"""mixer2 (chan_capture x2 -> FIFOs -> mix_chan x2 -> line_mixer) against the
bit-exact model gateware/model/line_mixer_ref.py.

Two receivers see the same picture with different, per-line random "snow".
Fields have a real vertical blanking interval (VBI lines without any line
record, 1.4 ms) but only LINES active lines, so that a run covers several
fields; one test uses the real 525-line structure. Every decision, the current
channel after it and every output word must match the model. The scenarios
then check on the trace what the mixer is for: a complete picture from the
better receiver, nothing from an unlocked one, no extra field boundaries.

Arrival times: the model gets the time each line record completes in the byte
stream. The RTL sees it a fraction of a microsecond later (FIFO crossing), the
same for both channels, so the scenarios keep arrival differences away from 0
and from the pairing window (checked in `events`). test_pairing_window_edge sits
on the window's edge instead, with the model on the exact clock edge at which
mix_chan takes each line (line_mixer_ref.arrival_cycle).

Run:  .venv/bin/python -m pytest -q gateware/sim/test_mixer.py
"""
import bisect
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402
import line_mixer_ref as ref  # noqa: E402

LINE = 1716                 # bytes per line
VBI, LINES = 22, 24         # blanking lines (no records) and active lines per field
FIELD = (VBI + LINES) * LINE
T_A, T_B, T_S = 37.0, 37.002, 15.4          # two decoders locked to one camera do not drift apart
START_A, START_B = 2000.0, 5300.0
T_PAIR = ref.T_PAIR_CYCLES * T_S
LINE_NS = LINE * T_A
RST_NS = 500.0              # tb_mixer releases reset (and starts counting START_*) at 500 ns
BAD_XY = next(b for b, v in bt656.XY_TABLE.items() if v[3] == 'bad' and b not in (0, 255))


def sample(field, line, x):
    y = 16 + (field * 29 + line * 13 + x) % 220
    cb = 64 + (line * 7 + x // 2 + field * 40) % 128
    cr = 64 + (line * 11 + (x // 2) * 3 + field * 20) % 128
    return cb, y, cr


def active_bytes(field, line, amp, rng):
    def n(v):
        return max(1, min(254, v + (rng.randint(-amp, amp) if amp else 0)))
    out = bytearray()
    for x in range(0, 720, 2):
        cb, y0, cr = sample(field, line, x)
        _, y1, _ = sample(field, line, x + 1)
        out += bytes([n(cb), n(y0), n(cr), n(y1)])
    return bytes(out)


class Stream:
    """BT.656 bytes of one receiver, built line by line."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.data = bytearray()

    def line(self, f, v, fld=0, n=0, amp=0, eav=None, sav=None, late=0, extra=0, lose=None):
        """late: SAV comes that many bytes late, EAV on time (the active part is shorter).
        extra: that many more blanking bytes before SAV (the line is too long, its active part whole).
        lose: both timing codes of this line are lost (blanking in their place), and that many more
        blanking bytes: the line before runs on into this one."""
        act = bt656.blanking(1440) if v else active_bytes(fld, n, amp, self.rng)
        if lose is not None:
            self.data += bt656.blanking(4 + LINE - 1440 - 8 + lose + 4) + act
            return
        self.data += bytes([0xFF, 0, 0, bt656.xy(f, v, 1) if eav is None else eav]) + bt656.blanking(LINE - 1440 - 8 + late + extra)
        self.data += bytes([0xFF, 0, 0, bt656.xy(f, v, 0) if sav is None else sav]) + act[:1440 - late]

    def field(self, fld, f=None, amp=None, hooks=None, lines=LINES, vbi=VBI):
        """Field `fld` (picture content; F bit fld & 1 unless given). amp: snow amplitude for all
        lines or {line: amplitude}; other lines get a random one. hooks: {line index in the
        field, blanking lines first: ('eav' | 'sav', byte to send as that timing code) or
        ('late' | 'extra', bytes), see line()}."""
        f = fld & 1 if f is None else f
        for i in range(vbi + lines):
            v = 1 if i < vbi else 0
            a = self.rng.choice((0, 0, 3, 6, 25, 60))
            if isinstance(amp, dict):
                a = amp.get(i - vbi, a)
            elif amp is not None:
                a = amp
            self.line(f, v, fld, i - vbi, 0 if v else a, **dict([(hooks or {})[i]] if i in (hooks or {}) else []))
        return self

    def gap(self, n):
        """n line times without any timing code (a decoder that stopped)."""
        self.data += bt656.blanking(n * LINE)
        return self

    def done(self, f=0):
        """Closing EAV, so that the last line completes."""
        self.data += bytes([0xFF, 0, 0, bt656.xy(f, 1, 1)]) + bt656.blanking(64)
        return bytes(self.data)


def records_with_times(data, t0, period):
    rx, out = bt656.Receiver(), []
    for k, b in enumerate(data):
        before = len(rx.records)
        rx.push(b)
        if len(rx.records) > before:
            out.append((t0 + k * period, rx.records[-1]))
    return out


def events(a, b, start_a=START_A, start_b=START_B, t_a=T_A, t_b=T_B, t_pair=T_PAIR):
    """Line records of both channels in arrival order: [(t_ns, channel, record)]."""
    ra, rb = records_with_times(a, start_a, t_a), records_with_times(b, start_b, t_b)
    tb = [t for t, _ in rb]
    for t, _ in ra:                                  # the scenario must not sit on a decision boundary
        k = bisect.bisect_left(tb, t)
        for d in [abs(t - x) for x in tb[max(0, k - 1):k + 1]]:
            assert d > 300 and abs(d - t_pair) > 1000, f'arrival difference {d:.0f} ns is too close to a boundary'
    return sorted([(t, 0, r) for t, r in ra] + [(t, 1, r) for t, r in rb], key=lambda e: e[:2])


def model(ev, **kw):
    m = ref.Mixer(**kw)
    for t, ch, r in ev:
        m.push(ch, r, t)
    m.finish()
    return m


def window(ev, on, off=None):
    """ext_bad for the model from a testbench time window; the edges must not be near an arrival."""
    for t, _, _ in ev:
        for edge in (on, off):
            assert edge is None or abs(t + RST_NS - edge) > 5000, 'ext_bad edge too close to a line arrival'
    return lambda t: t + RST_NS >= on and (off is None or t + RST_NS < off)


def run_sim(a, b, work, params=None, alter=None):
    """alter: {rtl file: (text, replacement)} compiles an altered copy (negative controls)."""
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    env = dict(os.environ)
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    bt656.write_hex(work / 'a.hex', a)
    bt656.write_hex(work / 'b.hex', b)
    p = dict(N_A=len(a), N_B=len(b), T_A=T_A, T_B=T_B, START_A=START_A, START_B=START_B)
    p.update(params or {})
    rtl = [GW / 'rtl' / n for n in ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v',
                                    'chan_capture.v', 'mix_chan.v', 'line_mixer.v', 'snow_stats.v', 'noise_stats.v', 'mixer2.v')]
    for name, (old, new) in (alter or {}).items():
        src = (GW / 'rtl' / name).read_text()
        assert src.count(old) == 1, f'{name}: {old!r} not found once'
        (work / name).write_text(src.replace(old, new))
        rtl = [work / name if r.name == name else r for r in rtl]
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_mixer',
                    *[f'-Ptb_mixer.{k}={v}' for k, v in p.items()],
                    *map(str, rtl), str(HERE / 'tb_mixer.v')], cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    dec, curs, end = [], [], None
    for line in (work / 'dec.txt').read_text().split('\n'):
        p = line.split()
        if not p:
            continue
        if p[0] == 'end':
            end = (int(p[1]), int(p[2]))
        else:
            dec.append(tuple(int(x) for x in p[:4]))
            curs.append(int(p[4]))
    out = []
    for line in (work / 'out.txt').read_text().split('\n'):
        p = line.split()
        if p:
            out.append((int(p[0]), int(p[1]), int(p[2]), int(p[3], 16)))
    return dec, curs, out, end


def check(name, a, b, params=None, ev_kw=None, alter=None, **model_kw):
    """Run the RTL and the model on the same streams; they must agree on everything."""
    ev = events(a, b, **(ev_kw or {}))
    ext = model_kw.pop('ext', None)
    if ext:
        model_kw['ext_bad'] = ext(ev)
    m = model(ev, **model_kw)
    dec, curs, out, end = run_sim(a, b, HERE / 'build' / name, params, alter)
    assert end is not None, 'simulation did not finish'
    assert end[0] == 0 and not m.overflow, 'line slots overflowed'
    for i, (g, e) in enumerate(zip(zip(dec, curs), zip(m.trace, m.curs))):
        assert g == e, (f'decision {i}: rtl {g} model {e}\nrtl   {list(zip(dec, curs))[max(0, i - 4):i + 3]}'
                        f'\nmodel {list(zip(m.trace, m.curs))[max(0, i - 4):i + 3]}')
    assert len(dec) == len(m.trace), f'{len(dec)} decisions, model {len(m.trace)}'
    assert len(out) == len(m.out), f'{len(out)} words, model {len(m.out)}'
    for i, (g, e) in enumerate(zip(out, m.out)):
        assert g == e, f'word {i}: rtl {g} model {e}'
    assert end[1] == m.cur
    # Keep the bench's decoded word stream available to tests with downstream-only oracles.
    # `check` has already established word-for-word RTL/model equality above.
    m.rtl_out = out
    return m


def events_exact(a, b, start_a=START_A, start_b=START_B, t_a=T_A, t_b=T_B):
    """Line records in arrival order, timed in mixer clock edges: the edge at which mix_chan takes
    each line's marker in tb_mixer.v (line_mixer_ref.arrival_cycle). Exact, also at the edges."""
    out = []
    for ch, data, t0, per in ((0, a, start_a, t_a), (1, b, start_b, t_b)):
        rx = bt656.Receiver()
        for k, byte in enumerate(data):
            n = len(rx.records)
            rx.push(byte)
            if len(rx.records) > n:
                r = rx.records[-1]
                out.append((ref.arrival_cycle(RST_NS + t0, 2 * round(per / 2, 3), k, r.active_count, T_S), ch, r))
    return sorted(out, key=lambda e: e[:2])


def check_exact(name, a, b, params, ev_kw, t_pair=ref.T_PAIR_CYCLES):
    """As check(), with the model on exact arrival cycles (no distance from the edges needed)."""
    ev = events_exact(a, b, **ev_kw)
    m = model(ev, t_pair=t_pair)
    dec, curs, out, end = run_sim(a, b, HERE / 'build' / name, params)
    assert end is not None and end[0] == 0 and not m.overflow
    for i, (g, e) in enumerate(zip(zip(dec, curs), zip(m.trace, m.curs))):
        assert g == e, f'decision {i}: rtl {g} model {e}'
    assert len(dec) == len(m.trace) and out == m.out and end[1] == m.cur
    return m, ev


@pytest.mark.parametrize('sign', [1, -1])
def test_pairing_window_edge(sign):
    """B's lines arrive 1023.5 mixer clocks after A's (sign 1) or before them (-1): the edge of
    the pairing window. The clock phases make each difference 1023 or 1024 clocks, so some lines
    pair and some do not. On the edge at which mix_chan takes each line (line_mixer_ref.
    arrival_cycle) the model agrees with the RTL on every decision and word. Negative control:
    the model with a window one clock longer or shorter disagrees with the same run."""
    start = START_A + ref.T_PAIR_CYCLES * T_S
    kw = {'START_A': start, 'START_B': start + sign * (ref.T_PAIR_CYCLES - 0.5) * T_S, 'T_B': T_A}
    a = Stream(11).field(0).field(1).done()
    b = Stream(12).field(0).field(1).done()
    ev_kw = {'start_a': start, 'start_b': kw['START_B'], 't_b': T_A}
    m, ev = check_exact(f'tb_mixer_edge{sign:+d}', a, b, kw, ev_kw)
    ta = {(r.field, r.line_in_field): t for t, ch, r in ev if ch == 0}
    d = {abs(t - ta[(r.field, r.line_in_field)]) for t, ch, r in ev if ch == 1 and (r.field, r.line_in_field) in ta}
    assert min(d) < ref.T_PAIR_CYCLES <= max(d), f'the differences do not straddle the edge: {sorted(d)}'
    pairs = sum(1 for _, p, *_ in m.trace if p == 0b11)
    assert 0 < pairs < 2 * LINES, f'{pairs} pairs: all or none of the lines paired'
    for t_pair in (ref.T_PAIR_CYCLES - 1, ref.T_PAIR_CYCLES + 1):
        other = model(ev, t_pair=t_pair)
        assert other.trace != m.trace, f'a window of {t_pair} clocks gives the same decisions'


# ---- what the trace must look like
def out_fields(trace):
    """Shown lines split the way the frame buffer splits them: [(F, [line, ...])]."""
    fields = []
    for use, _, f, line in trace:
        if not use:
            continue
        if not fields or fields[-1][0] != f or line <= fields[-1][1][-1]:
            fields.append((f, []))
        fields[-1][1].append(line)
    return fields


def complete(trace, n_fields, lines=LINES):
    got = out_fields(trace)
    assert len(got) == n_fields, f'{len(got)} output fields, expected {n_fields}: {[(f, len(l)) for f, l in got]}'
    for k, (_, ls) in enumerate(got):
        assert ls == list(range(lines)), f'output field {k}: lines {ls}'


def source_fields(trace):
    """Source field of each decision: line numbers restart in each field."""
    out, fld, prev = [], 0, -1
    for _, _, _, line in trace:
        fld += line < prev
        prev = line
        out.append(fld)
    return out


def cur_changes(m):
    return sum(1 for x, y in zip(m.curs, m.curs[1:]) if x != y)


# ---- scenarios
def test_in_step():
    """Both receivers good. B gets an undecodable timing code in a blanking line, so its
    next line counts as bad; A a broken EAV inside the picture, so one line exists only on B
    and the next one is bad on A. In both places the metric alone would have picked the
    damaged receiver. The picture must still be complete."""
    a = Stream(1).field(0).field(1, amp={0: 60}).field(2, amp={12: 0}, hooks={VBI + 12: ('eav', BAD_XY)}).done()
    b = Stream(2).field(0).field(1, amp={0: 0}, hooks={VBI - 1: ('sav', BAD_XY)}).field(2, amp={12: 60}).done()
    m = check('tb_mixer', a, b)
    kinds = {u for u, *_ in m.trace}
    assert {ref.USE_A, ref.USE_B, ref.USE_BLEND} <= kinds, f'scenario too easy: {kinds}'
    assert m.trace[LINES] == (ref.USE_A, 0b11, 1, 0), "B's bad line loses"
    lone = [i for i, (_, p, *_) in enumerate(m.trace) if p != 0b11]
    assert len(lone) == 1 and m.trace[lone[0]] == (ref.USE_B, 0b10, 0, 11), 'the gap is filled from B'
    assert m.trace[lone[0] + 1] == (ref.USE_B, 0b11, 0, 12), "A's bad line loses"
    complete(m.trace, 3)


def test_random_damage():
    """Undecodable timing codes at random places on both receivers (lines lost on one, on
    both, next to each other, in blanking). What is shown must be in order, and a line is
    missing only if neither receiver had it."""
    rng = random.Random(7)

    def hooks():
        return {rng.randrange(VBI - 2, VBI + LINES): (rng.choice(('eav', 'sav')), BAD_XY) for _ in range(5)}
    ha, hb = [hooks() for _ in range(3)], [hooks() for _ in range(3)]
    ha[2][VBI + 20] = hb[2][VBI + 20] = ('eav', BAD_XY)             # line 19 lost on both
    a, b = Stream(3), Stream(4)
    for fld in range(3):
        a.field(fld, hooks=ha[fld])
        b.field(fld, hooks=hb[fld])
    a, b = a.done(), b.done()
    m = check('tb_mixer_damage', a, b)
    have, left_out = [set(), set(), set()], [set(), set(), set()]
    for data in (a, b):
        fld, prev = 0, -1
        for r in bt656.Receiver().feed(data):
            fld += r.line_in_field <= prev
            prev = r.line_in_field
            have[fld].add(r.line_in_field)
    for (_, _, _, line), fld, o in zip(m.trace, source_fields(m.trace), m.omitted):
        if o:
            left_out[fld].add(line)
    assert 20 in left_out[2], 'line 20 of field 2 is bad on both receivers (their line 19 was lost)'
    got = out_fields(m.trace)
    assert [sorted(ls) for _, ls in got] == [sorted(h - o) for h, o in zip(have, left_out)],         'every line that a receiver had is shown, unless it is left out as bad on both'
    assert all(ls == sorted(ls) for _, ls in got) and 19 not in got[2][1]


LATE = 4                      # SAV 4 bytes late, EAV on time: 1436 active bytes, 359 words
INCOMPLETE_KEEP = 'wire mark = marker && complete && !full && !skipping;'


def incomplete_streams():
    """A: line 5 of field 1 incomplete. Both: line 8 of field 2 incomplete."""
    a = Stream(5).field(0).field(1, hooks={VBI + 5: ('late', LATE)}).field(2, hooks={VBI + 8: ('late', LATE)}).done()
    b = Stream(6).field(0).field(1).field(2, hooks={VBI + 8: ('late', LATE)}).done()
    return a, b


def test_incomplete_line_is_not_stored():
    """A line whose SAV comes late (EAV distance and timing codes intact, 359 words) must not
    be shown: its last ring word would be left from an older line (review 2026-10-06, F1).
    It counts as bad and as not delivered, so B's line with the same number fills the gap;
    where both receivers have it incomplete, the line is missing (the field store covers it)."""
    a, b = incomplete_streams()
    assert sorted({r.active_count for r in bt656.Receiver().feed(a)}) == [1440 - LATE, 1440]
    m = check('tb_mixer_incomplete', a, b)
    assert (ref.USE_B, 0b10, 1, 5) in m.trace, 'the gap is filled from B'
    got = out_fields(m.trace)
    assert [ls for _, ls in got] == [list(range(LINES)), list(range(LINES)), [n for n in range(LINES) if n != 8]]


def test_incomplete_line_check_is_tested():
    """Negative control: mix_chan.v storing the incomplete line again disagrees with the model."""
    a, b = incomplete_streams()
    with pytest.raises(AssertionError, match='decision|word'):
        check('tb_mixer_incomplete_kept', a, b,
              alter={'mix_chan.v': (INCOMPLETE_KEEP, 'wire mark = marker && !full && !skipping;')})


RUN_ON_WRAP = "if (act_count != 11'd2047) act_count <= act_count + 11'd1;"


def run_on_streams():
    """Lines that run on into the next ones (their EAV and SAV lost). A: line 6 of field 1 over one
    line (3156 active bytes), line 4 of field 2 over three (6588). B: line 7 of field 1 over six
    (11736: the bytes after the last multiple of 2048 are 1496, a whole line of words to an index
    that wraps). Each is a complete line, bad by its length; the timing of the rest is kept."""
    lose3 = {VBI + 5 + k: ('lose', 0) for k in range(3)}
    lose6 = {VBI + 8 + k: ('lose', 0) for k in range(6)}
    a = Stream(9).field(0).field(1, hooks={VBI + 7: ('lose', 0)}).field(2, hooks=lose3).done()
    b = Stream(10).field(0).field(1, hooks=lose6).field(2).done()
    return a, b


def test_run_on_line_is_stored_whole():
    """A line that runs on into the next one has its first 360 words in order: it is stored as
    a complete line, bad by its length, and the words are its own (found by
    sim/test_fuzz_chain.py, seed 2: bt656_rx's byte index wrapped at 2048, so the words started
    again at 0 and the line was taken as incomplete, or stored with words from later bytes)."""
    a, b = run_on_streams()
    recs = bt656.Receiver().feed(a) + bt656.Receiver().feed(b)
    assert sorted(r.length for r in recs if r.active_count == bt656.ACTIVE_MAX) == [3432, 6864, 12012]
    m = check('tb_mixer_run_on', a, b)
    for ch, data in ((0, a), (1, b)):
        whole = sum(1 for r in bt656.Receiver().feed(data) if r.active_count >= 1440)
        assert sum(1 for _, p, *_ in m.trace if p >> ch & 1) == whole, 'every whole line is decided, run-on ones too'


def test_run_on_line_check_is_tested():
    """Negative control: a bt656_rx.v whose byte index wraps at 2048 disagrees with the model."""
    a, b = run_on_streams()
    with pytest.raises(AssertionError, match='decision|word'):
        check('tb_mixer_run_on_wrap', a, b,
              alter={'bt656_rx.v': (RUN_ON_WRAP, "act_count <= act_count + 11'd1;")})


LONG = ('extra', 8)           # the line is 8 bytes too long: bad (length), but whole and on time
OMIT = "wire       omit  = show && both_bad && (adm_new || !bad_last);"


def double_bad_streams():
    """Lines bad on both receivers: field 0 line 6 alone, field 1 lines 10 and 11, field 2 its
    first and its last line. Field 3 is clean."""
    hooks = [{VBI + 6: LONG}, {VBI + 10: LONG, VBI + 11: LONG}, {VBI: LONG, VBI + LINES - 1: LONG}, {}]
    a, b = Stream(7), Stream(8)
    for fld, h in enumerate(hooks):
        a.field(fld, hooks=h)
        b.field(fld, hooks=h)
    return a.done(), b.done()


def test_lines_bad_on_both_are_left_out():
    """A line that is bad on both receivers is not written when the line before it in the field
    was good, so the field store replaces it with the line above; of two in a row the second is
    written. Everything else (decisions, current channel) is as without the rule."""
    a, b = double_bad_streams()
    m = check('tb_mixer_double_bad', a, b)
    left = [(fld, line) for (_, _, _, line), fld, o in zip(m.trace, source_fields(m.trace), m.omitted) if o]
    assert left == [(0, 6), (1, 10), (2, 0), (2, LINES - 1)], left
    assert all(p == 0b11 for (_, p, *_), o in zip(m.trace, m.omitted) if o)
    every = list(range(LINES))
    assert out_fields(m.trace) == [(0, [n for n in every if n != 6]), (1, [n for n in every if n != 10]),
                                   (0, every[1:-1]), (1, every)]
    before = model(events(a, b), omit_bad=False)
    assert m.curs == before.curs and [t[1:] for t in m.trace] == [t[1:] for t in before.trace]
    assert all(t == u or o for t, u, o in zip(m.trace, before.trace, m.omitted))


@pytest.mark.parametrize('variant, text', [('written', "wire       omit  = 1'b0;"),
                                           ('every', "wire       omit  = show && both_bad;")])
def test_double_bad_rule_is_checked(variant, text):
    """Negative controls: a line_mixer.v that writes the line anyway, or leaves out every such
    line (also the second of two), disagrees with the model."""
    a, b = double_bad_streams()
    with pytest.raises(AssertionError, match='decision|word'):
        check(f'tb_mixer_double_bad_{variant}', a, b, alter={'line_mixer.v': (OMIT, text)})


def test_line_bad_on_both_at_a_channel_change():
    """A (current) stops after line 9 of field 1. B fills the gap and takes over on its eighth
    lone line, line 17, which is bad (wrong length) while A has none: that line is left out,
    and B takes over on it all the same."""
    a = bytes(Stream(1).field(0, amp=0).field(1, amp=0).data[:FIELD + (VBI + 10) * LINE + 4])
    b = Stream(2).field(0, amp=25).field(1, amp=25, hooks={VBI + 17: LONG}).field(2, amp=25).done()
    m = check('tb_mixer_double_bad_takeover', a, b)
    k = LINES + 10 + 8 - 1
    assert m.curs.index(1) == k and cur_changes(m) == 1, 'B takes over at its 8th lone line'
    assert m.omitted[k] and m.trace[k] == (0, 0b10, 1, 17), m.trace[k]
    assert out_fields(m.trace) == [(0, list(range(LINES))), (1, [n for n in range(LINES) if n != 17]),
                                   (0, list(range(LINES)))]


def test_current_channel_goes_silent():
    """A is the current channel and stops in the middle of a field. B fills in at once
    (the channels were in step) and takes over after N_STEP lines: no line is lost."""
    a = bytes(Stream(1).field(0, amp=0).field(1, amp=0).data[:FIELD + (VBI + 10) * LINE + 4])
    b = Stream(2).field(0, amp=25).field(1, amp=25).field(2, amp=25).done()
    m = check('tb_mixer_silent', a, b)
    pairs = sum(1 for _, p, *_ in m.trace if p == 0b11)
    assert pairs == LINES + 10 and {u for u, *_ in m.trace[:pairs]} == {ref.USE_A}
    assert all(x[:2] == (ref.USE_B, 0b10) for x in m.trace[pairs:]), 'every lone B line is shown'
    assert cur_changes(m) == 1 and m.curs.index(1) == pairs + 8 - 1, 'B takes over at its 8th lone line'
    complete(m.trace, 3)


def test_silence_rule_is_checked():
    """Negative control for the comparison: with N_STEP = 4 in the RTL only, the takeover
    comes earlier than in the model and the traces differ."""
    a = bytes(Stream(1).field(0, amp=0).field(1, amp=0).data[:FIELD + (VBI + 10) * LINE + 4])
    b = Stream(2).field(0, amp=25).field(1, amp=25).done()
    with pytest.raises(AssertionError, match=f'decision {LINES + 10 + 3}'):
        check('tb_mixer_nstep', a, b, {'N_STEP': 4})


def test_channel_returns_with_wrong_line_numbers():
    """A stops for 9 lines in the middle of a field and comes back counting from where it
    stopped, so until the next vertical blanking its numbers lag B's by 8. Its lines arrive
    next to B's but must not be shown: B took over when A went quiet. In the next field the
    channels pair again. The output is read slowly here (every 8th cycle), so the mixer is
    busy most of the time and resolves lone lines late; that must not change anything."""
    s = Stream(1).field(0, amp=0)
    for i in range(VBI + LINES):
        if i == VBI + 6:
            s.data += bytes([0xFF, 0, 0, bt656.xy(1, 0, 1)]) + bt656.blanking(9 * LINE - 4)
        if not VBI + 6 <= i < VBI + 15:
            s.line(1, 1 if i < VBI else 0, 1, i - VBI, 0)
    a = s.field(2, amp=0).done()
    b = Stream(2).field(0, amp=25).field(1, amp=25).field(2, amp=25).done()
    m = check('tb_mixer_return', a, b, {'POP_DIV': 8})
    late = [(u, line) for u, p, _, line in m.trace if p == 0b01]
    assert late == [(0, n) for n in range(7, 16)], "A's shifted lines are dropped"
    assert sum(1 for _, p, *_ in m.trace if p == 0b11) == LINES + 6 + LINES, 'pairs again in field 2'
    assert cur_changes(m) == 2, 'to B when A went quiet, back to the cleaner A in field 2'
    complete(m.trace, 3)


JUDGE = "wire       c_alt   = pair && !(c ? join_b : join_a) && (c ? join_a : join_b);"


def return_streams(returning='a'):
    """A is silent for the whole of field 1 after two blanking lines; B carries field 1 and
    reports no lock from field 2's blanking to field 3's. A is the cleaner receiver."""
    s = Stream(1).field(0, amp=0)
    s.line(1, 1)                                  # two blanking lines close field 0, then nothing
    s.line(1, 1)
    s.gap(VBI - 2 + LINES)
    a = s.field(2, amp=0).field(3, amp=0).done()
    b = Stream(2).field(0, amp=25).field(1, amp=25).field(2, amp=25).field(3, amp=25).done()
    start, period = START_B, T_B
    if returning == 'b':
        a, b = b, a
        start, period = START_A, T_A
    on = RST_NS + start + (2 * (VBI + LINES) + VBI // 2) * LINE * period
    return a, b, on, on + (VBI + LINES) * LINE * period


@pytest.mark.parametrize('returning', ['a', 'b'])
def test_returning_channel_starts_the_next_field(returning):
    """A is silent for field 1 and B carries it; in field 2 A is back in step and B reports no
    lock, so every pair goes to A. A had no line in output field 1, and a pair was judged only on
    the current channel's field counter: A's lines all lay below line 23, the last one sent, and
    no field was shown again for as long as A stayed the cleaner receiver (found by
    sim/test_fuzz_chain.py, round d1, seed 48). Such a pair is now judged on the partner, which
    has moved on to its next field: fields 2 and 3 are shown whole, and the F bit is A's.
    The B variant swaps the receivers and computes the lock window on A's byte clock."""
    a, b, on, off = return_streams(returning)
    other = 'EXTA' if returning == 'b' else 'EXTB'
    ext = lambda ev: (window(ev, on, off), False) if returning == 'b' else (False, window(ev, on, off))
    m = check(f'tb_mixer_return_field_{returning}', a, b, {f'{other}_ON': on, f'{other}_OFF': off}, ext=ext)
    got = out_fields(m.trace)
    assert got == [(0, list(range(LINES))), (1, list(range(LINES))), (0, list(range(LINES))), (1, list(range(LINES)))],         [(f, len(ls)) for f, ls in got]


@pytest.mark.parametrize('returning', ['a', 'b'])
def test_returning_channel_check_is_tested(returning):
    """Negative control: line_mixer.v judging the pair on the current channel only disagrees
    with the model."""
    a, b, on, off = return_streams(returning)
    other = 'EXTA' if returning == 'b' else 'EXTB'
    ext = lambda ev: (window(ev, on, off), False) if returning == 'b' else (False, window(ev, on, off))
    with pytest.raises(AssertionError, match='decision|word'):
        check(f'tb_mixer_return_field_old_{returning}', a, b, {f'{other}_ON': on, f'{other}_OFF': off},
              ext=ext, alter={'line_mixer.v': (JUDGE, "wire       c_alt   = 1'b0;")})


def hidden_field_starts(m):
    """Decisions at which the mixer starts an output field that the word stream does not show:
    the field store sees a new field only when the F bit changes or the line number goes down."""
    out, prev = [], None
    for i, ((use, _, f, line), new) in enumerate(zip(m.trace, m.newfield)):
        if not use:
            continue
        if new and prev is not None and f == prev[0] and line > prev[1]:
            out.append(i)
        prev = (f, line)
    return out


class UnmarkedOutputField(AssertionError):
    """Only the observed #18 boundary defect is an expected failure."""


def test_new_output_field_is_seen_downstream():
    """Adapted from ec06c56: RTL/model agreement must pass before checking #18.
    F is constant at 1; A stops after line 3 and B takes over above that line. The output F
    bit now flips at every output field start, so the store sees the takeover as a new field.
    Was xfail (Core #18) while F was the decoder's: the RTL before 2026-10-08 raises
    UnmarkedOutputField here (negative control, run by hand with o_fbit <= c_f restored)."""
    a = bytes(Stream(1).field(0, f=1).field(1, f=1).data[:FIELD + (VBI + 4) * LINE + 4])
    b = Stream(2).field(0, f=1).field(1, f=1).field(2, f=1).field(3, f=1).done()
    kw = {'START_B': START_A + 5 * LINE_NS + LINE_NS / 3}
    m = check('tb_mixer_hidden_field', a, b, kw, ev_kw={k.lower(): v for k, v in kw.items()})
    assert any(m.newfield[1:]), 'the scenario has no second output field'
    prev = None
    hidden = []
    for (use, _, field, line), new in zip(m.trace, m.newfield):
        if not use:
            continue
        if new and prev is not None and field == prev[0] and line > prev[1]:
            hidden.append((prev, (field, line)))
        prev = field, line
    if hidden:
        assert hidden == [((1, 3), (1, 15))], f'unexpected unmarked field starts: {hidden}'
        raise UnmarkedOutputField(f'F/line before and after field start: {hidden}')


def omitted_intervening_field_streams(paired=True, omitted_fields=1):
    """Real VBI on every field; incomplete early rows still advance input field counters.

    Field 0 shows good lines 0..10. Each intervening field has incomplete lines 0..19 and a sole
    complete bad line 20, which is omitted. The final field has incomplete lines 0..20 before
    good lines 21..30. The actual V=1 interval resets decoded line numbering in each field. No
    internal fc state is fabricated; incomplete line markers establish subsequent source fields.
    """
    a = Stream(31).field(0, amp=0, lines=11)
    for field in range(1, omitted_fields + 1):
        hooks = {VBI + n: ('late', LATE) for n in range(20)}
        hooks[VBI + 20] = LONG
        a.field(field, amp=0, lines=21, hooks=hooks)
    visible_field = omitted_fields + 1
    a.field(visible_field, amp=0, lines=31,
            hooks={VBI + n: ('late', LATE) for n in range(21)})
    a = a.done(f=0)
    if paired:
        b = Stream(32).field(0, amp=0, lines=11)
        for field in range(1, omitted_fields + 1):
            hooks = {VBI + n: ('late', LATE) for n in range(20)}
            hooks[VBI + 20] = LONG
            b.field(field, amp=0, lines=21, hooks=hooks)
        b.field(visible_field, amp=0, lines=31,
                hooks={VBI + n: ('late', LATE) for n in range(21)})
        b = b.done(f=0)
    else:
        # B pairs with the priming field and then goes silent; the affected lines are lone A.
        b = Stream(32).field(0, amp=0, lines=11).done(f=0)
    return a, b


def emitted_boundary_groups(out):
    """Group actual emitted words by their (F, line) tags, then apply fb_sdram's split rule."""
    groups = []
    for f, line, index, _word in out:
        if index == 0:
            groups.append((f, line))
    boundaries = []
    for previous, current in zip(groups, groups[1:]):
        if current[0] != previous[0] or current[1] <= previous[1]:
            boundaries.append((previous, current))
    return groups, boundaries


def assert_omitted_field_boundary(out):
    """The emitted words must restart their field after line 10 despite rising line numbers."""
    groups, boundaries = emitted_boundary_groups(out)
    assert [line for _, line in groups] == list(range(11)) + list(range(21, 31))
    assert len(groups) == 21
    if not any(previous[1] == 10 and current[1] == 21
               for previous, current in boundaries):
        raise UnmarkedOutputField(
            f'no downstream boundary between emitted lines {groups[10]} and {groups[11]}')
    assert boundaries == [(groups[10], groups[11])], boundaries
    return groups, boundaries


def check_omitted_field_boundary_scenario(paired, omitted_fields):
    a, b = omitted_intervening_field_streams(paired, omitted_fields)
    offset = T_PAIR / 2        # half of T_PAIR; paired rows are away from the window edge
    source = {ch: bt656.Receiver().feed(data) for ch, data in ((0, a), (1, b))}
    for ch in (0, 1):
        recs = source[ch]
        if ch == 1 and not paired:
            assert [(r.field, r.line_in_field) for r in recs] == [(0, n) for n in range(11)]
            continue
        assert [(r.field, r.line_in_field) for r in recs[:11]] == [(0, n) for n in range(11)]
        cursor = 11
        for field in range(1, omitted_fields + 1):
            intermediate = recs[cursor:cursor + 21]
            assert [(r.field, r.line_in_field) for r in intermediate] == [
                (field & 1, n) for n in range(21)]
            assert all(r.active_count == 1440 - LATE for r in intermediate[:20]), intermediate[:20]
            assert intermediate[20].active_count == 1440 and intermediate[20].length > LINE
            cursor += 21
        visible_field = omitted_fields + 1
        final = recs[cursor:]
        assert [(r.field, r.line_in_field) for r in final] == [
            (visible_field & 1, n) for n in range(31)]
        assert all(r.active_count == 1440 - LATE for r in final[:21]), final[:21]

    m = check('tb_mixer_omitted_field_boundary', a, b,
              params={'START_B': START_A + offset, 'T_B': T_A},
              ev_kw={'start_a': START_A, 'start_b': START_A + offset,
                     't_a': T_A, 't_b': T_A})
    trace_rows = [(i, row) for i, row in enumerate(m.trace) if row[0]]
    assert [row[3] for _, row in trace_rows] == list(range(11)) + list(range(21, 31))
    omitted_at = list(range(11, 11 + omitted_fields))
    assert [i for i, omitted in enumerate(m.omitted) if omitted] == omitted_at
    for index in omitted_at:
        pop = 0b11 if paired else 0b01
        assert m.trace[index][0:2] == (ref.USE_NONE, pop) and m.trace[index][3] == 20, m.trace[index]
    assert_omitted_field_boundary(m.rtl_out)


@pytest.mark.parametrize('paired', [True, False], ids=['paired', 'lone'])
def test_omitted_complete_field_boundary_is_visible_in_output(paired):
    """An omitted complete line advances two source fields without emitting a word.

    RTL/model agreement is checked first by check(). The oracle then examines the bench-emitted
    words themselves using the downstream F-change/line-restart rule. The third input field
    starts above the last emitted line after two admitted field starts, so the missing boundary
    is independently observable regardless of which output tag the implementation chooses.
    """
    check_omitted_field_boundary_scenario(paired, omitted_fields=1)


def test_consecutive_omitted_fields_coalesce_to_one_visible_boundary():
    check_omitted_field_boundary_scenario(paired=True, omitted_fields=2)


LEGACY_BOUNDARY = (
    """                if (adm_new) begin boundary_pending <= 1'b1; join_a <= 1'b0; join_b <= 1'b0; end
                if (pair || !x) begin join_a <= 1'b1; o_fc_a <= fca; end
                if (pair || x)  begin join_b <= 1'b1; o_fc_b <= fcb; end
                if (use_n != 2'b00) begin o_fbit <= tag_f; boundary_pending <= 1'b0; end""",
    """                if (adm_new) begin o_fbit <= ~o_fbit; join_a <= 1'b0; join_b <= 1'b0; end
                if (pair || !x) begin join_a <= 1'b1; o_fc_a <= fca; end
                if (pair || x)  begin join_b <= 1'b1; o_fc_b <= fcb; end""",
)


def test_omitted_complete_field_old_consumption_mutant_is_caught():
    """The old RTL admission toggle must fail the independent emitted-word boundary oracle."""
    a, b = omitted_intervening_field_streams(paired=True, omitted_fields=1)
    offset = T_PAIR / 2
    _, _, out, end = run_sim(
        a, b, HERE / 'build' / 'tb_mixer_omitted_field_boundary_old',
        {'START_B': START_A + offset, 'T_B': T_A},
        alter={'line_mixer.v': LEGACY_BOUNDARY})
    assert end is not None and end[0] == 0
    with pytest.raises(UnmarkedOutputField, match='no downstream boundary'):
        assert_omitted_field_boundary(out)


def test_unlocked_decoder_in_step_loses():
    """Decoder B reports no lock the whole time (I2C status): every line comes from A."""
    a = Stream(1).field(0).field(1).done()
    b = Stream(2).field(0).field(1).done()
    m = check('tb_mixer_extb', a, b, {'EXTB_ON': 0}, ext=lambda ev: (False, True))
    assert all(u == ref.USE_A and p == 0b11 for u, p, *_ in m.trace), {(u, p) for u, p, *_ in m.trace}
    complete(m.trace, 2)


def test_decoder_loses_lock_and_recovers():
    """Decoder A (current, the cleaner picture) reports no lock from the middle of field 0
    to the middle of field 1. In between nothing comes from A; afterwards A is used again."""
    a = Stream(1).field(0, amp=0).field(1, amp=0).field(2, amp=0).done()
    b = Stream(2).field(0, amp=25).field(1, amp=25).field(2, amp=25).done()
    on = RST_NS + START_A + ((VBI + 12) * LINE + 858) * T_A
    off = on + FIELD * T_A
    m = check('tb_mixer_relock', a, b, {'EXTA_ON': on, 'EXTA_OFF': off}, ext=lambda ev: (window(ev, on, off), False))
    uses = [u for u, *_ in m.trace]
    assert set(uses[:12]) == {ref.USE_A} and set(uses[12:LINES + 12]) == {ref.USE_B}
    assert set(uses[LINES + 12:]) == {ref.USE_A}, 'back to the clean receiver as soon as it is locked'
    complete(m.trace, 3)


@pytest.mark.parametrize('lag_lines, pop_div', [(5, 1), ((VBI + LINES) // 2, 8)])
def test_unlocked_current_channel_out_of_step(lag_lines, pop_div):
    """A is the current channel after reset, reports no lock and runs out of step with B
    (ahead by some lines less a third of a line). B is good. When B has delivered eight good
    lines while A's last eight were bad, B takes over; from then on every B line is shown and
    no A line, also while B is in its blanking interval and only A delivers."""
    a = Stream(1).field(0, amp=60).field(1, amp=60).field(2, amp=60).field(3, amp=60).done()
    a = a[lag_lines * LINE:][:(3 * (VBI + LINES) + 1) * LINE]
    b = Stream(2).field(0, amp=3).field(1, amp=3).field(2, amp=3).done()
    kw = {'START_A': START_A + LINE_NS / 3}
    m = check(f'tb_mixer_exta{lag_lines}', a, b, {'EXTA_ON': 0, 'POP_DIV': pop_div, **kw},
              ev_kw={k.lower(): v for k, v in kw.items()}, ext=lambda ev: (True, False))
    assert all(p != 0b11 for _, p, *_ in m.trace), 'the channels never pair'
    k = m.curs.index(1)
    assert sum(1 for _, p, *_ in m.trace[:k + 1] if p == 0b10) == 8, 'B takes over at its eighth line'
    assert cur_changes(m) == 1
    assert all(u == (ref.USE_B if p == 0b10 else 0) for u, p, *_ in m.trace[k:]), 'only B after the takeover'
    assert [ls for _, ls in out_fields(m.trace[k:])] == [list(range(7, LINES)), list(range(LINES)), list(range(LINES))]


def test_lagging_channel_is_not_shown_until_the_other_is_gone():
    """Both receivers good, but B delivers every line five and a third lines late (two
    decoders that disagree about where the picture is). While A delivers, the output is A's
    lines and nothing else, and the current channel does not change in the blanking intervals.
    Then A stops for good: B takes over after N_DEAD of its lines and starts a field of its own."""
    a = Stream(1).field(0).field(1).done()
    b = Stream(2).field(0).field(1).field(2).field(3).done()
    kw = {'START_B': START_A + 5 * LINE_NS + LINE_NS / 3}
    m = check('tb_mixer_lag', a, b, kw, ev_kw={k.lower(): v for k, v in kw.items()})
    k = m.curs.index(1)
    last_a = max(i for i, (_, p, *_) in enumerate(m.trace) if p == 0b01)
    assert cur_changes(m) == 1 and sum(1 for _, p, *_ in m.trace[last_a:k + 1] if p == 0b10) == 40
    assert all(u == (ref.USE_A if p == 0b01 else 0) for u, p, *_ in m.trace[:k]), 'only A while A delivers'
    assert all(u == ref.USE_B for u, *_ in m.trace[k:])
    # the output F flips per output field (#18): B's field of its own is the third one, F = 0
    assert out_fields(m.trace) == [(0, list(range(LINES))), (1, list(range(LINES))), (0, list(range(9, LINES)))]


def test_blanking_must_not_look_like_silence():
    """Negative control for N_DEAD: two good receivers half a field apart, with N_DEAD = 16
    (shorter than the blanking interval) in both RTL and model. Each channel then takes the
    picture from the other in every blanking interval and the fields are cut up. With the
    real N_DEAD the model leaves the same streams alone."""
    a = Stream(1).field(0).field(1).done()
    b = Stream(2).field(0).field(1).done()
    kw = {'START_B': START_A + (VBI + LINES) // 2 * LINE_NS + LINE_NS / 3}
    ev_kw = {k.lower(): v for k, v in kw.items()}
    m = check('tb_mixer_ndead16', a, b, {'N_DEAD': 16, **kw}, ev_kw=ev_kw, n_dead=16)
    assert cur_changes(m) == 3 and len(out_fields(m.trace)) == 4
    good = model(events(a, b, **ev_kw))
    assert cur_changes(good) == 0
    complete(good.trace, 2)


def test_f_bits_disagree():
    """Decoder B holds F at 1 (as a TVP5150AM1 does when it takes the signal for
    non-interlaced) while A alternates. Lines still pair by number, and the F bit of an
    output field is the one its first line came with: A's in fields 0 and 1, B's in field 2
    where B is the cleaner receiver."""
    a = Stream(1).field(0, amp=0).field(1, amp=0).field(2, amp=60).done()
    b = Stream(2).field(0, f=1, amp=25).field(1, f=1, amp=25).field(2, f=1, amp=25).done()
    m = check('tb_mixer_fbits', a, b)
    assert all(p == 0b11 for _, p, *_ in m.trace)
    assert {u for u, *_ in m.trace[:2 * LINES]} == {ref.USE_A} and {u for u, *_ in m.trace[2 * LINES:]} == {ref.USE_B}
    assert out_fields(m.trace) == [(0, list(range(LINES))), (1, list(range(LINES))), (0, list(range(LINES)))]   # output F flips per field


def test_f_stuck_on_both():
    """Both decoders hold F at 1: fields are told apart by the line number alone."""
    a = Stream(1).field(0, f=1).field(1, f=1).done()
    b = Stream(2).field(0, f=1).field(1, f=1).done()
    m = check('tb_mixer_fstuck', a, b)
    assert all(p == 0b11 for _, p, *_ in m.trace)
    assert [f for f, _ in out_fields(m.trace)] == [0, 1], 'the output F flips per output field, whatever the decoders say'
    complete(m.trace, 2)


def test_full_ntsc_field():
    """Lines 1 to 300 of a real 525-line frame: 19 blanking lines, a field of 244 lines,
    19 blanking lines with the F change inside, and the first 18 lines of the next field."""
    def frame(seed, snow):
        rng, out = random.Random(seed), bytearray()
        for line in range(1, 301):
            f, v = bt656.field_and_vblank('ntsc', line)
            out += bt656.line_bytes('ntsc', line, None if v else active_bytes(f, line, rng.choice(snow), rng))
        return bytes(out) + bytes([0xFF, 0, 0, bt656.xy(1, 0, 1)]) + bt656.blanking(64)
    a, b = frame(1, (0, 3, 6)), frame(2, (0, 3, 25, 60, 60))
    m = check('tb_mixer_ntsc', a, b)
    assert all(p == 0b11 for _, p, *_ in m.trace)
    assert out_fields(m.trace) == [(0, list(range(244))), (1, list(range(18)))]
