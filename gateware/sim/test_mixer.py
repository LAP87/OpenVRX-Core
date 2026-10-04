"""mixer2 (chan_capture x2 -> FIFOs -> mix_chan x2 -> line_mixer) against the
bit-exact model gateware/model/line_mixer_ref.py.

Two receivers see the same picture with different, per-line random "snow".
Channel clocks differ slightly (37.00 / 37.07 ns) and start 3.3 us apart.
Channel B gets an undecodable timing code in a blanking line (its next line
must count as bad), channel A a broken EAV inside the picture (one line lost,
so the channels are briefly out of step). Every decision and every output word
must match the model.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_mixer.py
"""
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402
import line_mixer_ref as ref  # noqa: E402

LINES, VBI, FIELDS = 10, 2, 5
T_A, T_B, START_A, START_B = 37.0, 37.07, 2000.0, 5300.0
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


def stream(ch, seed, amp_override=None):
    """BT.656 bytes for one channel plus the per-line snow amplitudes used."""
    rng = random.Random(seed)
    data = bytearray()
    for fld in range(FIELDS):
        f = fld & 1
        for i in range(VBI + LINES):
            v = 1 if i < VBI else 0
            amp = 0 if v else rng.choice((0, 0, 3, 6, 25, 60))
            if amp_override and not v and fld in amp_override:
                amp = amp_override[fld]
            act = bt656.blanking(1440) if v else active_bytes(fld, i - VBI, amp, rng)
            eav_xy, sav_xy = bt656.xy(f, v, 1), bt656.xy(f, v, 0)
            if ch == 'b' and fld == 2 and i == 1:
                sav_xy = BAD_XY                 # undecodable code in a blanking line
            if ch == 'a' and fld == 3 and i == VBI + 4:
                eav_xy = BAD_XY                 # EAV of this line broken: the line before it is lost
            data += bytes([0xFF, 0, 0, eav_xy]) + bt656.blanking(1716 - 1440 - 8)
            data += bytes([0xFF, 0, 0, sav_xy]) + act
    return bytes(data)


def records_with_times(data, t0, period):
    rx, out = bt656.Receiver(), []
    for k, b in enumerate(data):
        before = len(rx.records)
        rx.push(b)
        if len(rx.records) > before:
            out.append((t0 + k * period, rx.records[-1]))
    return out


def model(a, b, **kw):
    ev = [(t, 0, r) for t, r in records_with_times(a, START_A, T_A)]
    ev += [(t, 1, r) for t, r in records_with_times(b, START_B, T_B)]
    m = ref.Mixer(**kw)
    for _, ch, r in sorted(ev, key=lambda e: e[0]):
        m.push(ch, r)
    return m


def run_sim(a, b, work, params=()):
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    env = dict(os.environ)
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    bt656.write_hex(work / 'a.hex', a)
    bt656.write_hex(work / 'b.hex', b)
    rtl = [GW / 'rtl' / n for n in ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v',
                                    'chan_capture.v', 'mix_chan.v', 'line_mixer.v', 'snow_stats.v', 'mixer2.v')]
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_mixer',
                    f'-Ptb_mixer.N_A={len(a)}', f'-Ptb_mixer.N_B={len(b)}', *params,
                    *map(str, rtl), str(HERE / 'tb_mixer.v')], cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    dec, end = [], None
    for line in (work / 'dec.txt').read_text().split('\n'):
        p = line.split()
        if not p:
            continue
        if p[0] == 'end':
            end = (int(p[1]), int(p[2]))
        else:
            dec.append(tuple(int(x) for x in p[:4]))
    out = []
    for line in (work / 'out.txt').read_text().split('\n'):
        p = line.split()
        if p:
            out.append((int(p[0]), int(p[1]), int(p[2]), int(p[3], 16)))
    return dec, out, end


def test_mixer_against_model():
    a, b = stream('a', 1), stream('b', 2)
    m = model(a, b)
    dec, out, end = run_sim(a, b, HERE / 'build' / 'tb_mixer')
    assert end is not None, 'simulation did not finish'
    assert end[0] == 0 and not m.overflow, 'line slots overflowed'
    kinds = {u for u, *_ in m.trace}
    assert {ref.USE_A, ref.USE_B, ref.USE_BLEND} <= kinds, f'scenario too easy: {kinds}'
    assert any(p != 0b11 for _, p, *_ in m.trace), 'no unpaired line in the scenario'
    for i, (g, e) in enumerate(zip(dec, m.trace)):
        assert g == e, f'decision {i}: rtl {g} model {e}\nrtl {dec[max(0, i - 3):i + 3]}\nmodel {m.trace[max(0, i - 3):i + 3]}'
    assert len(dec) == len(m.trace), f'{len(dec)} decisions, model {len(m.trace)}'
    assert len(out) == len(m.out), f'{len(out)} words, model {len(m.out)}'
    for i, (g, e) in enumerate(zip(out, m.out)):
        assert g == e, f'word {i}: rtl {g} model {e}'


def test_dead_channel_switches():
    """A stops after two fields while it is the current channel: B's lines are
    dropped until A counts as dead (TIMEOUT), then everything comes from B."""
    timeout = 60000                                      # 0.92 ms ~ 14 lines at 15.4 ns
    a_full, b = stream('a', 1, {1: 0}), stream('b', 2, {1: 60})     # A clean, B snowy in field 1
    a = a_full[:2 * (VBI + LINES) * 1716]
    dec, out, end = run_sim(a, b, HERE / 'build' / 'tb_mixer_dead', [f'-Ptb_mixer.TIMEOUT={timeout}'])
    assert end is not None and end[0] == 0
    m = model(a, b)
    n_paired = sum(1 for _, p, *_ in m.trace if p == 0b11)
    # up to the moment A disappears the RTL matches the model
    assert dec[:n_paired] == m.trace[:n_paired]
    rest = dec[n_paired:]
    assert m.cur == 0, 'scenario: A must be the current channel when it disappears'
    assert rest and all(p == 0b10 for _, p, *_ in rest), rest      # only B lines left
    dropped = [r for r in rest if r[0] == 0b00]
    shown = [r for r in rest if r[0] == 0b10]
    line_ns = 1716 * T_B
    assert 1 <= len(dropped) <= timeout * 15.4 / line_ns + 3, f'{len(dropped)} lines dropped'
    assert rest[-len(shown):] == shown, 'B lines must be shown once A is dead'
    assert end[1] == 1, 'current channel should be B'
    assert len(out) == 360 * sum(1 for u, *_ in dec if u), 'words for every shown line'


def test_unlocked_decoder_loses():
    """Decoder B reports no lock (I2C status): every paired line comes from A."""
    a, b = stream('a', 1), stream('b', 2)
    m = model(a, b, ext_bad=(False, True))
    dec, out, end = run_sim(a, b, HERE / 'build' / 'tb_mixer_extb', ['-Ptb_mixer.EXT_B=1'])
    assert dec == m.trace
    assert out == m.out
    paired = [u for u, p, *_ in dec if p == 0b11]
    assert paired and all(u == ref.USE_A for u in paired), set(paired)
