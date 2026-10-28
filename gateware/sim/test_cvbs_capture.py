"""rtl/cvbs_capture.v against model/cvbs_capture_ref.py: the same 6-bit composite samples at 40 MS/s
must give the same mixer entries, bit for bit (task 64, hub docs/design/2026-10-24/DIGITAL_INGANG.md).

Run:  .venv/bin/python -m pytest -q gateware/sim/test_cvbs_capture.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import cvbs_capture_ref as m  # noqa: E402


def run(samples, comb=True, tag='run', want_lock=False, avg=m.AVG, white_x8=m.WHITE_X8_STD):
    """Entries the RTL emits for the samples, decoded like the model's tuples; with want_lock also
    the (sample index, locked) list of every change of the flywheel lock. avg: the slicer's window;
    white_x8: the gain table (20 standard, 31 C5VRX)."""
    work = HERE / 'build' / 'cvbs_capture' / tag
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    hexfile = work / 'samples.hex'
    outfile = work / 'entries.txt'
    lockfile = work / 'lock.txt'
    m.write_hex(hexfile, samples)
    defines = (([] if comb else ['-DCVBS_COMB=0']) + ([] if avg == m.AVG else [f'-DCVBS_AVG={avg}'])
               + ([] if white_x8 == m.WHITE_X8_STD else [f'-DCVBS_WHITE_X8={white_x8}']))
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), *defines, '-o', 'sim.vvp', '-s', 'tb_cvbs_capture',
                    str(HERE / 'tb_cvbs_capture.v'), str(GW / 'rtl' / 'cvbs_capture.v')],
                   cwd=work, env=env, check=True)
    res = subprocess.run(['vvp', '-n', 'sim.vvp', f'+hex={hexfile}', f'+out={outfile}', f'+n={len(samples)}',
                          f'+lock={lockfile}'],
                         cwd=work, env=env, check=True, capture_output=True, text=True)
    assert re.search(r'RESULT samples=\d+ entries=\d+', res.stdout), res.stdout[-500:]
    out = []
    for line in outfile.read_text().split():
        v = int(line, 16)
        field = (v >> 51) & 1
        ln = (v >> 41) & 0x3FF
        if (v >> 52) & 1:
            out.append(('marker', field, ln, (v >> 21) & 0xFFFFF, (v >> 17) & 0xF, (v >> 1) & 0xFFF))
        else:
            out.append(('word', field, ln, (v >> 32) & 0x1FF, v & 0xFFFFFFFF))
    if want_lock:
        trace = [(int(a), bool(int(b))) for a, b in
                 (ln.split() for ln in lockfile.read_text().split('\n') if ln.strip())]
        return out, trace
    return out


def first_difference(got, exp):
    for i, (g, e) in enumerate(zip(got, exp)):
        if g != e:
            return f'entry {i}: rtl {g}, model {e}'
    if len(got) != len(exp):
        return f'{len(got)} entries from the rtl, {len(exp)} from the model'
    return None


def test_gain_table_matches_model():
    """rtl/cvbs_gain.vh and rtl/cvbs_gain_c5.vh are the model's tables (regenerate with
    cvbs_capture_ref.write_gain_vh)."""
    assert (GW / 'rtl' / 'cvbs_gain.vh').read_text().endswith(m.gain_vh(m.WHITE_X8_STD))
    assert (GW / 'rtl' / 'cvbs_gain_c5.vh').read_text().endswith(m.gain_vh(m.WHITE_X8_C5VRX))
    assert m.gain_table(20)[16] == 1402 and m.gain_table(31)[16] == 904     # 219*256/(2.5*16), /(3.875*16)


def test_c5vrx_gain_keeps_white_below_the_clamp():
    """The C5VRX levels (white 62, blanking 31, sync 23) through the C5VRX gain table: the brightest grey bar
    (luma 233) comes out at 233 and black at 16, RTL as model; through the standard table (the negative
    control) the same stream clips every bar above code 51 to 254, RTL as model too."""
    s = m.synth(m.bars, frames=1, levels=(23, 31, 62))
    for white_x8, top in ((m.WHITE_X8_C5VRX, 233), (m.WHITE_X8_STD, 254)):
        exp = m.expected_entries(s, white_x8=white_x8)
        got = run(s, tag=f'gain{white_x8}', white_x8=white_x8)
        diff = first_difference(got, exp)
        assert diff is None, diff
        ys = [((e[4] >> 24) & 0xFF, (e[4] >> 8) & 0xFF) for e in got if e[0] == 'word']
        flat = [y for pair in ys for y in pair]
        assert abs(max(flat) - top) <= 2, (white_x8, max(flat))        # 233 maps to 234 with this table's rounding
        assert min(flat) == 16, (white_x8, min(flat))
    clipped = sum(1 for e in m.expected_entries(s, white_x8=m.WHITE_X8_STD) if e[0] == 'word'
                  and ((e[4] >> 24) & 0xFF) == 254)
    assert clipped > 30000, clipped                     # three of the eight bars sit above code 51 (one luma byte counted)


def test_clean_frame_matches_model():
    """One clean NTSC frame of grey bars: every word and marker as the model, both fields numbered
    from 0 after their vertical blanking, 360 words per line, lengths within the mixer's tolerance."""
    s = m.synth(m.bars, frames=1)
    exp = m.expected_entries(s)
    got = run(s, tag='clean')
    assert first_difference(got, exp) is None, first_difference(got, exp)
    markers = [e for e in got if e[0] == 'marker']
    assert len(markers) == 486                                   # 244 + 242 (the last line's marker needs the next start)
    assert all(abs(e[5] - 1716) <= 2 for e in markers)
    assert not any(e[4] for e in markers)
    fields = [e[1] for e in markers]
    assert fields[:244] == [fields[0]] * 244 and fields[244] != fields[0]
    assert [e[2] for e in markers[:244]] == list(range(244))


def test_noise_and_faults_match_model():
    """Noise of one code and two faults (a missing line sync, a short line): the same entries as
    the model; the missing sync is one flywheel line flagged bad, the phase jump re-locks within
    MISS_MAX + 2 lines, both numberings go on."""
    s = m.synth(m.bars, frames=1, noise=1.0, seed=3, faults={100: 'nosync', 300: 'short'})
    exp = m.expected_entries(s)
    got = run(s, tag='faults')
    assert first_difference(got, exp) is None, first_difference(got, exp)
    markers = [e for e in got if e[0] == 'marker']
    bad = [(e[1], e[2]) for e in markers if e[4]]
    assert (markers[0][1], 80) in bad                            # line 100 = active line 80 of the first field
    assert len(bad) <= 1 + m.MISS_MAX + 2
    assert len(markers) == 486


def test_negative_control_comb_off():
    """The RTL without the comb differs from the model with it on a two-line stream whose lines
    differ (the comparison bites), and equals the model without the comb."""
    def alt(ln, x):
        return 16 + (x * 219 // 720 if ln % 2 else 235 - x * 219 // 720)
    s = m.synth(alt, frames=1)
    got = run(s, comb=False, tag='nocomb')
    assert first_difference(got, m.expected_entries(s, comb=True)) is not None
    diff = first_difference(got, m.expected_entries(s, comb=False))
    assert diff is None, diff


def lock_offsets(got, exp):
    """The RTL's lock changes paired with the model's: the same values in the same order, and
    the RTL's sample index minus the model's (its registers decide a few clocks later)."""
    assert [v for _, v in got] == [v for _, v in exp], (got, exp)
    return [g - e for (g, _), (e, _) in zip(got, exp)]


def test_lock_trace_matches_model():
    """The flywheel lock, like the entries (task 69): locks on the first full line period, stays
    locked over one missing sync (one flywheel line, below MISS_MAX), drops after the short line's
    phase jump and locks again; every change at the model's sample plus one constant delay."""
    s = m.synth(m.bars, frames=1, noise=1.0, seed=3, faults={100: 'nosync', 300: 'short'})
    exp = m.expected_lock_trace(s)
    assert [v for _, v in exp] == [True, False, True], exp
    _, got = run(s, tag='lock_faults', want_lock=True)
    offs = lock_offsets(got, exp)
    assert all(0 <= o <= 8 for o in offs) and max(offs) - min(offs) <= 1, offs


def test_lock_negative_controls():
    """Blank level with noise never locks, RTL and model alike; a picture whose sync disappears
    after 40 lines unlocks within MISS_MAX + 2 line periods of the cut, in both."""
    import random
    r = random.Random(5)
    flat = [22 + r.choice((-1, 0, 1)) for _ in range(20 * m.H_NOM)]
    assert m.expected_lock_trace(flat) == []
    _, got = run(flat, tag='lock_flat', want_lock=True)
    assert got == [], got
    base = m.synth(m.bars, frames=1)
    cut = 40 * m.H_NOM
    s = list(base[:cut]) + [22] * (12 * m.H_NOM)
    exp = m.expected_lock_trace(s)
    assert [v for _, v in exp] == [True, False], exp
    assert cut < exp[1][0] <= cut + (m.MISS_MAX + 2) * m.H_NOM, (cut, exp)
    _, got = run(s, tag='lock_cut', want_lock=True)
    offs = lock_offsets(got, exp)
    assert all(0 <= o <= 8 for o in offs) and max(offs) - min(offs) <= 1, offs


def test_c5vrx_levels_lock_by_sweep():
    """The levels the M7 probe measured on the C5VRX bus (bench 2026-10-27: sync 23, blanking 31, white 62):
    the slicer of 12 sees no pulse, the sweep reaches one, the lock comes after at least ten sweep steps and
    the picture then comes out like a standard one (the lock lands in the first field, after its vertical
    sync: the three fields after it are numbered, 728 markers of two frames, lengths in tolerance), RTL as
    model."""
    s = m.synth(m.bars, frames=2, levels=(23, 31, 62))
    exp = m.expected_lock_trace(s)
    assert [v for _, v in exp] == [True], exp
    assert 10 * m.BOOT_STEP <= exp[0][0] < 30 * m.H_NOM, exp
    entries, got = run(s, tag='c5vrx_levels', want_lock=True)
    offs = lock_offsets(got, exp)
    assert all(0 <= o <= 8 for o in offs), offs
    diff = first_difference(entries, m.expected_entries(s))
    assert diff is None, diff
    markers = [e for e in entries if e[0] == 'marker']
    assert len(markers) == 729, len(markers)         # 243 + 244 + 242: the last marker needs the next start
    assert all(abs(e[5] - 1716) <= 2 for e in markers)
    assert not any(e[4] for e in markers)
    cap = m.Capture()
    cap.run(s)
    assert (cap.sync, cap.blank) == (23, 31)


def test_sweep_negative_controls():
    """Edges a line apart are not enough: a black picture at the C5VRX levels with every sync cut to 100
    samples (below T_EQ, equalizing width) never locks, RTL and model, although the swept slicer sees the
    pulses between 24 and 31 (above 31 everything is low: no edges); and the standard levels still lock on
    the second sync, before the sweep has moved."""
    s = list(m.synth(lambda ln, x: 16, frames=1, levels=(23, 31, 62)))
    i, cut = 0, 0
    while i < len(s):
        if s[i] == 23:
            j = i
            while j < len(s) and s[j] == 23:
                j += 1
            if j - i > 150:
                s[i + 100:j] = [31] * (j - i - 100)
                cut += 1
            i = j
        else:
            i += 1
    assert cut > 400, cut
    assert m.expected_lock_trace(s) == []
    _, got = run(s, tag='sweep_narrow', want_lock=True)
    assert got == [], got
    std = m.synth(m.bars, frames=1)
    exp = m.expected_lock_trace(std)
    assert [v for _, v in exp] == [True] and exp[0][0] < 3 * m.BOOT_STEP, exp     # the slicer still 12 to 14


def test_noisy_sync_edges_hold_the_line_length():
    """The C5VRX-level stream with three codes of noise (the bench's sync tip wobbles +-8): with the 8-sample
    slicer window and the line start at the prediction, no line leaves the mixer's length tolerance (the 8-sample
    window alone left 3.4 % outside), none is flagged bad and no lock is lost, RTL as model;
    the negative control is the same stream through the bare-sample slicer (AVG = 1, the old edge), which does
    not even find the vertical sync in this noise and numbers no line, RTL as model too."""
    s = m.synth(m.bars, frames=2, levels=(23, 31, 62), noise=3.0, seed=7)
    exp = m.expected_entries(s)
    entries, got = run(s, tag='noisy_avg8', want_lock=True)
    diff = first_difference(entries, exp)
    assert diff is None, diff
    assert [v for _, v in got] == [True], got
    markers = [e for e in entries if e[0] == 'marker']
    assert len(markers) >= 700, len(markers)
    off8 = sum(1 for e in markers if abs(e[5] - 1716) > 2)
    assert off8 == 0, (off8, len(markers))
    assert not any(e[4] for e in markers)
    exp1 = m.expected_entries(s, avg=1)
    entries1 = run(s, tag='noisy_avg1', avg=1)
    diff = first_difference(entries1, exp1)
    assert diff is None, diff
    markers1 = [e for e in entries1 if e[0] == 'marker']
    assert len(markers1) < len(markers) // 2, (len(markers1), len(markers))


def displace_syncs(s, offsets):
    """Move the start of every sync pulse (a run of the sync code at least 150 samples long) by the next offset
    in the cycle: later by cutting the pulse's first samples, earlier by extending it into the front porch."""
    s = list(s)
    sync, blank = s[0] if s[0] < 31 else 23, 31
    out, i, k = s[:], 0, 0
    while i < len(s):
        if s[i] == sync:
            j = i
            while j < len(s) and s[j] == sync:
                j += 1
            if j - i >= 150:
                o = offsets[k % len(offsets)]
                k += 1
                if o > 0:
                    out[i:i + o] = [blank] * o
                elif o < 0:
                    out[i + o:i] = [sync] * (-o)
            i = j
        else:
            i += 1
    return out, k


def test_jittered_edges_keep_the_prediction():
    """Every sync edge displaced by a pseudo-random -8..8 samples at the C5VRX levels (twice the bench's wobble
    after the 8-sample window): the lines start at the prediction, so every length stays within the tolerance,
    nothing is flagged bad and the lock holds, RTL as model. The negative control displaces the edges by
    +-(WIN + 8): they fall outside the window, the lines are flywheel lines flagged bad and the lock drops,
    RTL as model."""
    import random
    r = random.Random(11)
    base = m.synth(m.bars, frames=2, levels=(23, 31, 62))
    s, k = displace_syncs(base, [r.randint(-8, 8) for _ in range(97)])
    assert k > 1000, k
    exp = m.expected_entries(s)
    entries, got = run(s, tag='jitter20', want_lock=True)
    diff = first_difference(entries, exp)
    assert diff is None, diff
    assert [v for _, v in got] == [True], got
    markers = [e for e in entries if e[0] == 'marker']
    assert len(markers) >= 700, len(markers)
    assert all(abs(e[5] - 1716) <= 2 for e in markers)
    assert not any(e[4] for e in markers)
    s2, _ = displace_syncs(base, [m.WIN + 8, -(m.WIN + 8)])
    exp2 = m.expected_lock_trace(s2)
    assert len(exp2) >= 2 and exp2[1][1] is False, exp2
    entries2, got2 = run(s2, tag='jitter72', want_lock=True)
    diff = first_difference(entries2, m.expected_entries(s2))
    assert diff is None, diff
    offs = lock_offsets(got2, exp2)
    assert all(0 <= o <= 8 for o in offs), offs


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
