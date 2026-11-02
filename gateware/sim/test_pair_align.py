"""rtl/pair_align.v against model/pair_align_ref.py, and what the stage does for cvbs_capture: the C5VRX bus
sends every sample twice and the bench (2026-10-27/28) saw the first copy miss bit 2's rising edge in 41-66 %
of the edges and carry every isolated code 0. With the settled copy in both positions the capture's entries
are those of a clean stream; the raw stream's are not (the negative control), and the wrong pair phase is
worse than the raw stream (the second negative control, with the phase decision frozen).

Run:  .venv/bin/python -m pytest -q gateware/sim/test_pair_align.py
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
import pair_align_ref as pa  # noqa: E402

sys.path.insert(0, str(HERE))
from test_cvbs_capture import run as run_capture, first_difference  # noqa: E402

LV_C5 = (23, 31, 62)          # C5VRX's sync, blanking and white codes (bench 2026-10-27)
BENCH_1251 = GW / 'vectors' / 'digin_bench_2026-10-28_1251.hex'


def run_rtl(samples, tag, hold_min=pa.HOLD_MIN):
    """(q list, phase list, mism list) from the RTL, one entry per sample."""
    work = HERE / 'build' / 'pair_align' / tag
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    hexfile = work / 'samples.hex'
    outfile = work / 'out.txt'
    pa.write_hex(hexfile, samples)
    defines = [] if hold_min == pa.HOLD_MIN else [f'-DPA_HOLD_MIN={hold_min}']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), *defines, '-o', 'sim.vvp', '-s', 'tb_pair_align',
                    str(HERE / 'tb_pair_align.v'), str(GW / 'rtl' / 'pair_align.v')],
                   cwd=work, env=env, check=True)
    res = subprocess.run(['vvp', '-n', 'sim.vvp', f'+hex={hexfile}', f'+out={outfile}', f'+n={len(samples)}'],
                         cwd=work, env=env, check=True, capture_output=True, text=True)
    assert re.search(rf'RESULT samples={len(samples)} written={len(samples)}', res.stdout), res.stdout[-300:]
    q, ph, mi = [], [], []
    for line in outfile.read_text().split('\n'):
        p = line.split()
        if p:
            q.append(int(p[0], 16)); ph.append(int(p[1])); mi.append(int(p[2], 16))
    return q, ph, mi


def model_run(samples, hold_min=pa.HOLD_MIN):
    """(q list, phase list, mism list) from the model, the phase and mism as the RTL shows them: the values
    after the sample's clock."""
    c = pa.PairAlign(hold_min=hold_min)
    q, ph, mi = [], [], []
    for s in samples:
        q.append(c.step(s)); ph.append(c.phase); mi.append(c.mism)
    return (q, ph, mi), c


def video(lines=60, noise=1.0, seed=3):
    """A noisy C5VRX-level picture at 40 MS/s (the unique samples), `lines` lines long (0 = a whole frame).
    Noise 1 code: with 2 codes the capture model loses lines of a paired stream (the pairs halve the
    independent samples in the slicer's 8-sample mean) and with seeds 3 and 4 a whole field; an open point
    outside this stage, noted in the hub protocol 2026-11-02."""
    s = m.synth(m.bars, frames=1, levels=LV_C5, noise=noise, seed=seed)
    return s[:lines * m.H_NOM] if lines else s


@pytest.mark.parametrize('phase', [1, 0])
def test_rtl_matches_model_on_the_bench_faults(phase):
    """Paired noisy video with the late bit-2 edge in half of its rising edges and a code 0 in 0.5 % of the
    first copies, with the pairs on either parity: the RTL's output, phase and window counts are the model's,
    sample for sample. The model settles on the right phase within the first window and from then on its
    output is the clean paired stream one sample late (every glitch gone)."""
    clean = pa.pair_stream(video(), phase=phase)
    s, late, zeros = pa.glitch(clean, phase=phase, p_late=0.5, p_zero=0.005, seed=7)
    assert late > 1000 and zeros > 100, (late, zeros)
    (mq, mph, mmi), c = model_run(s)
    assert c.phase == phase and all(n <= (1 << pa.WIN_LOG2) for n, _ in c.phase_trace), c.phase_trace
    win = 1 << pa.WIN_LOG2
    assert mq[win + 1:] == clean[win:-1]
    rq, rph, rmi = run_rtl(s, tag=f'faults_ph{phase}')
    assert rq == mq, first_difference(rq, mq)
    assert rph == mph and rmi == mmi
    # the published count is the raw stream's glitches per window: hundreds, and the other parity's count
    # (every change of the picture) is what keeps the phase; after the first window mism counts only glitches
    assert all(50 < v < 1500 for v in mmi[2 * win:]), sorted(set(mmi[2 * win:]))[:5]


def test_aligned_stream_restores_the_clean_entries():
    """A whole frame at the C5VRX levels with the late bit-2 edge in half of its rising edges: cvbs_capture on
    the aligned stream gives exactly the entries of the clean stream one sample late (the pairs on the parity
    the stage assumes after reset, so no window has to pass first), 87 480 words. Negative control: the raw
    glitched stream gives different entries in most words (model: 84 %), because the glitched samples in the
    sync and the porch move the measured levels and with them every luma value, and a missing bit 2 in one
    copy is 4 codes, 14 luma steps through the C5VRX gain table."""
    clean = pa.pair_stream(video(lines=0), phase=0)
    s, late, _ = pa.glitch(clean, phase=0, p_late=0.5, seed=11)
    assert late > 40000, late
    (aligned, _, _), c = model_run(s)
    assert c.phase == 0 and not c.phase_trace, c.phase_trace
    assert aligned == [clean[0]] + clean[:-1]
    want = m.expected_entries(aligned, white_x8=m.WHITE_X8_C5VRX)
    assert sum(1 for e in want if e[0] == 'word') == 87480
    got = run_capture(aligned, tag='aligned', white_x8=m.WHITE_X8_C5VRX)
    assert first_difference(got, want) is None, first_difference(got, want)
    raw = run_capture(s, tag='raw', white_x8=m.WHITE_X8_C5VRX)
    raw_words = [e for e in raw if e[0] == 'word']
    want_words = [e for e in m.expected_entries(clean, white_x8=m.WHITE_X8_C5VRX) if e[0] == 'word']
    differing = sum(1 for a, b in zip(raw_words, want_words) if a[:4] == b[:4] and a[4] != b[4])
    assert differing > 0.5 * len(want_words), (differing, len(want_words), late)


def test_wrong_phase_doubles_the_glitches():
    """Negative control: with the phase decision frozen (HOLD_MIN beyond any window) and the pairs on the
    other parity, the stage holds the glitched first copy over both positions: more samples differ from the
    clean stream than in the raw input. RTL as model."""
    clean = pa.pair_stream(video(lines=20), phase=1)
    s, late, _ = pa.glitch(clean, phase=1, p_late=1.0, seed=5)
    frozen = 4000
    (mq, mph, mmi), c = model_run(s, hold_min=frozen)
    assert c.phase == 0 and not c.phase_trace
    wrong = sum(1 for a, b in zip(mq[1:], clean[:-1]) if a != b)
    assert wrong >= 2 * late - 2, (wrong, late)
    rq, rph, rmi = run_rtl(s, tag='frozen', hold_min=frozen)
    assert rq == mq and rph == mph and rmi == mmi
    # and with the decision on, the same stream flips the phase at the first window end and is clean after it
    (mq2, _, _), c2 = model_run(s)
    assert c2.phase_trace == [(1 << pa.WIN_LOG2, 1)], c2.phase_trace
    assert mq2[(1 << pa.WIN_LOG2) + 1:] == clean[(1 << pa.WIN_LOG2):-1]


def test_flat_and_unpaired_streams_keep_the_phase():
    """A flat level never moves the phase (both counts stay under HOLD_MIN) and reports no mismatches; a stream
    without pairs (every 40 MS/s sample unique, the synthetic composite as such) counts alike on both parities
    and never moves it either. RTL as model on both."""
    flat = [31] * (3 << pa.WIN_LOG2)
    (mq, mph, mmi), c = model_run(flat)
    assert not c.phase_trace and mmi[-1] == 0 and mq[1:] == flat[1:]
    rq, rph, rmi = run_rtl(flat, tag='flat')
    assert rq == mq and rph == mph and rmi == mmi
    unpaired = video(lines=8, noise=0.0)
    (mq, mph, mmi), c = model_run(unpaired)
    assert not c.phase_trace, c.phase_trace
    assert c.c01 + c.c10 > 0
    rq, rph, rmi = run_rtl(unpaired, tag='unpaired')
    assert rq == mq and rph == mph and rmi == mmi


def test_bench_capture_pairs_become_identical():
    """The real capture of 2026-10-28 12:51 (M7 probe, 65 536 samples, the steady picture at the lower code
    scale 13/25/50): 3 557 of its 32 768 pairs differ, all of them bit 2 set only in the second copy, while the
    other parity differs in 18 437. Through the stage the pairs after the first window are identical, the
    phase is the capture's (the second copy on the odd clocks), and the counts published at the window ends
    add up to the raw stream's glitches in those windows. RTL as model."""
    x = [int(v, 16) for v in BENCH_1251.read_text().split()]
    assert len(x) == 65536
    raw_ph0 = pa.mismatching_pairs(x, phase=0)
    raw_ph1 = pa.mismatching_pairs(x, phase=1)
    bus_phase = 0 if raw_ph0 < raw_ph1 else 1
    assert (raw_ph0, raw_ph1) == (18437, 3557), (raw_ph0, raw_ph1)
    first = 1 - bus_phase
    only_bit2 = all((x[k] ^ x[k + 1]) in (0, 4) and (x[k + 1] & 4) >= (x[k] & 4)
                    for k in range(first, len(x) - 1, 2))
    assert only_bit2
    (mq, mph, mmi), c = model_run(x)
    win = 1 << pa.WIN_LOG2
    assert c.phase == bus_phase and all(n <= win for n, _ in c.phase_trace), c.phase_trace
    # the output pairs: identical from the first window on. The output is the input one sample late, so its
    # identical pairs sit on the other grid (the settled copy at the clock it arrived and the clock after)
    assert pa.mismatching_pairs(mq, phase=bus_phase ^ 1, start=win + 1) == 0
    assert pa.mismatching_pairs(mq, phase=bus_phase, start=win + 1) > 10000
    published = sum(v for _, v in c.mism_trace[1:])      # windows 2..15: samples 4 096..61 439 of 65 536
    assert 0.8 * 3557 <= published <= 3557, published
    rq, rph, rmi = run_rtl(x, tag='bench_1251')
    assert rq == mq, first_difference(rq, mq)
    assert rph == mph and rmi == mmi


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
