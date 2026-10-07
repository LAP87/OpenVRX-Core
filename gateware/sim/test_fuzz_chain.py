"""The picture chain of M4 under seeded disturbances (model/fuzz_stream.py).

tb_chain.v runs two BT.656 streams through bt656_rx -> chan_capture -> mix_chan ->
line_mixer (mixer2) -> fb_backend (fb_sdram with sdram_model.v, or the low-latency
ring) -> fb_display. Each block is checked against its model on the input it really got:

  rx       every line marker against bt656.Receiver (field, line, HF, timing-code counts,
           length, complete); the noise meter's line counts against luma_outside()
  mixer    every decision, the current channel after it and every word against
           line_mixer_ref.Mixer, on arrival cycles computed from the byte streams
           (line_mixer_ref.arrival_cycle: the capture path's latency and the FIFO's
           synchroniser, clock edge for clock edge). Where that run differs, the model runs
           again on the cycles at which the RTL took each marker from its FIFO; if that run
           agrees, the arrival model is what differs, and the run counts as an edge case
           (logged, not a fault).
  store    every decision of the field store against fb_ref.FieldStore (as test_fb.py);
           every line read into the line buffer has the checksum of what the SDRAM held
  display  every output line shows the source line fb_ref.src_line gives and word 52 of
           the line read for it; in LOW, the word its ring slot held

and against six invariants that do not depend on the models:
  1. no X/Z on r, g, b, de, hsync, vsync after the first frame, and after the first frame
     following a mode switch;
  2. every frame, frame start to frame start, has V_TOTAL - 1 .. V_TOTAL + MAX_WAIT lines;
     shorter frames (genlock cuts) at least HOLD frames apart;
  3. every line read for a frame is stored in the buffer it is read from, or black;
  4. no SDRAM protocol error (sdram_model.v STRICT);
  5. the mixer's overflow is never set;
  6. every line shown with video comes from a camera field at most two fields older than
     the newest field the mixer had passed on when the frame started. Frames that a mode
     switch runs through are not checked (README: the frame in progress at a switch shows
     what the line buffer holds).

Scaled geometry (the clocks are the real ones): the fields of model/fuzz_stream.py
(24 or 29 active lines), an output frame of 87 lines of 1650 pixel clocks (1.92 ms,
720p's line) with 72 active lines (3 per source line, as 720 for 243), RT_NTSC 4,
RT_HYST 2, RT_PAL 8, RT_SPLIT 26 (between the scaled NTSC and PAL line counts).
Full geometry (run_seed(geometry='full'), fuzz_campaign.py --geometry full): 243/288
lines per field, 720p (750 lines, 720 active) and the field store's own thresholds;
four fields, about seven minutes a seed.

Seeds: FUZZ_SEEDS=0-199 (ranges and commas) runs those, FUZZ_CLASSES=a,b,c limits the
classes, and each result is appended to build/fuzz/<FUZZ_ROUND>.jsonl. Without
FUZZ_SEEDS the suite runs the seeds in SUITE_SEEDS. The campaign itself runs outside
pytest: sim/fuzz_campaign.py.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_fuzz_chain.py
"""
import bisect
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402
import fb_ref as fb  # noqa: E402
import fuzz_stream as fz  # noqa: E402
import line_mixer_ref as lm  # noqa: E402

T_S, T_P, H_TOTAL = fz.T_S, 13.4, 1650
H_ALT = 330                     # 720p50 lines are this much longer (fb_backend.v H_FP_ALT 440 against 110)
MAX_WAIT, HOLD = 8, 32
GEOMETRIES = {                  # output frame and field store thresholds per fuzz_stream geometry
    'scaled': dict(V_TOTAL=87, V_ACTIVE=72, V_FP=1, V_SYNC=1, RT=dict(RT_NTSC=4, RT_PAL=8, RT_HYST=2, RT_SPLIT=26)),
    'full': dict(V_TOTAL=750, V_ACTIVE=720, V_FP=5, V_SYNC=5, RT=dict(RT_NTSC=4, RT_PAL=44, RT_HYST=16, RT_SPLIT=270)),
}


def use_geometry(name):
    """Set the module's output geometry (one seed at a time per process)."""
    global V_TOTAL, V_ACTIVE, V_FP, V_SYNC, RT
    g = GEOMETRIES[name]
    V_TOTAL, V_ACTIVE, V_FP, V_SYNC, RT = g['V_TOTAL'], g['V_ACTIVE'], g['V_FP'], g['V_SYNC'], g['RT']


use_geometry('scaled')
T_PAIR = lm.T_PAIR_CYCLES
EXT_DELAY = 3                   # a control change at cycle C reaches mix_chan's bad flag at C + 3
EDGE_NS = 1000.0                # arrival differences this close to 0 or T_PAIR are reported as the edge
SUITE_SEEDS = (3, 5, 8, 13, 21, 34, 55, 89, 144, 233)
# Known faults with an issue: findings of these groups in LOW frames while the output locks after
# a switch to LOW (or after reset in LOW) are counted against the issue, not as new findings.
LOW_LOCK_ISSUE = 'LAP87/OpenVRX-Core#17'
LOW_LOCK_GROUPS = ('display/switch_video', 'display/ll_empty', 'display/ll_word', 'age/ll', 'output/xz')
LOW_LOCK_FRAMES = 4             # frames after the switch
BLACK = fb.BLACK_WORD

RTL = ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v', 'chan_capture.v', 'mix_chan.v',
       'line_mixer.v', 'snow_stats.v', 'noise_stats.v', 'mixer2.v', 'sdram_burst.v', 'field_phase.v',
       'fb_sdram.v', 'genlock_timing.v', 'ycbcr2rgb.v', 'cdc_sync.v', 'fb_display.v', 'fb_backend.v')


# ---------------------------------------------------------------- running the bench
def ctl_cycles(sc):
    """Control entries as (cycle, kind, value): the SDRAM clock count at whose edge it takes effect."""
    out, last = [], -1
    for t, kind, v in sc.ctl:
        c = max(last + 1, int(-(-((fz.RST_NS + t) / T_S - 0.5) // 1)))
        out.append((c, kind, v))
        last = c
    return out


def run_sim(sc, work, alter=None, timeout=3000):
    """Run tb_chain.v on scenario sc in directory work. alter: {rtl file: (text, replacement)}
    compiles an altered copy (negative controls). Returns the logs, split into fields."""
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    env = dict(os.environ)
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    bt656.write_hex(work / 'a.hex', sc.a)
    bt656.write_hex(work / 'b.hex', sc.b)
    ctl = ctl_cycles(sc) + [(0xFFFFFFFF, 0, 0)]
    (work / 'ctl.hex').write_text(''.join(f'{c << 3 | k << 1 | v:09x}\n' for c, k, v in ctl))
    p = dict(N_A=len(sc.a), N_B=len(sc.b), N_CTL=len(ctl), T_A=sc.t_a, T_B=round(sc.t_b, 6),
             START_A=round(sc.start_a, 3), START_B=round(sc.start_b, 3), LL=sc.ll0,
             V_TOTAL=V_TOTAL, V_ACTIVE=V_ACTIVE, V_FP=V_FP, V_SYNC=V_SYNC, **RT)
    rtl = [GW / 'rtl' / n for n in RTL]
    for fname, (old, new) in (alter or {}).items():
        text = (GW / 'rtl' / fname).read_text()
        assert text.count(old) == 1, f'{fname}: {old!r} not found once'
        (work / fname).write_text(text.replace(old, new))
        rtl = [work / fname if r.name == fname else r for r in rtl]
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_chain', *[f'-Ptb_chain.{k}={v}' for k, v in p.items()],
                    *map(str, rtl), str(HERE / 'sdram_model.v'), str(HERE / 'tb_chain.v')],
                   cwd=work, env=env, check=True, capture_output=True)
    run = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    logs = {}
    for name in ('mix', 'sd', 'pix'):
        path = work / f'{name}.txt'
        logs[name] = [ln.split() for ln in path.read_text().split('\n') if ln] if path.exists() else []
    logs['stdout'] = run.stdout[-3000:]
    return logs


def num(x):
    try:
        return int(x)
    except ValueError:
        return None                 # X/Z as printed by the simulator


def hexnum(x):
    try:
        return int(x, 16)
    except ValueError:
        return None


# ---------------------------------------------------------------- findings
class Findings:
    """Deviations: dict(block, kind, t (ns), detail). Edge cases of the mixer go to `edges`."""

    def __init__(self):
        self.items, self.edges, self.notes, self.known = [], [], [], []

    def add(self, block, kind, t_ns, detail):
        self.items.append(dict(block=block, kind=kind, t=round(t_ns or 0.0), detail=str(detail)[:500]))

    def first(self):
        return min(self.items, key=lambda d: d['t']) if self.items else None

    def groups(self):
        return sorted({f"{d['block']}/{d['kind']}" for d in self.items})


def cyc_ns(c):
    return (c + 0.5) * T_S


# ---------------------------------------------------------------- receiver
def receiver_records(sc):
    """Model line records per channel: [(index of the byte that completed it, record)]."""
    out = {}
    for ch, data in ((0, sc.a), (1, sc.b)):
        rx, recs = bt656.Receiver(), []
        for k, byte in enumerate(data):
            n = len(rx.records)
            rx.push(byte)
            if len(rx.records) > n:
                recs.append((k, rx.records[-1]))
        out[ch] = recs
    return out


def arrival_cycle(sc, ch, k, rec):
    """The SDRAM clock count at which mix_chan takes the marker of a line whose EAV timing code
    ends at byte k of channel ch (tb_chain.v clocks; see line_mixer_ref.arrival_cycle)."""
    t0, per = (sc.start_a, sc.t_a) if ch == 0 else (sc.start_b, sc.t_b)
    return lm.arrival_cycle(fz.RST_NS + t0, 2 * round(per / 2, 3), k, rec.active_count, T_S)


def check_rx(logs, recs, fd):
    """Line markers (K) and noise counts (N) against the model, per channel."""
    marks, noise = {0: [], 1: []}, {0: [], 1: []}
    for ev in logs['mix']:
        if ev[0] == 'K':
            marks[int(ev[1])].append([num(x) for x in ev[2:]])
        elif ev[0] == 'N':
            noise[int(ev[1])].append([num(x) for x in ev[2:]])
    for ch in (0, 1):
        for i, (m, (_, r)) in enumerate(zip(marks[ch], recs[ch])):
            cyc, f, line, complete, _mark, hf, xyb, xyc, length = m
            want = (r.field, r.line_in_field, int(r.active_count >= 1440), r.hf_energy & 0xFFFFF,
                    min(r.xy_bad, 15), min(r.xy_corrected, 15), min(r.length, 4095))
            got = (f, line, complete, hf, xyb, xyc, length)
            if got != want:
                fd.add('rx', 'record', cyc_ns(cyc), f'{"AB"[ch]} marker {i}: rtl {got} model {want} '
                       f'(active {r.active_count}, hf {r.hf_energy})')
                break
        if len(marks[ch]) != len(recs[ch]):
            n = min(len(marks[ch]), len(recs[ch]))
            t = cyc_ns(marks[ch][n - 1][0]) if n else 0
            fd.add('rx', 'count', t, f'{"AB"[ch]}: {len(marks[ch])} markers, model {len(recs[ch])} records')
        for i, (nz, (_, r)) in enumerate(zip(noise[ch], recs[ch])):
            want = min(1023, bt656.luma_outside(r.active))
            if nz[2] != want:
                t = cyc_ns(marks[ch][i][0]) if i < len(marks[ch]) else 0
                fd.add('rx', 'noise', t, f'{"AB"[ch]} line {i} {(r.field, r.line_in_field)}: count {nz[2]}, '
                       f'model {want} (active {r.active_count})')
                break
    return marks


# ---------------------------------------------------------------- mixer
def ext_fn(ctl, ch, delay):
    """ext_bad of channel ch as mix_chan sees it at a marker taken at cycle t."""
    ev = [(c, v) for c, k, v in ctl if k == ch]
    cs = [c for c, _ in ev]

    def f(t):
        i = bisect.bisect_right(cs, t - delay)
        return bool(ev[i - 1][1]) if i else False
    return f


def mixer_model(events, ctl):
    m = lm.Mixer(t_pair=T_PAIR, ext_bad=(ext_fn(ctl, 0, EXT_DELAY), ext_fn(ctl, 1, EXT_DELAY)))
    for t, ch, rec in events:
        m.push(ch, rec, t)
    m.finish()
    return m


def mixer_rtl(logs):
    dec, words, ov = [], [], None
    for ev in logs['mix']:
        if ev[0] == 'D':
            dec.append(tuple(num(x) for x in ev[1:]))
        elif ev[0] == 'O':
            words.append((num(ev[1]), num(ev[2]), num(ev[3]), hexnum(ev[4]), num(ev[5]), num(ev[6])))
        elif ev[0] == 'V':
            ov = int(ev[1])
    return dec, words, ov


def compare_mixer(m, dec, words):
    """First difference between model and RTL: (decision index or None, text), or None."""
    for i, (g, e, c) in enumerate(zip(dec, m.trace, m.curs)):
        if g[:5] != (*e, c):
            return i, f'decision {i}: rtl {g[:5]} model {(*e, c)}'
    if len(dec) != len(m.trace):
        return min(len(dec), len(m.trace)), f'{len(dec)} decisions, model {len(m.trace)}'
    for i, (g, e) in enumerate(zip(words, m.out)):
        if g[:4] != e:
            return None, f'word {i}: rtl {g[:4]} model {e}'
    if len(words) != len(m.out):
        return None, f'{len(words)} words, model {len(m.out)}'
    return None


def near_edge(ev):
    """Arrival differences between the channels within EDGE_NS of 0 or of T_PAIR (in ns)."""
    tb = sorted(t for t, ch, _ in ev if ch == 1)
    out = []
    for t, ch, _ in ev:
        if ch:
            continue
        j = bisect.bisect_left(tb, t - 2 * T_PAIR)
        for u in tb[j:j + 6]:
            d = abs(u - t)
            if min(d, abs(d - T_PAIR)) * T_S < EDGE_NS:
                out.append(round((u - t) * T_S))
    return out[:8]


def check_mixer(sc, logs, recs, marks, fd):
    """The RTL mixer against the model. Arrival cycles come from the streams
    (line_mixer_ref.arrival_cycle); where the model then differs from the RTL, it runs again on
    the cycles the RTL took the markers at. Returns (rtl decisions, rtl words)."""
    dec, words, ov = mixer_rtl(logs)
    ctl = ctl_cycles(sc)
    ev = sorted((arrival_cycle(sc, ch, k, r), ch, r) for ch in (0, 1) for k, r in recs[ch])
    for ch in (0, 1):                     # the arrival model itself
        for i, (mk, (k, r)) in enumerate(zip(marks[ch], recs[ch])):
            a = arrival_cycle(sc, ch, k, r)
            if mk[0] != a:
                fd.edges.append(dict(t=round(cyc_ns(mk[0])), detail=f'{"AB"[ch]} marker {i} taken at cycle {mk[0]}, '
                                     f'arrival model {a} (active {r.active_count})', near=[]))
                break
    m = mixer_model(ev, ctl)
    diff = compare_mixer(m, dec, words)
    if diff:
        ev2 = sorted((mk[0], ch, r) for ch in (0, 1) for mk, (_, r) in zip(marks[ch], recs[ch]))
        m2 = mixer_model(ev2, ctl)
        diff2 = compare_mixer(m2, dec, words)
        if diff2 is None:
            i = diff[0] if diff[0] is not None else len(dec) - 1
            t = cyc_ns(dec[min(i, len(dec) - 1)][5]) if dec else 0
            fd.edges.append(dict(t=round(t), detail=diff[1], near=near_edge(ev)))
            m = m2
        else:
            j = diff2[0] if diff2[0] is not None else len(dec) - 1
            t2 = cyc_ns(dec[min(j, len(dec) - 1)][5]) if dec else 0
            fd.add('mixer', 'decision' if diff2[0] is not None else 'words', t2,
                   f'cycle-exact: {diff2[1]}; from the streams: {diff[1]}')
    if ov is not None:
        fd.add('mixer', 'overflow', cyc_ns(ov), 'overflow set')
    elif m.overflow:
        fd.add('mixer', 'model_overflow', 0, 'the model overflowed, the RTL did not')
    return dec, words


# ---------------------------------------------------------------- where each word came from
def word_origins(sc, recs, marks, dec, words):
    """Camera field of every word the back end took from the mixer (-1: not known)."""
    queue = {0: [], 1: []}
    for ch in (0, 1):
        for mk, (k, r) in zip(marks[ch], recs[ch]):
            if mk[4]:                                    # stored in the ring
                ln = fz.camera_line(sc, ch, k - 4)       # the line's last byte before its EAV
                queue[ch].append(ln.k if ln is not None else -1)
    heads, line_org = {0: 0, 1: 0}, []
    for d in dec:
        use, pop = d[0], d[1]
        if use:
            src = 1 if use == lm.USE_B else 0
            line_org.append(queue[src][heads[src]] if heads[src] < len(queue[src]) else -1)
        for ch in (0, 1):
            if pop is not None and pop >> ch & 1:
                heads[ch] += 1
    org = [line_org[i // 360] if i // 360 < len(line_org) else -1 for i in range(len(words))]
    # newest camera field passed on, by cycle: (cycle of the word, running maximum)
    run, newest = [], -1
    for w, k in zip(words, org):
        if k > newest:
            newest = k
            run.append((w[5], newest))
    return org, run


def newest_at(run, cyc):
    i = bisect.bisect_left([c for c, _ in run], cyc)
    return run[i - 1][1] if i else -1


# ---------------------------------------------------------------- field store
def checksum(ws):
    cs = 0
    for w in ws:
        cs = ((cs << 1) | (cs >> 31)) & 0xFFFFFFFF
        cs ^= w
    return cs


class Frame:
    def __init__(self, show, prev, low, rt, cyc, lines, k_new):
        self.show, self.prev, self.low, self.rt, self.cyc, self.lines, self.k_new = show, prev, low, rt, cyc, lines, k_new
        self.want, self.got, self.org = [], [], []


def check_store(logs, words, org, run, fd):
    """Replay the store's log through fb_ref (a fresh model after each low-latency period);
    every read against the SDRAM content. Returns the frames with what they read."""
    mem, morg = {}, {}
    st, frames, pending, reads, prev_st = None, [], [], [], None
    stored = {}
    cur_org = -1
    for ev in logs['sd']:
        e = ev[0]
        if e == 'L':
            if ev[2] == '1':
                prev_st = st if st is not None else prev_st
                st, pending, reads = None, [], []
            continue
        if e in ('G', 'E', 'T', 'Q', 'end'):
            continue
        if e == 'w':
            addr, val = int(ev[1]), hexnum(ev[2])
            mem[addr], morg[addr] = val, cur_org
            continue
        if st is None:
            old_ok = prev_st.ok if prev_st is not None else None
            st = fb.FieldStore(**{k.lower(): v for k, v in RT.items()})
            if old_ok is not None:
                # fb_sdram.v keeps its stored-line bits in block RAM, which the reset during LOW does
                # not clear; a buffer's bits are cleared when the writer takes it for a field
                st.ok = [set(o) for o in old_ok]
            frames.append(None)                         # requests before the first frame start
        v = [num(x) for x in ev[1:]] if e not in ('R', 'S') else ev[1:]
        try:
            if e == 'A':
                if st.first_word(v[0], v[1]) != v[2]:
                    fd.add('store', 'decision', 0, f'first word: buffer {v[2]}, model {st.cur}')
                stored[st.cur] = set()
            elif e == 'N':
                if not st.is_new_field(v[0], v[1]) or (st.cur, (st.max_line + 1) & 1023) != (v[2], v[3]):
                    fd.add('store', 'decision', 0, f'publish {v}, model {(st.cur, st.max_line + 1)}')
                if st.first_word(v[0], v[1]) != v[4]:
                    fd.add('store', 'decision', 0, f'next buffer {v[4]}, model {st.cur}')
                stored[st.cur] = set()
            elif e == 'J':
                if not st.joined or not st.is_new_field(v[0], v[1]):
                    fd.add('store', 'decision', 0, f'joined field dropped {v}, model not')
                elif st.end_joined(v[0], v[1]) != v[2]:
                    fd.add('store', 'decision', 0, f'joined field dropped, next buffer {v[2]}, model {st.cur}')
                stored[st.cur] = set()
            elif e == 'P':
                if st.lines != v[0]:
                    fd.add('store', 'decision', 0, f'line count {v[0]}, model {st.lines}')
            elif e == 'W':
                f, line, idx, cyc, npop = v
                if npop < len(words) and words[npop][:3] != (f, line, idx):
                    fd.add('store', 'log', cyc_ns(cyc), f'word {npop} is {words[npop][:3]}, the writer took {(f, line, idx)}')
                if not st.have_field or st.is_new_field(f, line):
                    fd.add('store', 'decision', cyc_ns(cyc), f'word of line {(f, line)} taken outside a field')
                else:
                    st.word(f, line, idx, cyc)
                cur_org = org[npop] if npop < len(org) else -1
            elif e == 'M':
                st.line_stored(v[0])
                stored.setdefault(st.cur, set()).add(v[0])
            elif e == 'D':
                show, prev, low, rt = st.frame_start()
                cyc = v[5]
                if (show, st.prev, st.prev_ok, low, rt) != (v[0], v[1], bool(v[2]), bool(v[3]), bool(v[4])):
                    fd.add('store', 'decision', cyc_ns(cyc),
                           f'frame start: rtl {v[:5]}, model {(show, st.prev, st.prev_ok, low, rt)}')
                frames.append(Frame(show, prev, low, rt, cyc, st.lines, newest_at(run, cyc)))
            elif e == 'F':
                if frames[-1] is not None:
                    frames[-1].want.append(v[0])
                pending.append(st.fetch(v[0]))
            elif e == 'S':
                want = pending.pop(0) if pending else None
                src = (fb.BLANK, int(v[1])) if v[0] == 'blank' else (int(v[0]), int(v[1]))
                if want != src:
                    fd.add('store', 'decision', 0, f'line read from {src}, model {want}')
                if src[0] == fb.BLANK:
                    content, o = [BLACK] * 360, None
                else:
                    base = src[0] << 19 | src[1] << 9
                    content = [mem.get(base + i) for i in range(360)]
                    o = morg.get(base + 52)
                    if src[1] not in stored.get(src[0], ()):
                        o = 'unstored'                  # invariant 3, checked where the line is shown
                reads.append((frames[-1], src, content, o))
            elif e == 'R':
                if not reads:
                    fd.add('store', 'log', 0, 'line buffer written without a read')
                    continue
                fr, src, content, o = reads.pop(0)
                if (v[0] == '1') != (src[0] == fb.BLANK):
                    fd.add('store', 'read', 0, f'black line where {src} was due, or the reverse')
                want = 'x' if None in content else f'{checksum(content):08x}'
                if v[2] != want:
                    fd.add('store', 'read', 0, f'line {src}: checksum {v[2]}, the SDRAM held {want}')
                if fr is not None:
                    fr.got.append(content)
                    fr.org.append(o)
        except AssertionError as err:                   # the model refuses the event
            fd.add('store', 'model', 0, f'{ev}: {err}')
    return [f for f in frames if f is not None]


# ---------------------------------------------------------------- pixel domain
def pix_frames(pix):
    """Per output frame: dict(pc, lines, video, ll, low, src={y: line}, shown={y: word}, t={y: ns})."""
    out = []
    for ev in pix:
        if ev[0] == 'V':
            out.append(dict(pc=int(ev[1]), lines=num(ev[2]), video=num(ev[3]), ll=num(ev[4]), low=None,
                            src={}, shown={}, t={}))
        elif out and ev[0] == 'B':
            out[-1]['low'] = num(ev[1])
        elif out and ev[0] == 'Y':
            out[-1]['src'][int(ev[1])] = num(ev[2])
        elif out and ev[0] == 'X':
            out[-1]['shown'][int(ev[1])] = hexnum(ev[2])
            out[-1]['t'][int(ev[1])] = float(ev[3])
    return [f for f in out if len(f['src']) == V_ACTIVE and len(f['shown']) == V_ACTIVE]


def switch_windows(pix, starts):
    """(from, to) pixel clocks around each mode switch: the switch to the end of the first frame after it."""
    out = []
    for ev in pix:
        if ev[0] == 'M':
            sw = int(ev[1])
            later = [s for s in starts if s > sw]
            out.append((sw - V_TOTAL * H_TOTAL, later[1] if len(later) > 1 else 1 << 60))
    return out


def check_display(sc, logs, frames, words, org, run, fd):
    pix = logs['pix']
    pf_all = pix_frames(pix)
    starts = frame_starts(pix)
    sws = switch_windows(pix, starts)

    def in_switch(pc):
        return any(a <= pc < b for a, b in sws)

    end_pc = (fz.RST_NS + sc.end_ns) / T_P
    by_pc = [(round(fr.cyc * T_S / T_P), fr) for fr in frames]
    # low-latency ring: word 52 of each line as written, per slot
    ring = {}
    for ev in logs['sd']:
        if ev[0] == 'Q':
            ring.setdefault(int(ev[1]), []).append((float(ev[6]), hexnum(ev[4]), int(ev[5])))
    ring_t = {s: [q[0] for q in qs] for s, qs in ring.items()}
    checked = 0
    for pf in pf_all:
        if not pf['video'] or in_switch(pf['pc']) or pf['pc'] > end_pc:
            continue
        t_frame = pf['pc'] * T_P
        if pf['lines'] > V_ACTIVE:
            # fb_display.v steps at most one source line per output line: it scales up only. The
            # default of 240 lines (no line count yet) is more than the scaled frame's 72 lines.
            fd.notes.append(f"frame at {t_frame / 1e6:.2f} ms has {pf['lines']} source lines for {V_ACTIVE}: not checked")
            continue
        for y in range(V_ACTIVE):
            s = fb.src_line(y, pf['lines'], V_ACTIVE, pf['low'])
            if pf['src'][y] != s:
                fd.add('display', 'map', t_frame, f"output line {y}: source line {pf['src'][y]}, model {s} "
                       f"({pf['lines']} lines, low {pf['low']})")
                break
        if pf['ll']:
            k_new = newest_at(run, int(t_frame / T_S))
            for y in range(V_ACTIVE):
                slot = pf['src'][y] & 15
                t_rd = pf['t'][y] - T_P
                i = bisect.bisect_left(ring_t.get(slot, []), t_rd)
                if not i:
                    fd.add('display', 'll_empty', t_frame, f'output line {y}: ring slot {slot} never written')
                    break
                _, word, npop = ring[slot][i - 1]
                if pf['shown'][y] != word:
                    fd.add('display', 'll_word', t_frame, f"output line {y}: shows {pf['shown'][y]}, slot {slot} held {word}")
                    break
                k = org[npop] if npop < len(org) else -1
                if k >= 0 and k < k_new - 2:
                    fd.add('age', 'll', t_frame, f'output line {y}: camera field {k}, newest passed on {k_new}')
                    break
                checked += 1
            continue
        near = [fr for pc, fr in by_pc if abs(pc - (pf['pc'] - H_TOTAL)) < 40]
        if len(near) != 1:
            fd.add('display', 'no_decision', t_frame, f"no frame decision for the frame at pixel clock {pf['pc']}")
            continue
        fr = near[0]
        if pf['low'] != fr.low:
            fd.add('display', 'low', t_frame, f"lower field {pf['low']}, the store said {fr.low}")
        for y in range(V_ACTIVE):
            s = pf['src'][y]
            if s not in fr.want or fr.want.index(s) >= len(fr.got):
                fd.add('display', 'not_read', t_frame, f'output line {y}: source line {s} was not read')
                break
            j = fr.want.index(s)
            want = fr.got[j][52]
            if pf['shown'][y] != want:
                fd.add('display', 'word', t_frame, f"output line {y}: shows {pf['shown'][y]}, line read had {want}")
                break
            k = fr.org[j]
            if k == 'unstored':
                fd.add('store', 'unstored', t_frame, f'output line {y} shows source line {s}, read from a line '
                       'not stored since its buffer was taken')
                break
            if k is not None and k >= 0 and k < fr.k_new - 2:
                fd.add('age', 'buf', t_frame, f'output line {y} (source line {s}): camera field {k}, '
                       f'newest passed on {fr.k_new}')
                break
            checked += 1
    return checked


def frame_starts(pix):
    """Pixel clocks of the frame starts (x = 0, y = 0). While the timing generator is held in
    reset it sits at 0, 0 too; those clocks are not frame starts."""
    out = []
    for ev in pix:
        if ev[0] == 'V':
            pc = int(ev[1])
            if out and pc - out[-1] < H_TOTAL:
                out[-1] = pc
            else:
                out.append(pc)
    return out


def check_invariants(sc, logs, fd):
    pix = logs['pix']
    starts = frame_starts(pix)
    sws = switch_windows(pix, starts)
    # 1. X/Z, from the end of the first whole frame on (as test_fb.py)
    first_ok = starts[2] if len(starts) > 2 else 1 << 60
    for ev in pix:
        if ev[0] == 'Z':
            pc = int(ev[1])
            if pc >= first_ok and not any(a + V_TOTAL * H_TOTAL <= pc < b for a, b in sws):
                fd.add('output', 'xz', pc * T_P, f'X/Z on an output in the line ending at pixel clock {pc}')
                break
    # README (Bildvägen efter mixern): BUF -> LOW, the first frame after the switch has no video
    vids = {}
    for ev in pix:
        if ev[0] == 'V':
            vids[int(ev[1])] = num(ev[3])
    for ev in pix:
        if ev[0] == 'M' and ev[2] == '1':
            sw = int(ev[1])
            after = [s0 for s0 in starts if s0 > sw]
            if after and vids.get(after[0]):
                fd.add('display', 'switch_video', after[0] * T_P,
                       f'BUF -> LOW at pixel clock {sw}: the first frame after it has video')
    # 2. frame lengths, frame start to frame start (genlock_timing.v and its proof count them so)
    alt = {int(ev[1]): num(ev[5]) for ev in pix if ev[0] == 'V' and len(ev) > 5}
    cuts = []
    for i, (a, b) in enumerate(zip(starts[1:], starts[2:])):
        n = round((b - a) / (H_TOTAL + H_ALT * (alt.get(a) or 0)))
        if n < V_TOTAL - 1:
            cuts.append(i)
        elif n > V_TOTAL + MAX_WAIT:
            fd.add('output', 'long_frame', b * T_P, f'frame of {n} lines')
    for a, b in zip(cuts, cuts[1:]):
        if b - a < HOLD:
            fd.add('output', 'short_frames', starts[b + 1] * T_P, f'short frames {b - a} frames apart')
    # a cut that skips the vsync lines: the sink sees one long frame (noted, not a fault)
    vs = [int(ev[1]) for ev in pix if ev[0] == 'S']
    for a, b in zip(vs, vs[1:]):
        n = round((b - a) / H_TOTAL)
        if n > V_TOTAL + MAX_WAIT:
            fd.notes.append(f'vsync to vsync {n} lines at {b * T_P / 1e6:.2f} ms ({len(cuts)} cut frame(s))')
    # 4. SDRAM protocol
    sd = logs['sd']
    if not sd or sd[-1][0] != 'end':
        fd.add('sdram', 'protocol', 0, 'no end line: ' + ' | '.join(logs['stdout'].strip().split('\n')[-3:]))
    elif sd[-1][1] != '0':
        fd.add('sdram', 'protocol', 0, f'{sd[-1][1]} protocol errors')
    if not logs['mix'] or logs['mix'][-1][0] != 'end':
        fd.add('bench', 'end', 0, 'mix.txt has no end line')


def sort_known(sc, logs, fd):
    """Move the findings that LOW_LOCK_ISSUE explains to fd.known."""
    pix = logs['pix']
    starts = frame_starts(pix)
    wins = []
    sws = ([0] if sc.ll0 else []) + [int(ev[1]) for ev in pix if ev[0] == 'M' and ev[2] == '1']
    for sw in sws:
        later = [s0 for s0 in starts if s0 > sw]
        wins.append((sw, later[LOW_LOCK_FRAMES] if len(later) > LOW_LOCK_FRAMES else 1 << 60))
    keep = []
    for d in fd.items:
        pc = d['t'] / T_P
        if f"{d['block']}/{d['kind']}" in LOW_LOCK_GROUPS and any(a <= pc < b for a, b in wins):
            fd.known.append(dict(d, issue=LOW_LOCK_ISSUE))
        else:
            keep.append(d)
    fd.items = keep


# ---------------------------------------------------------------- one seed
def run_seed(seed, classes=None, work=None, alter=None, keep=False, n_fields=None, force=(), geometry='scaled'):
    """Generate, simulate and check one seed. Returns the result as a dict."""
    t0 = time.time()
    sc = fz.generate(seed, classes, n_fields=n_fields, force=force, geometry=geometry)
    use_geometry(geometry)
    work = work or HERE / 'build' / 'fuzz' / f'seed{seed}'
    fd = Findings()
    try:
        logs = run_sim(sc, work, alter)
    except subprocess.TimeoutExpired:
        fd.add('bench', 'timeout', 0, 'simulation timed out')
        logs = None
    checked = 0
    if logs:
        recs = receiver_records(sc)
        marks = check_rx(logs, recs, fd)
        dec, words = check_mixer(sc, logs, recs, marks, fd)
        org, run = word_origins(sc, recs, marks, dec, words)
        frames = check_store(logs, words, org, run, fd)
        checked = check_display(sc, logs, frames, words, org, run, fd)
        check_invariants(sc, logs, fd)
        sort_known(sc, logs, fd)
        if checked < (2 if geometry == 'scaled' else 1) * V_ACTIVE:
            fd.add('bench', 'few_lines', 0, f'only {checked} output lines checked')
    if not keep and not fd.items and work.exists():
        shutil.rmtree(work, ignore_errors=True)
    res = dict(seed=seed, classes=sc.classes_used(), enabled=None if classes is None else sorted(classes),
               std=sc.std, ll0=sc.ll0, geometry=geometry,
               result='fail' if fd.items else ('known' if fd.known else ('edge' if fd.edges else 'pass')),
               known=fd.known[:4],
               groups=fd.groups(), first=fd.first(), findings=fd.items[:12], edges=fd.edges[:4],
               notes=fd.notes[:4], checked=checked, seconds=round(time.time() - t0, 1), used=sc.used)
    return res


def parse_seeds(text):
    out = []
    for part in text.split(','):
        if '-' in part:
            a, b = part.split('-')
            out += range(int(a), int(b) + 1)
        elif part.strip():
            out.append(int(part))
    return out


def append_result(res, round_name):
    path = HERE / 'build' / 'fuzz' / f'{round_name}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as fh:
        fh.write(json.dumps(res) + '\n')


SEEDS = parse_seeds(os.environ['FUZZ_SEEDS']) if os.environ.get('FUZZ_SEEDS') else list(SUITE_SEEDS)
CLASSES = os.environ['FUZZ_CLASSES'].split(',') if os.environ.get('FUZZ_CLASSES') else None


@pytest.mark.parametrize('seed', SEEDS)
def test_chain_seed(seed):
    """One seed through the whole chain: no deviation from the models, no broken invariant.
    Differences that only the arrival times explain (the pairing window's edge) pass."""
    res = run_seed(seed, CLASSES)
    if os.environ.get('FUZZ_SEEDS'):
        append_result(res, os.environ.get('FUZZ_ROUND', 'adhoc'))
    assert res['result'] not in ('fail', 'crash'), json.dumps(dict(classes=res['classes'], first=res['first'],
                                                    groups=res['groups']), indent=1)


# Negative controls: an altered copy of one RTL file, a short seed, and the check that must see it.
NEGATIVE = {
    'rx': (0, [], {'bt656_rx.v': ('hf <= hf + ((dl2 > prev_y) ? dl2 - prev_y : prev_y - dl2);',
                                  "hf <= hf + ((dl2 > prev_y) ? dl2 - prev_y : 8'd0);")}, 'rx/record'),
    'mixer': (0, [], {'line_mixer.v': ("avg = ({1'b0, p} + {1'b0, q} + 9'd1) >> 1;",
                                       "avg = ({1'b0, p} + {1'b0, q}) >> 1;")}, 'mixer/'),
    'store': (0, [], {'fb_sdram.v': ("latest <= cur_buf; latest_v <= 1'b1;",
                                     "latest <= cur_buf; latest_v <= 1'b0;")}, 'store/decision'),
    'display': (0, [], {'fb_display.v': ("lb_raddr <= {ll ? src_cur[3:2] : 2'b00, src_cur[1:0], sx[9:1]};",
                                         "lb_raddr <= {ll ? src_cur[3:2] : 2'b00, src_cur[1:0], sx[9:1] + 9'd1};")},
                'display/word'),
    'ring': (49, ['mode_switch'], {'fb_backend.v': ("wire [12:0] lbw_addr = ll_s ? {e_line[3:0], e_idx} : {2'b00, lb_waddr};",
                                                    "wire [12:0] lbw_addr = ll_s ? {e_line[3:0] + 4'd1, e_idx} : {2'b00, lb_waddr};")},
             'display/ll_word'),
}


@pytest.mark.parametrize('block', sorted(NEGATIVE))
def test_chain_checks_catch_faults(block):
    """Negative controls for the checks above: each altered RTL file is seen by the check of its
    block (the receiver's HF, the mixer's rounding in a blend, the field store's latest field,
    the display's read address, the low-latency ring's slot). The 'ring' seed runs BUF, then LOW
    from 3.3 ms; the others have no disturbance. Six fields each."""
    seed, classes, alter, group = NEGATIVE[block]
    res = run_seed(seed, classes, work=HERE / 'build' / 'fuzz' / f'neg_{block}', alter=alter, n_fields=6)
    seen = res['groups'] + [f"{k['block']}/{k['kind']}" for k in res['known']]     # also what #17 explains
    assert any(g.startswith(group) for g in seen), (block, seen, res['first'])
