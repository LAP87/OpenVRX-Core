"""mixer2 with B_DIGITAL (hub plan task 69): channel B's health comes from cvbs_capture's lock, not
from the TVP status input, which does not exist for a sample bus. The negative control is the
BT.656 build of the same mixer, where the status input still rules.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_mixer_digital.py
"""
import os
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

RTL = ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v', 'chan_capture.v', 'cvbs_capture.v',
       'pair_align.v', 'mix_chan.v', 'line_mixer.v', 'snow_stats.v', 'noise_stats.v', 'mixer2.v')


def run(samples, digital, tag):
    """(trace, end): every change of (b_lock, mix_chan B's synchronised ext_bad) with its time in
    ns, and the pair at the end of the run."""
    work = HERE / 'build' / 'mixer_digital' / tag
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    m.write_hex(work / 'b.hex', samples)
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_mixer_digital',
                    f'-Ptb_mixer_digital.N_B={len(samples)}', f'-Ptb_mixer_digital.B_DIGITAL={int(digital)}',
                    *[str(GW / 'rtl' / n) for n in RTL], str(HERE / 'tb_mixer_digital.v')],
                   cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    trace, end = [], None
    for line in (work / 'trace.txt').read_text().split('\n'):
        p = line.split()
        if not p:
            continue
        if p[0] == 'end':
            end = (int(p[1]), int(p[2]))
        else:
            trace.append((int(p[0]), int(p[1]), int(p[2])))
    return trace, end


@pytest.fixture(scope='module')
def picture():
    """40 lines of clean composite as the bus sends them, every sample twice (pair_align_ref.pair_stream), with
    the bench's late bit-2 edge in half of the first copies: the flywheel locks a few lines in."""
    paired = pa.pair_stream(m.synth(m.bars, frames=1)[:40 * m.H_NOM])
    return pa.glitch(paired, p_late=0.5)[0]


def test_digital_b_health_is_the_capture_lock(picture):
    """ext_bad_b held high (no TVP B answers): before the capture locks, mix_chan B's ext_bad is
    high; once it locks, ext_bad goes low within two system clocks and stays low. B's lines then
    count as good (mix_chan.v bad_in) instead of losing every pair against A."""
    trace, end = run(picture, digital=True, tag='digital')
    assert end == (1, 0), (trace, end)
    locks = [t for t, lock, bad in trace if lock == 1]
    assert locks, trace
    t_lock = locks[0]
    assert all(bad == 1 for t, lock, bad in trace if t < t_lock), trace
    clear = [t for t, lock, bad in trace if bad == 0]
    assert clear and t_lock <= clear[0] <= t_lock + 2 * 15.4 + 1.0, (t_lock, trace)


def test_negative_control_bt656_build_keeps_the_status_input(picture):
    """The same samples into the BT.656 build of mixer2: nothing locks and mix_chan B's ext_bad
    follows the status input (high throughout)."""
    trace, end = run(picture, digital=False, tag='bt656')
    assert end == (0, 1), (trace, end)
    assert not any(lock for _, lock, _ in trace), trace
    assert all(bad == 1 for _, _, bad in trace), trace


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
