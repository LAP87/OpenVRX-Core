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
           every read has a checksum of the SDRAM snapshot at its accepted first burst
  display  every output line shows the source line fb_ref.src_line gives and word 52 of
           the line read for it; in LOW, the word its ring slot held

and against six invariants that do not depend on the models:
  1. no X/Z on r, g, b, de, hsync, vsync after the first frame, and after the first frame
     following a mode switch;
  2. every frame has exactly one vsync pulse and V_TOTAL - 1 .. V_TOTAL + MAX_WAIT lines,
     except a cut and its immediately following recovery frame; cut groups are at least HOLD
     frame starts apart and may contain no third short frame;
  3. every line read for a frame is stored in the buffer it is read from, or black;
  4. no SDRAM protocol error (sdram_model.v STRICT);
  5. the mixer's overflow is never set;
  6. every line shown with video comes from a field of the store at most two fields older
     than the one it writes when the frame starts (age/store); and no camera field that both
     receivers delivered in step goes missing between a line shown and the newest field the
     mixer had passed on, when the line is more than two camera fields older (age/lost_field). Frames that a mode
     switch runs through are not checked (README: the frame in progress at a switch shows
     what the line buffer holds).

LOW display video additionally requires both the current LOW-period alive flag and the timing
generator's trigger-started flag. A separate post-switch sample checks that have_video was cleared
for the frame in progress; one eligible trigger-started frame at the new mode boundary may show.
Every run must also finish with one bounded DRAIN receipt and no outstanding read or burst state.

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
import ll_ring_ref as ring  # noqa: E402

T_S, T_P, H_TOTAL = fz.T_S, 13.4, 1650
H_TOTAL_ALT = 1980              # H_FP_ALT adds 330 clocks to the default 1650-clock line
MAX_WAIT, HOLD = 8, 32
DRAIN_MAX_CYCLES, DRAIN_STABLE_CYCLES = 4096, 4
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
# Known faults with an issue. Core #17 (video in LOW before the output had locked) is fixed: a LOW
# frame has video only when a trigger of this LOW period started it, so no group is counted
# against it any more (LOW_LOCK_GROUPS is empty; the machinery stays for the next such issue).
LOW_LOCK_ISSUE = 'LAP87/OpenVRX-Core#17'
LOW_LOCK_GROUPS = ()
LOW_LOCK_FRAMES = 4             # frames after the switch
# Output fields the word stream does not mark (same F bit, first line above the last one sent):
# the store joins them to the field before. Age findings within three field periods after such a
# start are counted against the issue.
HIDDEN_ISSUE = 'LAP87/OpenVRX-Core#18'
BLACK = fb.BLACK_WORD

RTL = ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v', 'chan_capture.v', 'mix_chan.v',
       'line_mixer.v', 'snow_stats.v', 'noise_stats.v', 'mixer2.v', 'sdram_burst.v', 'field_phase.v',
       'fb_sdram.v', 'genlock_timing.v', 'ycbcr2rgb.v', 'cdc_sync.v', 'fb_display.v', 'vblend.v', 'fb_backend.v')


# ---------------------------------------------------------------- running the bench
def ctl_cycles(sc):
    """Control entries as (cycle, kind, value): the SDRAM clock count at whose edge it takes effect."""
    out, last = [], -1
    for t, kind, v in sc.ctl:
        c = max(last + 1, int(-(-((fz.RST_NS + t) / T_S - 0.5) // 1)))
        out.append((c, kind, v))
        last = c
    return out


def run_sim(sc, work, alter=None, timeout=3000, stall_drain=False, gate_probe=0):
    """Run tb_chain.v on scenario sc in directory work. alter: {rtl file: (text, replacement)}
    compiles an altered copy (negative controls). stall_drain withholds data after an accepted
    read; gate_probe forces one LOW frame-gate input for exactly one checked frame."""
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
             V_TOTAL=V_TOTAL, V_ACTIVE=V_ACTIVE, V_FP=V_FP, V_SYNC=V_SYNC,
             DRAIN_STALL_READ=int(stall_drain), GATE_PROBE=int(gate_probe), **RT)
    rtl = [GW / 'rtl' / n for n in RTL]
    for fname, (old, new) in (alter or {}).items():
        text = (GW / 'rtl' / fname).read_text()
        assert text.count(old) == 1, f'{fname}: {old!r} not found once'
        (work / fname).write_text(text.replace(old, new))
        rtl = [work / fname if r.name == fname else r for r in rtl]
    subprocess.run(['iverilog', '-g2012', '-I', str(HERE), '-o', 'sim.vvp', '-s', 'tb_chain', *[f'-Ptb_chain.{k}={v}' for k, v in p.items()],
                    *map(str, rtl), str(HERE / 'sdram_model.v'), str(HERE / 'tb_chain.v')],
                   cwd=work, env=env, check=True, capture_output=True)
    run = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    logs = {}
    for name in ('mix', 'sd', 'pix', 'margin'):
        path = work / f'{name}.txt'
        logs[name] = [ln.split() for ln in path.read_text().split('\n') if ln] if path.exists() else []
    logs['stdout'] = run.stdout[-3000:]
    logs['stderr'] = run.stderr[-3000:]
    logs['returncode'] = run.returncode
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
        self.hidden = []                # ns: output fields the stream does not mark (#18)

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
    if not any(d['block'] == 'mixer' for d in fd.items):
        prev = None
        for (use, _, f, line), new, d in zip(m.trace, m.newfield, dec):
            if not use:
                continue
            if new and prev is not None and f == prev[0] and line > prev[1]:
                fd.hidden.append(cyc_ns(d[5]))
            prev = (f, line)
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
    pairs = {}                                           # camera field -> pairs decided in it
    for d in dec:
        use, pop = d[0], d[1]
        if pop == 3 and heads[0] < len(queue[0]):
            pairs[queue[0][heads[0]]] = pairs.get(queue[0][heads[0]], 0) + 1
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
    AGE_FIELDS.clear()
    AGE_FIELDS.update(set(org) | {k for k, n in pairs.items() if n})
    LOST_PAIRED.clear()
    LOST_PAIRED.update({k for k, n in pairs.items() if n} - set(org))
    return org, run


# Camera fields that count for the age of a line: those the mixer passed words of, and those in
# which the two receivers paired. LOST_PAIRED: fields both receivers delivered in step that never
# reached the output (finding 6). Invariant 6 is checked strictly on the field store's own fields
# (age/store); a line more than two camera fields old is a finding only when a field in
# LOST_PAIRED lies between (age/lost_field), and a note otherwise: a receiver that missed a
# blanking interval numbers on, and the store keeps the two camera fields as one.
AGE_FIELDS, LOST_PAIRED = set(), set()


def age(k, k_new):
    return sum(1 for f in range(k + 1, k_new + 1) if f in AGE_FIELDS)


def camera_age(fd, k, k_new, t, what):
    if k is None or k < 0 or age(k, k_new) <= 2:
        return False
    lost = [f for f in range(k + 1, k_new + 1) if f in LOST_PAIRED]
    if lost:
        fd.add('age', 'lost_field', t, f'{what}: camera field {k}, newest passed on {k_new}; '
               f'camera field(s) {lost} paired but never shown')
        return True
    fd.notes.append(f'{what}: camera field {k}, newest passed on {k_new} (fields merged or lost upstream)')
    return True                         # one note per frame


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
        self.want, self.got, self.org, self.bad, self.sorg = [], [], [], [], []
        self.sfield_new = 0             # the store's field being written at the frame start


class StoreFrames(list):
    """Store frame decisions plus independently derived provenance for BUF ring writes."""

    def __init__(self):
        super().__init__()
        self.buffer_samples = {}         # (physical address, timestamp) -> source metadata


def check_store(logs, words, org, run, fd):
    """Replay the store's log through fb_ref (a fresh model after each low-latency period);
    every read against the SDRAM content. Returns the frames with what they read."""
    mem, morg = {}, {}
    st, frames, pending, selected, prev_st = None, StoreFrames(), [], [], None
    active_read = None
    sfield, buf_field = 0, {}             # the store's fields in order; buffer -> its field
    stored = {}
    cur_org = -1
    for ev in logs['sd']:
        e = ev[0]
        if e == 'L':
            if ev[2] == '1':
                prev_st = st if st is not None else prev_st
                st, pending, selected, active_read = None, [], [], None
            continue
        if e in ('G', 'E', 'T', 'Q', 'LBTRACE', 'LBEND', 'LW', 'DRAIN', 'end'):
            continue
        if e == 'w':
            addr, val = int(ev[1]), hexnum(ev[2])
            if active_read is not None:
                fd.add('store', 'log', 0,
                       f'SDRAM write at {addr} interleaved with read {active_read["src"]} '
                       f'started at cycle {active_read["cycle"]}')
            mem[addr], morg[addr] = val, cur_org
            continue
        if e == 'L52':
            try:
                addr, data = int(ev[1]), hexnum(ev[2])
                _npop, low, buf, line, blank = map(num, ev[3:8])
                t_ns = float(ev[8])
            except (IndexError, TypeError, ValueError):
                fd.add('store', 'log', 0, f'malformed line-buffer word-52 marker {ev}')
                continue
            if data is None or low is None or addr % 512 != 52 or (
                    not low and (line is None or blank is None or (not blank and buf is None))):
                fd.add('store', 'log', t_ns, f'invalid line-buffer word-52 marker {ev}')
                continue
            if low:
                continue
            if blank:
                if data != BLACK:
                    fd.add('store', 'read', t_ns, f'blank BUF word-52 at address {addr} is {data:08x}, not BLACK')
                frames.buffer_samples[(addr, t_ns)] = dict(origin=None, src=(fb.BLANK, line), blank=True)
                continue
            read = active_read
            if read is None or not read['started']:
                fd.add('store', 'log', t_ns,
                       f'BUF word-52 write at address {addr} has no accepted SDRAM-read snapshot')
                continue
            slot = addr // 512
            if read['slot'] != slot:
                fd.add('store', 'log', t_ns,
                       f'BUF word-52 address {addr} uses slot {slot}, accepted read selected slot {read["slot"]}')
            if (buf, line) != read['src']:
                fd.add('store', 'log', t_ns,
                       f'BUF word-52 source {(buf, line)} does not match accepted read {read["src"]}')
            if read['content'] is None or read['content'][52] is None:
                fd.add('store', 'read', t_ns,
                       f'BUF word-52 at address {addr} has no independent SDRAM value in the accepted-read snapshot')
            elif data != read['content'][52]:
                fd.add('store', 'read', t_ns,
                       f'BUF word-52 at address {addr} is {data:08x}, accepted-read snapshot has {read["content"][52]:08x}')
            frames.buffer_samples[(addr, t_ns)] = dict(origin=read['origin'], src=read['src'],
                                                        sfield=read['sfield'], blank=False)
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
                sfield += 1
                buf_field[st.cur] = sfield
            elif e == 'N':
                if not st.is_new_field(v[0], v[1]) or (st.cur, (st.max_line + 1) & 1023) != (v[2], v[3]):
                    fd.add('store', 'decision', 0, f'publish {v}, model {(st.cur, st.max_line + 1)}')
                if st.first_word(v[0], v[1]) != v[4]:
                    fd.add('store', 'decision', 0, f'next buffer {v[4]}, model {st.cur}')
                stored[st.cur] = set()
                sfield += 1
                buf_field[st.cur] = sfield
            elif e == 'J':
                if not st.joined or not st.is_new_field(v[0], v[1]):
                    fd.add('store', 'decision', 0, f'joined field dropped {v}, model not')
                elif st.end_joined(v[0], v[1]) != v[2]:
                    fd.add('store', 'decision', 0, f'joined field dropped, next buffer {v[2]}, model {st.cur}')
                stored[st.cur] = set()
                sfield += 1
                buf_field[st.cur] = sfield
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
                frames[-1].sfield_new = sfield
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
                    content = [BLACK] * 360
                    o = None
                    sf = sfield
                else:
                    # S records the selected source, before the arbiter can accept a read. The
                    # current eight-word writer burst may still update this line, so defer the
                    # independent SDRAM snapshot until the accepted-start marker (I).
                    content = None
                    o = None
                    sf = None
                    if src[1] not in stored.get(src[0], ()):
                        o = 'unstored'                  # invariant 3, checked where the line is shown
                    sf = buf_field.get(src[0], -99)
                selected.append(dict(frame=frames[-1], src=src, content=content, origin=o, sfield=sf,
                                     started=False, slot=None, cycle=None))
            elif e == 'I':
                buf, line, slot, addr, cyc = v
                if any(value is None for value in v):
                    fd.add('store', 'log', 0, f'malformed accepted read-start marker {ev}')
                    continue
                if active_read is not None:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read start at cycle {cyc} before read {active_read["src"]} '
                           f'from cycle {active_read["cycle"]} completed')
                    continue
                if not selected:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read start for buffer {buf} line {line} without a source selection')
                    continue
                read = selected[0]
                src = read['src']
                if src[0] == fb.BLANK:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read start for buffer {buf} line {line} while blank line {src[1]} was selected')
                    continue
                if (buf, line) != src:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read start {(buf, line)} does not match selected source {src}')
                expected_addr = (buf << 19) | (line << 9)
                if addr != expected_addr:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read address {addr} is not line base {expected_addr} for {(buf, line)}')
                if addr & 0x1FF:
                    fd.add('store', 'log', cyc_ns(cyc),
                           f'accepted read address {addr} is not the first burst of a line')
                if slot not in range(4):
                    fd.add('store', 'log', cyc_ns(cyc), f'accepted read selected invalid line-buffer slot {slot}')
                # Snapshot the independent full-word memory model at the accepted request. R is
                # checked against this snapshot, including for reads outside a decided frame.
                read['content'] = [mem.get(addr + i) for i in range(360)]
                read['origin'] = morg.get(addr + 52)
                if src[1] not in stored.get(src[0], ()):
                    read['origin'] = 'unstored'        # invariant 3, checked where the line is shown
                read['sfield'] = buf_field.get(src[0], -99)
                read.update(started=True, slot=slot, cycle=cyc, address=addr)
                active_read = read
            elif e == 'R':
                if not selected:
                    fd.add('store', 'log', 0, 'line buffer write completed without a source selection')
                    continue
                read = selected.pop(0)
                fr, src = read['frame'], read['src']
                content, o, sf = read['content'], read['origin'], read['sfield']
                if (v[0] == '1') != (src[0] == fb.BLANK):
                    fd.add('store', 'read', 0, f'black line where {src} was due, or the reverse')
                if src[0] == fb.BLANK:
                    if active_read is not None:
                        fd.add('store', 'log', 0,
                               f'blank line {src[1]} completed while read {active_read["src"]} was active')
                else:
                    if not read['started'] or active_read is not read:
                        fd.add('store', 'log', 0,
                               f'nonblank read {src} completed without its accepted-start snapshot')
                    elif num(v[1]) != read['slot']:
                        fd.add('store', 'log', 0,
                               f'read {src} completed in slot {v[1]}, accepted start selected slot {read["slot"]}')
                    if active_read is read:
                        active_read = None
                if content is None:
                    content = [None] * 360
                    bad = f'line {src}: no accepted read-start memory snapshot'
                else:
                    want = 'x' if None in content else f'{checksum(content):08x}'
                    # Every R checksum remains strict, including reads before a frame decision.
                    bad = None if v[2] == want else f'line {src}: checksum {v[2]}, the SDRAM held {want} when the read began'
                if bad:
                    fd.add('store', 'read', 0, bad)
                if fr is not None:
                    fr.got.append(content)
                    fr.org.append(o)
                    fr.bad.append(bad)
                    fr.sorg.append(sf)
                elif bad:
                    fd.notes.append('read outside a frame: ' + bad)
        except AssertionError as err:                   # the model refuses the event
            fd.add('store', 'model', 0, f'{ev}: {err}')
    if selected:
        fd.add('store', 'log', 0,
               f'{len(selected)} selected source line(s) ended without a completed read')
    if active_read is not None:
        fd.add('store', 'log', 0,
               f'accepted read {active_read["src"]} from cycle {active_read["cycle"]} never completed')
    result = StoreFrames()
    result.extend(f for f in frames if f is not None)
    result.buffer_samples = frames.buffer_samples
    return result


def check_margins(logs, fd):
    """The margin checks of margin_checks.vh (formal/README.md, items 4 and 5): frame_low and
    ll_low have arrived a pixel clock before line 0 takes them, and a BUF line-buffer slot holds
    its line up to the last word when the display starts reading it."""
    kinds = {'F': ('display', 'low_margin'), 'W': ('display', 'low_margin'), 'R': ('store', 'line_late')}
    for row in logs.get('margin', []):
        try:
            kind, t_ns, ok, margin = row[0], float(row[1]), row[2], float(row[3])
            block, what = kinds[kind]
        except (IndexError, KeyError, ValueError):
            fd.add('bench', 'margin_log', 0, f'malformed margin line {row}')
            continue
        if ok != '1' or margin < T_P:
            fd.add(block, what, t_ns, f'{kind}: ok {ok}, margin {margin:.1f} ns (needs {T_P} ns)')


def check_drain(logs, fd):
    """Require one bounded final receipt proving fetch and SDRAM burst state are idle."""
    sd = logs.get('sd', [])
    receipts = [ev for ev in sd if ev and ev[0] == 'DRAIN']
    if len(receipts) != 1:
        fd.add('store', 'drain', 0, f'expected one final DRAIN receipt, got {receipts[:2]}')
        return
    ev = receipts[0]
    if len(ev) != 19:
        fd.add('store', 'drain', 0, f'malformed DRAIN receipt {ev}')
        return
    if len(sd) < 2 or sd[-1][0] != 'end' or sd[-2] != ev:
        fd.add('store', 'drain', 0, 'DRAIN is not the final SDRAM record before the protocol end marker')
        return
    try:
        values = [int(x) for x in ev[2:]]
    except ValueError:
        fd.add('store', 'drain', 0, f'non-numeric DRAIN state {ev}')
        return
    (cycles, stable, fetch_ev, fetch_req, look, fetching, rd_inflight, req_valid,
     grp_ready, writing, grp_mask, burst_state, stall_armed, pix_frozen, pc, x, y) = values
    if ev[1] != 'pass':
        fd.add('store', 'drain', 0, f'drain ended with status {ev[1]} after {cycles} clocks: {ev}')
    elif logs.get('returncode', 0) != 0:
        fd.add('store', 'drain', 0, f'simulator exited {logs["returncode"]} despite a pass receipt')
    elif (cycles < DRAIN_STABLE_CYCLES or cycles > DRAIN_MAX_CYCLES or
          stable != DRAIN_STABLE_CYCLES or stable > cycles):
        fd.add('store', 'drain', 0, f'drain bound/count is invalid: {ev}')
    elif (fetch_ev, fetch_req, look, fetching, rd_inflight, req_valid, grp_ready, writing,
          grp_mask, burst_state, stall_armed, pix_frozen) != (0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1):
        fd.add('store', 'drain', 0, f'drain receipt has outstanding fetch or SDRAM state: {ev}')
    elif pc <= 0 or x != 0 or y != V_ACTIVE:
        fd.add('store', 'drain', 0, f'drain did not freeze at the declared vertical-blank boundary: {ev}')


# ---------------------------------------------------------------- pixel domain
def pix_frames(pix):
    """Per output frame, including the LOW source-alive and timing-trigger gate samples."""
    out = []
    for ev in pix:
        if ev[0] == 'V':
            out.append(dict(pc=int(ev[1]), lines=num(ev[2]), video=num(ev[3]), ll=num(ev[4]), low=None,
                            alt=num(ev[5]) if len(ev) > 5 else None,
                            alive=num(ev[7]) if len(ev) > 7 else None,
                            triggered=num(ev[8]) if len(ev) > 8 else None,
                            src={}, shown={}, t={}))
        elif out and ev[0] == 'B':
            out[-1]['low'] = num(ev[1])
        elif out and ev[0] == 'Y':
            out[-1]['src'][int(ev[1])] = num(ev[2])
        elif out and ev[0] == 'X':
            out[-1]['shown'][int(ev[1])] = hexnum(ev[2])
            out[-1]['t'][int(ev[1])] = float(ev[3])
    return [f for f in out if len(f['src']) == V_ACTIVE and len(f['shown']) == V_ACTIVE]


def video_event(pc, lines, video, ll, alt, nlines, alive=0, triggered=0):
    """Build a complete V log row while keeping the historical first seven fields fixed."""
    return ['V', str(pc), str(lines), str(video), str(ll), str(alt), str(nlines),
            str(alive), str(triggered)]


def check_gate_probe(logs, gate_probe, fd):
    """Bind an optional testbench force to one exact V sample; never infer video from DUT internals."""
    pix = logs.get('pix', [])
    markers = [ev for ev in pix if ev and ev[0] == 'GATE']
    if gate_probe == 0:
        if markers:
            fd.add('bench', 'gate_probe', 0, f'unexpected GATE marker while probe is disabled: {markers[:2]}')
        return
    if gate_probe not in (1, 2):
        fd.add('bench', 'gate_probe', 0, f'unsupported GATE_PROBE value {gate_probe}')
        return
    if len(markers) != 1:
        fd.add('bench', 'gate_probe', 0, f'expected exactly one GATE marker, got {markers[:2]}')
        return
    ev = markers[0]
    if len(ev) != 5:
        fd.add('bench', 'gate_probe', 0, f'malformed GATE marker {ev}')
        return
    try:
        kind, frame_pc, original_alive, original_triggered = map(int, ev[1:])
    except ValueError:
        fd.add('bench', 'gate_probe', 0, f'non-numeric GATE marker {ev}')
        return
    if (kind, original_alive, original_triggered) != (gate_probe, 1, 1):
        fd.add('bench', 'gate_probe', frame_pc, f'GATE marker does not bind the requested original gates: {ev}')
        return
    frames = [row for row in pix if row and row[0] == 'V' and len(row) > 1 and num(row[1]) == frame_pc]
    if len(frames) != 1:
        fd.add('bench', 'gate_probe', frame_pc, f'GATE marker has {len(frames)} matching V records: {ev}')
        return
    frame = frames[0]
    if len(frame) != 9:
        fd.add('bench', 'gate_probe', frame_pc, f'GATE target V record is malformed: {frame}')
        return
    ll, alive, triggered = (num(frame[i]) for i in (4, 7, 8))
    wanted = (1, 0, 1) if gate_probe == 1 else (1, 1, 0)
    if (ll, alive, triggered) != wanted:
        fd.add('bench', 'gate_probe', frame_pc,
               f'GATE probe {gate_probe} expected target V (LOW, alive, triggered)={wanted}, '
               f'observed {(ll, alive, triggered)}: {frame}')


def switch_windows(pix, starts):
    """(from, to) pixel clocks around each mode switch: the switch to the end of the first frame after it."""
    out = []
    for ev in pix:
        if ev[0] == 'M':
            sw = int(ev[1])
            later = [s for s in starts if s > sw]
            out.append((sw - V_TOTAL * H_TOTAL, later[1] if len(later) > 1 else 1 << 60))
    return out


def display_switch_windows(pix, starts, alt):
    """Display-data exclusion using the frame's active-area width, with the old end bound.

    ALT is sampled in each V record. Unknown ALT keeps the original full-frame exclusion,
    so malformed timing metadata cannot create new display coverage.
    """
    if alt not in (0, 1):
        return switch_windows(pix, starts)
    line_clocks = H_TOTAL_ALT if alt else H_TOTAL
    active_span = V_ACTIVE * line_clocks
    out = []
    for ev in pix:
        if ev[0] == 'M':
            sw = int(ev[1])
            later = [s for s in starts if s > sw]
            out.append((sw - active_span, later[1] if len(later) > 1 else 1 << 60))
    return out


def check_display(sc, logs, frames, words, org, run, fd):
    pix = logs['pix']
    pf_all = pix_frames(pix)
    starts = frame_starts(pix)
    sws = {alt: display_switch_windows(pix, starts, alt) for alt in (0, 1, None)}

    def in_switch(pc, alt):
        return any(a <= pc < b for a, b in sws[alt if alt in (0, 1) else None])

    end_pc = (fz.RST_NS + sc.end_ns) / T_P
    by_pc = [(round(fr.cyc * T_S / T_P), fr) for fr in frames]
    # Rebuild the shared ring from accepted physical-address runs and word-52
    # writes. The expected source data and completion history never use a DUT
    # validity bit or the displayed X value as an oracle.
    ring_model = ring.LineBuffer()
    markers = [ev for ev in logs['sd'] if ev[0] == 'LBTRACE']
    trace_required = bool(pix)
    if trace_required and markers != [['LBTRACE', '1']]:
        fd.add('display', 'ring_trace', 0, f'expected one LBTRACE 1 marker, got {markers[:2]}')
    endings = [ev for ev in logs['sd'] if ev[0] == 'LBEND']
    ring_runs, ring_samples = [], []
    for ev in logs['sd']:
        if ev[0] == 'LW':
            try:
                first, last, first_cyc, last_cyc = map(int, ev[1:5])
                first_ns, last_ns = map(float, ev[5:7])
                if first > last or first_cyc > last_cyc or first_ns > last_ns:
                    raise ValueError('range ends before it starts')
                ring_runs.append((first_ns, last_ns, first, last))
            except (IndexError, ValueError):
                fd.add('display', 'ring_trace', 0, f'malformed accepted-write run {ev}')
        elif ev[0] == 'L52':
            try:
                addr, data = int(ev[1]), hexnum(ev[2])
                npop, low, buf, line, blank = (num(x) for x in ev[3:8])
                t_ns = float(ev[8])
                if data is None or any(v is None for v in (npop, low)) or addr % 512 != 52:
                    raise ValueError('invalid address, data, or mode metadata')
                ring_samples.append((t_ns, addr, data, npop, bool(low), buf, line, blank))
            except (IndexError, TypeError, ValueError):
                fd.add('display', 'ring_trace', 0, f'malformed word-52 accepted-write marker {ev}')
    if trace_required and len(endings) != 1:
        fd.add('display', 'ring_trace', 0, f'expected one LBEND summary, got {endings[:2]}')
    elif endings:
        try:
            logged_writes, logged_runs = map(int, endings[0][1:3])
            expanded_writes = sum(last - first + 1 for _, _, first, last in ring_runs)
            if (logged_writes, logged_runs) != (expanded_writes, len(ring_runs)):
                fd.add('display', 'ring_trace', 0,
                       f'LBEND counts {(logged_writes, logged_runs)}, expanded accepted trace '
                       f'has {(expanded_writes, len(ring_runs))}')
        except (IndexError, ValueError):
            fd.add('display', 'ring_trace', 0, f'malformed LBEND summary {endings[0]}')
    for t_ns, addr, data, npop, low, buf, line, blank in ring_samples:
        # A physical-address trace describes what happened, not what should
        # have happened. Bind LOW writes to the independently checked mixer
        # stream even when the wrong slot leaves the displayed slot virgin.
        if low:
            if not 0 <= npop < len(words):
                fd.add('display', 'll_origin', t_ns,
                       f'LOW word-52 write has invalid mixer word index {npop}')
            else:
                _, source_line, source_index, source_word, *_ = words[npop]
                expected_addr = ((source_line & 15) << 9) | source_index
                if source_index != 52 or addr != expected_addr or data != source_word:
                    fd.add('display', 'll_word', t_ns,
                           f'LOW write {npop}: address {addr}, data {data:08x}; '
                           f'mixer expects address {expected_addr}, index {source_index}, '
                           f'data {source_word:08x}')
        matches = [r for r in ring_runs if r[2] <= addr <= r[3] and r[0] <= t_ns <= r[1]]
        if len(matches) != 1:
            fd.add('display', 'ring_trace', t_ns,
                   f'word-52 write at address {addr} belongs to {len(matches)} accepted-address runs')
    for first_ns, last_ns, first, last in ring_runs:
        for addr in range(first, last + 1):
            if addr % 512 != 52:
                continue
            count = sum(1 for t_ns, sample_addr, *_ in ring_samples
                        if sample_addr == addr and first_ns <= t_ns <= last_ns)
            if count != 1:
                fd.add('display', 'ring_trace', last_ns,
                       f'accepted-address run {first}..{last} contains address {addr} with {count} word-52 markers')
    ring_events = ([(last_ns, 0, first, last) for first_ns, last_ns, first, last in ring_runs] +
                   [(t_ns, 1, addr, data, npop, low, buf, line, blank)
                    for t_ns, addr, data, npop, low, buf, line, blank in ring_samples])
    for event in sorted(ring_events, key=lambda e: (e[0], e[1])):
        if event[1] == 0:
            try:
                ring_model.accept_range(event[2], event[3], event[0])
            except ValueError as err:
                fd.add('display', 'ring_trace', event[0], str(err))
            continue
        t_ns, _, addr, data, npop, low, buf, line, blank = event
        provenance = dict(npop=npop, low=low, buf=buf, line=line, blank=bool(blank))
        if not low:
            source = getattr(frames, 'buffer_samples', {}).get((addr, t_ns))
            if source is None:
                provenance['origin_missing'] = True
            else:
                provenance.update(source)
        try:
            ring_model.record_sample(addr, data, t_ns, provenance)
        except ValueError as err:
            fd.add('display', 'ring_trace', t_ns, str(err))
    checked = 0
    for pf in pf_all:
        if not pf['video']:
            continue
        t_frame = pf['pc'] * T_P
        if pf['alt'] not in (0, 1):
            fd.add('display', 'alt_metadata', t_frame,
                   f"complete video frame at pixel clock {pf['pc']} has unknown timing ALT {pf['alt']!r}")
            continue
        if in_switch(pf['pc'], pf['alt']) or pf['pc'] > end_pc:
            continue
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
                t_valid = pf['t'][y] - 2 * T_P
                if not ring_model.valid_at(slot, t_valid):
                    want = BLACK
                    provenance = None
                else:
                    sample = ring_model.sample_event_at(slot, 52, t_rd)
                    if sample is None:
                        fd.add('display', 'll_empty', t_frame,
                               f'output line {y}: initialized ring slot {slot} has no earlier word-52 write')
                        break
                    _, want, provenance = sample
                if pf['shown'][y] != want:
                    fd.add('display', 'll_word', t_frame,
                           f'output line {y}: shows {pf["shown"][y]}, ring model expects {want:08x} '
                           f'for slot {slot} (valid {ring_model.valid_at(slot, t_valid)})')
                    break
                if provenance is not None:
                    if provenance.get('low'):
                        npop = provenance.get('npop')
                        if npop is None or npop < 0 or npop >= len(org):
                            fd.add('display', 'll_origin', t_frame,
                                   f'output line {y}: LOW word-52 at slot {slot} has invalid mixer word index {npop}')
                            break
                        k = org[npop]
                        if not isinstance(k, int) or k < 0:
                            fd.add('display', 'll_origin', t_frame,
                                   f'output line {y}: LOW mixer word {npop} has no independent camera-field origin')
                            break
                    elif provenance.get('blank'):
                        k = None
                    elif provenance.get('origin') == 'unstored':
                        fd.add('store', 'unstored', t_frame,
                               f'LOW output line {y}: BUF slot {slot} contains a line not stored since its buffer was taken')
                        break
                    elif provenance.get('origin_missing') or not isinstance(provenance.get('origin'), int) or provenance['origin'] < 0:
                        fd.add('display', 'll_origin', t_frame,
                               f'output line {y}: initialized BUF slot {slot} has no independent camera-field origin')
                        break
                    else:
                        k = provenance['origin']
                    if k is not None and camera_age(fd, k, k_new, t_frame, f'LOW output line {y}'):
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
            if fr.bad[j]:
                fd.add('store', 'read', t_frame, f'output line {y}: {fr.bad[j]}')
                break
            want = fr.got[j][52]
            if pf['shown'][y] != want:
                fd.add('display', 'word', t_frame, f"output line {y}: shows {pf['shown'][y]}, line read had {want}")
                break
            k = fr.org[j]
            if k == 'unstored':
                fd.add('store', 'unstored', t_frame, f'output line {y} shows source line {s}, read from a line '
                       'not stored since its buffer was taken')
                break
            if fr.sfield_new - fr.sorg[j] > 2:
                fd.add('age', 'store', t_frame, f'output line {y} (source line {s}): store field {fr.sorg[j]}, '
                       f'the store writes field {fr.sfield_new}')
                break
            if camera_age(fd, k, fr.k_new, t_frame, f'output line {y} (source line {s})'):
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
    # M's third payload field samples have_video one pixel clock after the synchronized mode edge.
    # That is the display gate after fb_display applies its mode-switch reset.
    mode_events = []
    for ev in pix:
        if ev[0] != 'M':
            continue
        try:
            sw, mode, gate = int(ev[1]), num(ev[2]), num(ev[3])
        except (IndexError, ValueError):
            fd.add('display', 'switch_metadata', 0, f'malformed mode-switch marker {ev}')
            continue
        if len(ev) != 4 or mode not in (0, 1) or gate not in (0, 1):
            fd.add('display', 'switch_metadata', sw * T_P, f'invalid mode-switch metadata {ev}')
            continue
        mode_events.append((sw, mode))
        if gate != 0:
            fd.add('display', 'switch_video', sw * T_P,
                   f'mode switch to {mode} at pixel clock {sw}: have_video remained {gate} after clear')

    # V is sampled at x=1, after fb_display evaluates line_start at x=0. M records the
    # effective synchronized mode-change edge. Only a change on that x=0 edge can win the
    # mode-reset assignment over the frame-start gate and explain one blank eligible frame;
    # in the logged clocks that is exactly V.pc == M.pc + 1. Later/earlier frames must show.
    low_clear_race_starts = {sw + 1 for sw, mode in mode_events if mode == 1}
    for ev in pix:
        if ev[0] != 'V':
            continue
        try:
            pc = int(ev[1])
            if len(ev) != 9:
                raise ValueError(f'expected 9 fields, got {len(ev)}')
            lines, video, ll = (num(ev[i]) for i in (2, 3, 4))
            alive, triggered = num(ev[7]), num(ev[8])
        except (IndexError, ValueError):
            fd.add('output', 'trigger_metadata', 0, f'malformed V frame marker {ev}')
            continue
        if any(value not in (0, 1) for value in (video, ll, alive, triggered)):
            fd.add('output', 'trigger_metadata', pc * T_P, f'unknown video/mode gate in V frame marker {ev}')
            continue
        if video and ll and not (alive and triggered):
            fd.add('display', 'trigger_gate', pc * T_P,
                   f'LOW frame at pixel clock {pc} has video={video}, ll_alive={alive}, triggered={triggered}')
        if ll and alive and triggered and not video and pc not in low_clear_race_starts:
            fd.add('display', 'trigger_missing', pc * T_P,
                   f'eligible LOW frame at pixel clock {pc} has no video outside the one-clock switch-start race')
    # 2. Frame length and sync pulse count, frame start to frame start. The bench counts output
    # lines directly because 720p50 lines are longer and the wait limit can add full lines.
    nlines = {int(ev[1]): num(ev[6]) for ev in pix if ev[0] == 'V' and len(ev) > 6}
    vs = [int(ev[1]) for ev in pix if ev[0] == 'S']
    intervals = []
    for i, (a, b) in enumerate(zip(starts[1:], starts[2:])):
        n = nlines[b] if nlines.get(b) is not None else round((b - a) / H_TOTAL)
        sync_count = sum(a <= s < b for s in vs)
        if sync_count != 1:
            fd.add('output', 'vsync_count', b * T_P,
                   f'frame at pixel clock {a}: {sync_count} vsync pulses (expected 1)')
        intervals.append((i, a, b, n))
        if n > V_TOTAL + MAX_WAIT:
            fd.add('output', 'long_frame', b * T_P, f'frame of {n} lines')
    short = [i for i, _, _, n in intervals if n < V_TOTAL - 1]
    groups = []
    for i in short:
        if not groups or i != groups[-1][-1] + 1:
            groups.append([i])
        else:
            groups[-1].append(i)
    for group in groups:
        if len(group) > 2:
            fd.add('output', 'short_frames', starts[group[0] + 1] * T_P,
                   f'{len(group)} adjacent short frames; only a cut and its recovery may be short')
        elif len(group) == 2:
            recovery_lines = intervals[group[1]][3]
            min_recovery_lines = V_ACTIVE + V_FP + V_SYNC + 1
            if recovery_lines < min_recovery_lines:
                fd.add('output', 'short_frames', starts[group[1] + 1] * T_P,
                       f'recovery frame has {recovery_lines} lines; needs at least {min_recovery_lines}')
    for left, right in zip(groups, groups[1:]):
        if right[0] - left[0] < HOLD:
            fd.add('output', 'short_frames', starts[right[0] + 1] * T_P,
                   f'cut groups start {right[0] - left[0]} frame starts apart, HOLD is {HOLD}')
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
    g = fz.GEOM[sc.geometry][sc.std]
    span = 3 * (g['vbi'] + g['var'][1] + 1) * g['line'] * fz.T_A
    keep = []
    for d in fd.items:
        pc = d['t'] / T_P
        if f"{d['block']}/{d['kind']}" in LOW_LOCK_GROUPS and any(a <= pc < b for a, b in wins):
            fd.known.append(dict(d, issue=LOW_LOCK_ISSUE))
        elif d['block'] == 'age' and any(h <= d['t'] < h + span for h in fd.hidden):
            fd.known.append(dict(d, issue=HIDDEN_ISSUE))
        elif d['block'] == 'age' and d['kind'] == 'lost_field' and sc.ahead:
            fd.notes.append(f"age, a channel a field ahead of the camera (no decoder can): {d['detail']}")
        else:
            keep.append(d)
    fd.items = keep


# ---------------------------------------------------------------- one seed
def run_seed(seed, classes=None, work=None, alter=None, keep=False, n_fields=None, force=(), geometry='scaled',
             density=1.0, gate_probe=0, recovery_fields=0):
    """Generate, simulate and check one seed. Returns the result as a dict."""
    t0 = time.time()
    if type(recovery_fields) is not int or recovery_fields < 0:
        raise ValueError('recovery_fields must be a nonnegative integer')
    sc = fz.generate(seed, classes, n_fields=n_fields, force=force, geometry=geometry, density=density)
    recovery = None
    if recovery_fields:
        from fuzz_recovery import append_camera_fields
        sc, recovery = append_camera_fields(sc, fields=recovery_fields)
    use_geometry(geometry)
    work = work or HERE / 'build' / 'fuzz' / f'seed{seed}'
    fd = Findings()
    try:
        logs = run_sim(sc, work, alter, gate_probe=gate_probe)
    except subprocess.TimeoutExpired:
        fd.add('bench', 'timeout', 0, 'simulation timed out')
        logs = None
    checked = 0
    if logs:
        check_gate_probe(logs, gate_probe, fd)
        check_drain(logs, fd)
        check_margins(logs, fd)
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
    if not keep and not recovery_fields and gate_probe == 0 and not fd.items and work.exists():
        shutil.rmtree(work, ignore_errors=True)
    res = dict(seed=seed, classes=sc.classes_used(), enabled=None if classes is None else sorted(classes),
               std=sc.std, ll0=sc.ll0, geometry=geometry, density=density, n_fields=n_fields,
               result='fail' if fd.items else ('known' if fd.known else ('edge' if fd.edges else 'pass')),
               known=fd.known[:4],
               groups=fd.groups(), first=fd.first(), findings=fd.items[:12], edges=fd.edges[:4],
               notes=fd.notes[:4], checked=checked, seconds=round(time.time() - t0, 1), used=sc.used)
    if recovery_fields:
        res.update(recovery_fields=recovery_fields, recovery=recovery)
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
    'trigger': (1201, ['mode_switch'],
                {'fb_display.v': ("if (line_start && y == 0) have_video <= ll ? (ll_alive && ll_triggered) : have_pub;",
                                  "if (line_start && y == 0) have_video <= ll ? ll_alive : have_pub;")},
                'display/trigger_gate', 2),
    'alive': (1201, ['mode_switch'],
              {'fb_display.v': ("if (line_start && y == 0) have_video <= ll ? (ll_alive && ll_triggered) : have_pub;",
                                "if (line_start && y == 0) have_video <= ll ? ll_triggered : have_pub;")},
              'display/trigger_gate', 1),
    'switch_clear': (1201, ['mode_switch'],
                     {'fb_display.v': ("if (ll != ll_d) have_video <= 1'b0;",
                                       "if (ll != ll_d) have_video <= have_video;")},
                     'display/switch_video'),
}


@pytest.mark.parametrize('block', sorted(NEGATIVE))
def test_chain_checks_catch_faults(block):
    """Negative controls for the checks above: each altered RTL file is seen by the check of its
    block (the receiver's HF, the mixer's rounding in a blend, the field store's latest field,
    the display's read address, the low-latency ring's slot, and the LOW alive/trigger/mode gates).
    The 'ring' seed runs BUF, then LOW from 3.3 ms. Gate mutants use the ten-field probe stimulus;
    other mutants retain their six-field cases."""
    seed, classes, alter, group, *probe = NEGATIVE[block]
    gate_probe = probe[0] if probe else 0
    n_fields = 10 if gate_probe else 6
    work = HERE / 'build' / 'fuzz' / f'neg_{block}'
    res = run_seed(seed, classes, work=work, alter=alter, n_fields=n_fields, gate_probe=gate_probe)
    seen = res['groups'] + [f"{k['block']}/{k['kind']}" for k in res['known']]     # also what #17 explains
    assert any(g.startswith(group) for g in seen), (block, seen, res['first'])
    if gate_probe:
        pix = [ln.split() for ln in (work / 'pix.txt').read_text().splitlines() if ln]
        marker = [ev for ev in pix if ev[0] == 'GATE']
        assert len(marker) == 1 and int(marker[0][1]) == gate_probe, marker
        frame = [ev for ev in pix if ev[0] == 'V' and len(ev) == 9 and ev[1] == marker[0][2]]
        assert len(frame) == 1 and frame[0][3] == '1', (marker, frame)


@pytest.mark.parametrize('gate_probe', [1, 2])
def test_gate_probe_baseline_native(tmp_path, gate_probe):
    """The unmodified display blanks a frame when either required LOW gate is forced low."""
    work = tmp_path / f'gate_probe_{gate_probe}'
    res = run_seed(1201, ['mode_switch'], work=work, keep=True, n_fields=10, gate_probe=gate_probe)
    assert res['result'] == 'pass' and res['checked'] >= 144, res
    assert not (res['groups'] or res['known'] or res['edges'] or res['notes']), res
    pix = [ln.split() for ln in (work / 'pix.txt').read_text().splitlines() if ln]
    marker = [ev for ev in pix if ev[0] == 'GATE']
    assert len(marker) == 1, marker
    frame = [ev for ev in pix if ev[0] == 'V' and len(ev) == 9 and ev[1] == marker[0][2]]
    assert len(frame) == 1 and frame[0][3] == '0', (marker, frame)
    if gate_probe == 1:
        assert frame[0][7:] == ['0', '1'], frame[0]
    else:
        assert frame[0][7:] == ['1', '0'], frame[0]


def test_drain_timeout_catches_stalled_accepted_read_native(tmp_path):
    """A real accepted read with withheld data must end in a bounded drain failure."""
    use_geometry('scaled')
    sc = fz.generate(1201, ['mode_switch'], n_fields=6)
    logs = run_sim(sc, tmp_path / 'drain_stall', stall_drain=True)
    receipts = [ev for ev in logs['sd'] if ev and ev[0] == 'DRAIN']
    accepted = [ev for ev in logs['sd'] if ev and ev[0] == 'I']
    assert len(receipts) == 1 and receipts[0][1] == 'fail_2', receipts[:2]
    assert len(receipts[0]) == 19 and receipts[0][14] == '1', receipts[0]
    assert accepted and logs['returncode'] != 0, (accepted[:1], logs['returncode'], logs['stdout'])

def test_read_without_frame_decision_keeps_checksum_control():
    """A corrupt read before a frame decision must remain a finding.
    Seed 126 showed that lack of a store decision does not imply blank RGB."""
    bad = checksum([BLACK] * 360) ^ 1
    logs = dict(sd=[['F', '0'], ['S', 'blank', '0'], ['R', '1', '0', f'{bad:08x}']])
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert fd.groups() == ['store/read'], fd.items


def accepted_read_fixture(*, outside_frame=False, marker=True, start=(0, 5), slot=2,
                          r_slot=None, wrong_checksum=False, duplicate=False,
                          interleave=False, second_source=False):
    """Pure SDRAM-log fixture with the last half of an active writer burst after S."""
    base = (0 << 19) | (5 << 9)
    line_words = [((i + 1) * 0x01020305) & 0xFFFFFFFF for i in range(360)]
    old_words = list(line_words)
    for i in range(148, 152):
        old_words[i] ^= 0x80000001

    sd = [['A', '0', '0', '0'], ['W', '0', '5', '0', '1', '0'], ['M', '5']]
    if second_source:
        sd.extend([['W', '0', '6', '0', '2', '1'], ['M', '6']])
    if not outside_frame:
        sd.append(['D', '0', '0', '0', '0', '1', '2'])

    sd.append(['F', '5'])
    if second_source:
        sd.append(['F', '6'])
    for i, word in enumerate(old_words):
        sd.append(['w', str(base + i), f'{word:08x}'])
    sd.append(['S', '0', '5'])
    if second_source:
        sd.append(['S', '0', '6'])
    for i in range(148, 152):
        sd.append(['w', str(base + i), f'{line_words[i]:08x}'])
    if marker:
        start_buf, start_line = start
        start_addr = (start_buf << 19) | (start_line << 9)
        sd.append(['I', str(start_buf), str(start_line), str(slot), str(start_addr), '100'])
        if duplicate:
            sd.append(['I', str(start_buf), str(start_line), str(slot), str(start_addr), '101'])
        if interleave:
            sd.append(['w', str(base + 52), f'{(line_words[52] ^ 1):08x}'])
    if not second_source:
        read_slot = slot if r_slot is None else r_slot
        read_sum = checksum(line_words) ^ (1 if wrong_checksum else 0)
        sd.append(['R', '0', str(read_slot), f'{read_sum:08x}'])
    sd.append(['end', '0'])
    return dict(sd=sd), old_words, line_words


def test_store_snapshots_at_accepted_read_after_active_write_finishes():
    logs, old_words, line_words = accepted_read_fixture()
    assert checksum(old_words) != checksum(line_words)
    fd = Findings()
    frames = check_store(logs, [], [], [], fd)
    assert fd.groups() == [], fd.items
    assert len(frames) == 1 and frames[0].bad == [None]


@pytest.mark.parametrize('fixture, expected', [
    ({'marker': False}, 'no accepted read-start memory snapshot'),
    ({'start': (1, 5)}, 'does not match selected source'),
    ({'duplicate': True}, 'before read'),
    ({'interleave': True}, 'interleaved with read'),
    ({'r_slot': 3}, 'completed in slot'),
])
def test_store_rejects_bad_read_start_binding(fixture, expected):
    logs, _, _ = accepted_read_fixture(**fixture)
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert 'store/log' in fd.groups() or 'store/read' in fd.groups(), fd.items
    assert any(expected in item['detail'] for item in fd.items), fd.items


def test_store_read_checksum_remains_strict_outside_frame():
    logs, _, _ = accepted_read_fixture(outside_frame=True, wrong_checksum=True)
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert 'store/read' in fd.groups(), fd.items
    assert any('checksum' in item['detail'] for item in fd.items), fd.items


def test_store_rejects_out_of_order_accepted_read_start():
    logs, _, _ = accepted_read_fixture(second_source=True, start=(0, 6))
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert 'store/log' in fd.groups(), fd.items
    assert any('does not match selected source' in item['detail'] for item in fd.items), fd.items


def test_store_rejects_missing_final_read_completion_at_eof():
    logs, _, _ = accepted_read_fixture()
    logs['sd'] = [ev for ev in logs['sd'] if ev[0] != 'R']
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert 'store/log' in fd.groups(), fd.items
    assert any('never completed' in item['detail'] for item in fd.items), fd.items


def l52_for_fixture(logs, data, *, low='0', buf='0', line='5', blank='0', slot=2):
    marker = ['L52', str(slot * 512 + 52), f'{data:08x}', '0', low, buf, line, blank, '2000.0']
    start = next((i for i, ev in enumerate(logs['sd']) if ev[0] == 'I'), None)
    if start is None:
        start = next((i for i, ev in enumerate(logs['sd']) if ev[0] == 'R'), len(logs['sd']))
        logs['sd'].insert(start, marker)
    else:
        logs['sd'].insert(start + 1, marker)
    return marker


def test_store_checks_buf_word52_against_accepted_snapshot():
    logs, old_words, _ = accepted_read_fixture()
    l52_for_fixture(logs, old_words[52])
    fd = Findings()
    frames = check_store(logs, [], [], [], fd)
    assert fd.groups() == [], fd.items
    assert frames.buffer_samples[(2 * 512 + 52, 2000.0)]['src'] == (0, 5)


@pytest.mark.parametrize('fault, expected', [
    ('wrong_word', 'accepted-read snapshot'),
    ('missing_start', 'no accepted SDRAM-read snapshot'),
    ('missing_buf', 'invalid line-buffer word-52 marker'),
    ('missing_line', 'invalid line-buffer word-52 marker'),
])
def test_store_rejects_bad_buf_word52_trace(fault, expected):
    logs, old_words, _ = accepted_read_fixture(marker=(fault != 'missing_start'))
    data = old_words[52] ^ (1 if fault == 'wrong_word' else 0)
    l52_for_fixture(logs, data, buf='x' if fault == 'missing_buf' else '0',
                    line='x' if fault == 'missing_line' else '5')
    fd = Findings()
    check_store(logs, [], [], [], fd)
    assert 'store/log' in fd.groups() or 'store/read' in fd.groups(), fd.items
    assert any(expected in item['detail'] for item in fd.items), fd.items


def test_store_ignores_unused_low_metadata_but_accepts_blank_buf_without_buffer_id():
    low_only = {'sd': [['L52', str(9 * 512 + 52), 'a5000034', '10', '1', 'x', 'x', 'x', '100.0']]}
    fd = Findings()
    check_store(low_only, [], [], [], fd)
    assert not fd.items, fd.items

    blank_sum = checksum([BLACK] * 360)
    blank = {'sd': [
        ['F', '3'], ['S', 'blank', '3'],
        ['L52', str(2 * 512 + 52), f'{BLACK:08x}', '0', '0', 'x', '3', '1', '100.0'],
        ['R', '1', '2', f'{blank_sum:08x}'], ['end', '0'],
    ]}
    fd = Findings()
    check_store(blank, [], [], [], fd)
    assert not fd.items, fd.items


@pytest.mark.parametrize('line_count, expected', [
    (758, []), (759, ['output/long_frame']), (748, ['output/short_frames']),
])
def test_frame_length_uses_counted_lines_when_width_changes(line_count, expected):
    """A mixed-width frame at the wait limit is valid; long/close short frames still fail."""
    use_geometry('full')
    # 750 ordinary lines and eight PAL-width waiting lines: division by
    # 1650 yields 760, while the bench counts 758 real lines.
    span = 750 * H_TOTAL + 8 * 1980
    pix = []
    for k in range(5):
        pix.extend((video_event(k * span, 288, 1, 1, 0, line_count, 1, 1),
                    ['S', str(k * span + 5 * H_TOTAL)]))
    sc = type('Scenario', (), {'end_ns': 5 * span * T_P})()
    fd = Findings()
    try:
        check_invariants(sc, dict(pix=pix, sd=[['end', '0']], mix=[['end']], stdout=''), fd)
        assert fd.groups() == expected, fd.items
    finally:
        use_geometry('scaled')


def timing_fixture(frame_lines, sync_counts=None):
    """Minimal pixel log for exercising invariant 2 without a gateware simulation."""
    sync_counts = sync_counts or [1] * len(frame_lines)
    starts, pc = [], 0
    for n in frame_lines:
        starts.append(pc)
        pc += n * H_TOTAL
    starts.append(pc)
    pix = []
    for k, start in enumerate(starts):
        n = frame_lines[k - 1] if k else V_TOTAL
        pix.append(video_event(start, V_ACTIVE, 0, 0, 0, n))
    for i, (a, n) in enumerate(zip(starts, frame_lines)):
        for pulse in range(sync_counts[i]):
            pix.append(['S', str(a + min(n - 1, 1 + pulse) * H_TOTAL)])
    return pix


def invariant_findings(pix):
    fd = Findings()
    check_invariants(type('Scenario', (), {'end_ns': 1e12})(),
                     dict(pix=pix, sd=[['end', '0']], mix=[['end']], stdout=''), fd)
    return fd.groups(), fd.items


def triggered_pixel_fixture(records, *, switch_video=0):
    """Frame trace with a LOW switch; each record is (video, alive, triggered)."""
    span = V_TOTAL * H_TOTAL
    starts = [1_000_000 + k * span for k in range(len(records))]
    pix = [['M', str(starts[0] - 1), '1', str(switch_video)]]
    for start, (video, alive, triggered) in zip(starts, records):
        pix.append(video_event(start, V_ACTIVE, video, 1, 0, V_TOTAL, alive, triggered))
        pix.append(['S', str(start + 5)])
    return pix


def drain_values():
    # cycles, stable, fetch event/request, look, fetching, read/request, queued group,
    # active write, group mask, burst state, stall arm, frozen, pixel cycle, x, y
    return [12, DRAIN_STABLE_CYCLES, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 1000, 0, V_ACTIVE]


def drain_receipt(status='pass', *, values=None):
    return ['DRAIN', status, *map(str, drain_values() if values is None else values)]


def test_drain_receipt_accepts_only_a_single_bounded_idle_snapshot():
    fd = Findings()
    check_drain({'sd': [drain_receipt(), ['end', '0']], 'returncode': 0}, fd)
    assert not fd.items, fd.items


def _assert_drain_detail(sd, returncode, expected_detail):
    fd = Findings()
    check_drain({'sd': sd, 'returncode': returncode}, fd)
    assert len(fd.items) == 1, fd.items
    item = fd.items[0]
    assert (item['block'], item['kind']) == ('store', 'drain'), item
    assert expected_detail in item['detail'], item


def test_drain_rejects_missing_duplicate_or_misplaced_receipt():
    receipt = drain_receipt()
    end = ['end', '0']
    interleaved = ['LBEND', '0', '0']
    expected = 'expected one final DRAIN receipt'
    _assert_drain_detail([], 0, expected)
    _assert_drain_detail([receipt, receipt, end], 0, expected)
    placement = 'DRAIN is not the final SDRAM record before the protocol end marker'
    _assert_drain_detail([receipt], 0, placement)
    _assert_drain_detail([receipt, interleaved, end], 0, placement)


def test_drain_rejects_malformed_and_unknown_receipt():
    malformed = drain_receipt()[:-1]
    _assert_drain_detail([malformed, ['end', '0']], 0, 'malformed DRAIN receipt')
    _assert_drain_detail([drain_receipt('unknown'), ['end', '0']], 0,
                         'drain ended with status unknown after 12 clocks')


@pytest.mark.parametrize('receipt, returncode, expected_detail', [
    (drain_receipt('fail_2'), 1, 'drain ended with status fail_2 after 12 clocks'),
    (drain_receipt(values=[12, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1, 1000, 0, V_ACTIVE]),
     0, 'drain bound/count is invalid'),
    (drain_receipt(values=[12, 4, 0, 0, 'x', 0, 0, 0, 0, 0, 0, 2, 0, 1, 1000, 0, V_ACTIVE]),
     0, 'non-numeric DRAIN state'),
])
def test_drain_reaches_failed_and_unsettled_state_checks(receipt, returncode, expected_detail):
    _assert_drain_detail([receipt, ['end', '0']], returncode, expected_detail)


@pytest.mark.parametrize('name, index, value', [
    ('fetch event CDC', 2, 1), ('fetch request CDC', 3, 1), ('lookup', 4, 1),
    ('fetching', 5, 1), ('read in flight', 6, 1), ('request valid', 7, 1),
    ('queued writer group', 8, 1), ('active writer', 9, 1), ('nonempty group mask', 10, 1),
    ('active burst', 11, 1), ('stall hook', 12, 1), ('unfrozen pixel clock', 13, 0),
])
def test_drain_rejects_each_outstanding_or_unsettled_state(name, index, value):
    values = drain_values()
    values[index] = value
    _assert_drain_detail([drain_receipt(values=values), ['end', '0']], 0,
                         'drain receipt has outstanding fetch or SDRAM state')


def test_drain_rejects_nonzero_exit_even_with_valid_final_receipt():
    _assert_drain_detail([drain_receipt(), ['end', '0']], 1,
                         'simulator exited 1 despite a pass receipt')


def gate_probe_fixture(probe, *, video=0, target=None, marker=True, duplicate_marker=False,
                       marker_kind=None, marker_pc=None, original=(1, 1), malformed=False,
                       duplicate_v=False):
    frame_pc = 9000
    alive, triggered = target or ((0, 1) if probe == 1 else (1, 0))
    marker_kind = probe if marker_kind is None else marker_kind
    marker_pc = frame_pc if marker_pc is None else marker_pc
    pix = []
    if marker:
        row = ['GATE', str(marker_kind), str(marker_pc), str(original[0]), str(original[1])]
        if malformed:
            row.pop()
        pix.append(row)
        if duplicate_marker:
            pix.append(row.copy())
    frame = video_event(frame_pc, V_ACTIVE, video, 1, 0, V_TOTAL, alive, triggered)
    pix.append(frame)
    if duplicate_v:
        pix.append(frame.copy())
    return {'pix': pix}


@pytest.mark.parametrize('probe', [1, 2])
def test_gate_probe_checker_accepts_exact_frame_binding_without_using_video_as_oracle(probe):
    for video in (0, 1):
        fd = Findings()
        check_gate_probe(gate_probe_fixture(probe, video=video), probe, fd)
        assert not fd.items, fd.items


@pytest.mark.parametrize('fault', [
    'missing', 'duplicate', 'malformed', 'wrong_kind', 'wrong_frame', 'wrong_original',
    'forced_input_high', 'other_input_low', 'unknown_input', 'missing_v_flags',
    'wrong_mode', 'duplicate_v',
])
def test_gate_probe_checker_rejects_unbound_or_invalid_evidence(fault):
    kwargs = {}
    if fault == 'missing':
        kwargs['marker'] = False
    elif fault == 'duplicate':
        kwargs['duplicate_marker'] = True
    elif fault == 'malformed':
        kwargs['malformed'] = True
    elif fault == 'wrong_kind':
        kwargs['marker_kind'] = 2
    elif fault == 'wrong_frame':
        kwargs['marker_pc'] = 9001
    elif fault == 'wrong_original':
        kwargs['original'] = (0, 1)
    elif fault == 'forced_input_high':
        kwargs['target'] = (1, 1)
    elif fault == 'other_input_low':
        kwargs['target'] = (0, 0)
    elif fault == 'unknown_input':
        kwargs['target'] = ('x', 1)
    elif fault == 'missing_v_flags':
        kwargs['missing_v_flags'] = True
    elif fault == 'wrong_mode':
        kwargs['target'] = (0, 1)
        kwargs['wrong_mode'] = True
    elif fault == 'duplicate_v':
        kwargs['duplicate_v'] = True
    fixture = gate_probe_fixture(1, **{k: v for k, v in kwargs.items()
                                       if k not in ('wrong_mode', 'missing_v_flags')})
    if fault == 'wrong_mode':
        frame = next(ev for ev in fixture['pix'] if ev[0] == 'V')
        frame[4] = '0'
    elif fault == 'missing_v_flags':
        frame = next(ev for ev in fixture['pix'] if ev[0] == 'V')
        del frame[7:]
    fd = Findings()
    check_gate_probe(fixture, 1, fd)
    assert fd.groups() == ['bench/gate_probe'], (fault, fd.items)


def test_gate_probe_marker_is_forbidden_when_hook_is_disabled():
    fd = Findings()
    check_gate_probe(gate_probe_fixture(1), 0, fd)
    assert fd.groups() == ['bench/gate_probe'], fd.items


@pytest.mark.parametrize('alive, triggered', [(0, 1), (1, 0), (0, 0)])
def test_low_video_requires_alive_and_triggered(alive, triggered):
    records = [(1, 1, 1), (1, alive, triggered), (1, 1, 1), (1, 1, 1), (1, 1, 1)]
    groups, items = invariant_findings(triggered_pixel_fixture(records))
    assert 'display/trigger_gate' in groups, items


def test_valid_triggered_first_frame_after_switch_is_allowed():
    groups, items = invariant_findings(triggered_pixel_fixture([(1, 1, 1)] * 5))
    assert 'display/switch_video' not in groups and 'display/trigger_gate' not in groups, items


def test_coincident_switch_frame_may_be_blank_but_later_triggered_frame_must_show():
    groups, items = invariant_findings(triggered_pixel_fixture(
        [(0, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1)]))
    assert not groups, items


def test_mode_change_at_v_marker_does_not_exempt_frame_start_blank():
    pix = triggered_pixel_fixture([(0, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1)])
    pix[0][1] = next(ev[1] for ev in pix if ev[0] == 'V')
    groups, items = invariant_findings(pix)
    assert 'display/trigger_missing' in groups, items


def test_distant_first_eligible_blank_after_switch_is_not_exempt():
    pix = triggered_pixel_fixture([(0, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1), (1, 1, 1)])
    first_v = next(ev for ev in pix if ev[0] == 'V')
    pix[0][1] = str(int(first_v[1]) - 2 * H_TOTAL)
    groups, items = invariant_findings(pix)
    assert 'display/trigger_missing' in groups, items


def test_all_black_eligible_low_frames_are_not_coverage():
    groups, items = invariant_findings(triggered_pixel_fixture([(0, 1, 1)] * 5))
    assert 'display/trigger_missing' in groups, items


def test_mode_switch_marker_requires_post_clear_blank_sample():
    pix = triggered_pixel_fixture([(1, 1, 1)] * 5, switch_video=1)
    groups, items = invariant_findings(pix)
    assert 'display/switch_video' in groups, items


@pytest.mark.parametrize('fault', ['missing', 'unknown'])
def test_v_frame_gate_metadata_is_mandatory_and_binary(fault):
    pix = triggered_pixel_fixture([(1, 1, 1)] * 5)
    v = next(ev for ev in pix if ev[0] == 'V')
    if fault == 'missing':
        del v[7:]
    else:
        v[8] = 'x'
    groups, items = invariant_findings(pix)
    assert 'output/trigger_metadata' in groups, items


def test_mode_switch_metadata_is_mandatory():
    pix = triggered_pixel_fixture([(1, 1, 1)] * 5)
    pix[0].pop()
    groups, items = invariant_findings(pix)
    assert 'display/switch_metadata' in groups, items


def test_vsync_count_is_a_finding():
    """A complete frame without a sync pulse is a failure, not a length note."""
    use_geometry('scaled')
    pix = timing_fixture([V_TOTAL] * 5, sync_counts=[1, 1, 0, 1, 1])
    groups, items = invariant_findings(pix)
    assert groups == ['output/vsync_count'], items


def test_cut_and_recovery_are_the_only_short_frame_group():
    """Two adjacent short frames pass as cut plus recovery; a third is a finding."""
    use_geometry('scaled')
    min_recovery_lines = V_ACTIVE + V_FP + V_SYNC + 1
    groups, items = invariant_findings(timing_fixture([V_TOTAL, 10, min_recovery_lines, V_TOTAL]))
    assert not groups, items
    groups, items = invariant_findings(timing_fixture([V_TOTAL, 10, min_recovery_lines - 1, V_TOTAL]))
    assert groups == ['output/short_frames'], items
    groups, items = invariant_findings(timing_fixture([V_TOTAL, 10, min_recovery_lines, 20, V_TOTAL]))
    assert groups == ['output/short_frames'], items


def test_hold_is_counted_between_cut_groups():
    """HOLD separates groups by the starts of their first short frames."""
    use_geometry('scaled')
    recovery = V_ACTIVE + V_FP + V_SYNC + 1
    enough = [V_TOTAL, 10, recovery] + [V_TOTAL] * (HOLD - 2) + [10, recovery, V_TOTAL]
    close = [V_TOTAL, 10, recovery] + [V_TOTAL] * (HOLD - 3) + [10, recovery, V_TOTAL]
    groups, items = invariant_findings(timing_fixture(enough))
    assert not groups, items
    groups, items = invariant_findings(timing_fixture(close))
    assert groups == ['output/short_frames'], items


def test_camera_ahead_does_not_hide_store_age():
    """Deleting camera bytes cannot explain a stale field in the store's own order."""
    sc = type('Scenario', (), {'ll0': 0, 'geometry': 'scaled', 'std': 'ntsc', 'ahead': True})()
    fd = Findings()
    fd.add('age', 'store', 100, 'store field 1 while field 5 is written')
    fd.add('age', 'lost_field', 100, 'camera field 1 while field 5 arrived early')
    sort_known(sc, dict(pix=[]), fd)
    assert fd.groups() == ['age/store'], fd.items
    assert len(fd.notes) == 1 and 'camera field' in fd.notes[0]


@pytest.mark.parametrize('classes', [[], ['mode_switch']])
def test_no_display_coverage_is_a_failure_even_with_switches(tmp_path, monkeypatch, classes):
    """A passing result needs observed display lines; a switch cannot supply coverage."""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, 'run_sim', lambda *a, **kw: {'fixture': True})
    monkeypatch.setattr(module, 'receiver_records', lambda *a: [])
    monkeypatch.setattr(module, 'check_rx', lambda *a: [])
    monkeypatch.setattr(module, 'check_mixer', lambda *a: ([], []))
    monkeypatch.setattr(module, 'word_origins', lambda *a: ([], []))
    monkeypatch.setattr(module, 'check_store', lambda *a: [])
    monkeypatch.setattr(module, 'check_drain', lambda *a: None)
    monkeypatch.setattr(module, 'check_display', lambda *a: 0)
    monkeypatch.setattr(module, 'check_invariants', lambda *a: None)
    monkeypatch.setattr(module, 'sort_known', lambda *a: None)
    result = run_seed(49, classes, force=tuple(classes), work=tmp_path / 'empty', keep=True)
    assert result['checked'] == 0
    assert result['result'] == 'fail' and result['groups'] == ['bench/few_lines'], result


def ring_display_fixture(*, complete=True, fault=None, geometry='scaled', start=500000, alt=0,
                         switch_delta=None, cut=False):
    """One LOW frame with a known accepted write history, independent of DUT state."""
    use_geometry(geometry)
    line_clocks = H_TOTAL_ALT if alt == 1 else H_TOTAL
    word = 0x66778899
    pix = [video_event(start, 1, 1, 1, alt, V_TOTAL, 1, 1), ['B', '0']]
    for y in range(V_ACTIVE):
        if cut and y == V_ACTIVE - 1:
            continue
        pix.extend((['Y', str(y), '0'],
                    ['X', str(y), f'{word if complete else BLACK:08x}',
                     str((start + y * line_clocks + 302) * T_P)]))
    sd = [['LBTRACE', '1'], ['LW', '0' if complete else '52', '359', '1', '360', '100.0', '200.0'],
          ['L52', '52', f'{word:08x}', '52', '1', 'x', 'x', 'x', '150.0'],
          ['LBEND', '360' if complete else '308', '1']]
    if switch_delta is not None:
        switch_pc = start + switch_delta
        pix.append(['M', str(switch_pc), '1', '0'])
        # Two later V records define the original post-switch end boundary.
        pix.extend(video_event(switch_pc + offset * H_TOTAL, 1, 0, 0, alt, V_TOTAL)
                   for offset in (1, 2))
    if fault in ('missing_header', 'missing_run', 'missing_sample'):
        marker = dict(missing_header='LBTRACE', missing_run='LW', missing_sample='L52')[fault]
        sd = [event for event in sd if event[0] != marker]
    elif fault == 'all_black':
        for event in pix:
            if event[0] == 'X':
                event[2] = f'{BLACK:08x}'
    return dict(pix=pix, sd=sd)


def ring_fixture_words():
    """Independent mixer line; its word-52 value matches the positive fixture."""
    return [(0, 0, idx, 0x66778899, idx, idx) for idx in range(360)]


@pytest.mark.parametrize('complete', [False, True])
def test_low_display_checks_virgin_black_and_initialized_words(complete):
    logs = ring_display_fixture(complete=complete)
    fd = Findings()
    sc = type('Scenario', (), {'end_ns': 1e12})()
    checked = check_display(sc, logs, StoreFrames(), ring_fixture_words(), [0] * 360, [(0, 0)], fd)
    assert not fd.items, fd.items
    assert checked == V_ACTIVE


@pytest.mark.parametrize('fault', ['missing_header', 'missing_run', 'missing_sample', 'all_black'])
def test_low_display_rejects_missing_write_trace_or_all_black(fault):
    logs = ring_display_fixture(fault=fault)
    fd = Findings()
    sc = type('Scenario', (), {'end_ns': 1e12})()
    check_display(sc, logs, StoreFrames(), ring_fixture_words(), [0] * 360, [(0, 0)], fd)
    expected = 'display/ll_word' if fault == 'all_black' else 'display/ring_trace'
    assert expected in fd.groups(), fd.items


@pytest.mark.parametrize('fault', ['wrong_slot', 'wrong_payload', 'wrong_index', 'missing_word'])
def test_low_write_binding_is_checked_even_when_display_is_virgin_black(fault):
    logs = ring_display_fixture()
    words = ring_fixture_words()
    sample = next(ev for ev in logs['sd'] if ev[0] == 'L52')
    if fault == 'wrong_slot':
        run = next(ev for ev in logs['sd'] if ev[0] == 'LW')
        run[1:3] = ['512', '871']
        sample[1] = '564'
        for ev in logs['pix']:
            if ev[0] == 'X':
                ev[2] = f'{BLACK:08x}'
    elif fault == 'wrong_payload':
        sample[2] = f'{int(sample[2], 16) ^ 1:08x}'
    elif fault == 'wrong_index':
        sample[3] = '51'
    else:
        sample[3] = str(len(words))
    fd = Findings()
    sc = type('Scenario', (), {'end_ns': 1e12})()
    check_display(sc, logs, StoreFrames(), words, [0] * 360, [(0, 0)], fd)
    expected = 'display/ll_origin' if fault == 'missing_word' else 'display/ll_word'
    assert expected in fd.groups(), fd.items


def _check_ring_display(logs):
    fd = Findings()
    sc = type('Scenario', (), {'end_ns': 1e12})()
    checked = check_display(sc, logs, StoreFrames(), ring_fixture_words(), [0] * 360,
                            [(0, 0)], fd)
    return checked, fd


@pytest.mark.parametrize('geometry', ['scaled', 'full'])
def test_display_active_window_admits_complete_area_before_switch(geometry):
    try:
        use_geometry(geometry)
        active_span = V_ACTIVE * H_TOTAL
        frame_span = V_TOTAL * H_TOTAL
        delta = active_span + (frame_span - active_span) // 2
        logs = ring_display_fixture(geometry=geometry, switch_delta=delta)
        starts = frame_starts(logs['pix'])
        old_window = switch_windows(logs['pix'], starts)[0]
        assert old_window[0] <= 500000 < old_window[1]  # the old full-frame rule excludes it
        display_window = display_switch_windows(logs['pix'], starts, 0)[0]
        assert display_window == (500000 + delta - active_span, old_window[1])
        checked, fd = _check_ring_display(logs)
        assert checked == V_ACTIVE and not fd.items, (checked, fd.items)
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('geometry', ['scaled', 'full'])
@pytest.mark.parametrize('delta_kind', ['inside_last_active_line', 'exact_active_span'])
def test_display_active_window_still_excludes_switch_in_active_area(geometry, delta_kind):
    try:
        use_geometry(geometry)
        active_span = V_ACTIVE * H_TOTAL
        # Probe x=400 on the final active line, not its horizontal blank tail.
        delta = ((V_ACTIVE - 1) * H_TOTAL + 400
                 if delta_kind == 'inside_last_active_line' else active_span)
        logs = ring_display_fixture(geometry=geometry, switch_delta=delta)
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and not fd.items, (checked, fd.items)
        starts = frame_starts(logs['pix'])
        lo, hi = display_switch_windows(logs['pix'], starts, 0)[0]
        assert lo <= 500000 < hi
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('geometry', ['scaled', 'full'])
def test_pal_display_window_uses_1980_clocks_per_active_line(geometry):
    try:
        use_geometry(geometry)
        short_span = V_ACTIVE * H_TOTAL
        pal_span = V_ACTIVE * H_TOTAL_ALT
        # This switch is after an NTSC-width active area but before PAL's wider one.
        logs = ring_display_fixture(geometry=geometry, alt=1, switch_delta=short_span + 1)
        starts = frame_starts(logs['pix'])
        pal_window = display_switch_windows(logs['pix'], starts, 1)[0]
        old_window = switch_windows(logs['pix'], starts)[0]
        assert pal_window[0] == 500000 + short_span + 1 - pal_span
        assert old_window[1] == pal_window[1]
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and not fd.items, (checked, fd.items)

        # One clock beyond PAL's conservative active span is eligible; the shortened
        # NTSC line length must not be used to calculate this boundary.
        logs = ring_display_fixture(geometry=geometry, alt=1, switch_delta=pal_span + 1)
        checked, fd = _check_ring_display(logs)
        assert checked == V_ACTIVE and not fd.items, (checked, fd.items)
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('alt', ['x', None, 2])
def test_unknown_alt_video_frame_is_rejected_outside_switch_windows(alt):
    try:
        use_geometry('scaled')
        logs = ring_display_fixture(alt=alt)
        frame = pix_frames(logs['pix'])[0]
        assert frame['alt'] == (2 if alt == 2 else None)
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and 'display/alt_metadata' in fd.groups(), fd.items
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('alt', [0, 1])
def test_valid_alt_video_frame_without_switch_counts(alt):
    try:
        use_geometry('scaled')
        logs = ring_display_fixture(alt=alt)
        checked, fd = _check_ring_display(logs)
        assert checked == V_ACTIVE and not fd.items, (checked, fd.items)
    finally:
        use_geometry('scaled')


def test_zero_video_with_unknown_alt_keeps_existing_blank_frame_handling():
    try:
        use_geometry('scaled')
        logs = ring_display_fixture(alt='x')
        next(ev for ev in logs['pix'] if ev[0] == 'V')[3] = '0'
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and not fd.items, (checked, fd.items)
    finally:
        use_geometry('scaled')


def test_cut_frame_is_not_display_coverage_even_with_a_switch():
    try:
        use_geometry('scaled')
        logs = ring_display_fixture(switch_delta=V_ACTIVE * H_TOTAL + 1, cut=True)
        assert pix_frames(logs['pix']) == []
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and not fd.items, (checked, fd.items)
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('fault, expected', [('xword', 'display/ll_word'), ('ymap', 'display/map')])
def test_newly_eligible_active_frame_keeps_independent_ring_and_source_checks(fault, expected):
    try:
        use_geometry('scaled')
        logs = ring_display_fixture(switch_delta=V_ACTIVE * H_TOTAL + 1)
        if fault == 'xword':
            sample = next(ev for ev in logs['pix'] if ev[0] == 'X')
            sample[2] = f'{int(sample[2], 16) ^ 1:08x}'
        else:
            sample = next(ev for ev in logs['pix'] if ev[0] == 'Y')
            sample[2] = '1'
        checked, fd = _check_ring_display(logs)
        assert checked == 0 and expected in fd.groups(), (checked, fd.items)
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('alt, geometry', [(0, 'scaled'), (1, 'scaled'), (0, 'full'), (1, 'full')])
def test_display_window_preserves_post_switch_end_bound(alt, geometry):
    try:
        use_geometry(geometry)
        logs = ring_display_fixture(geometry=geometry, alt=alt,
                                    switch_delta=V_ACTIVE * (H_TOTAL_ALT if alt else H_TOTAL) + 1)
        starts = frame_starts(logs['pix'])
        legacy = switch_windows(logs['pix'], starts)
        corrected = display_switch_windows(logs['pix'], starts, alt)
        assert len(corrected) == len(legacy) == 1
        assert corrected[0][1] == legacy[0][1]
    finally:
        use_geometry('scaled')


@pytest.mark.parametrize('sample_pc, expected_xz', [(7999, True), (8001, False)])
def test_xz_invariant_keeps_original_mode_switch_window(sample_pc, expected_xz):
    use_geometry('scaled')
    pix = [video_event(pc, 1, 0, 0, 0, V_TOTAL) for pc in (100, 2000, 4000, 6000)]
    pix.extend((['M', '8000', '1', '0'], ['Z', str(sample_pc)],
                video_event(10000, 1, 0, 0, 0, V_TOTAL),
                video_event(12000, 1, 0, 0, 0, V_TOTAL)))
    fd = Findings()
    check_invariants(None, dict(pix=pix, sd=[['end', '0']], mix=[['end']], stdout=''), fd)
    assert ('output/xz' in fd.groups()) is expected_xz, fd.items
