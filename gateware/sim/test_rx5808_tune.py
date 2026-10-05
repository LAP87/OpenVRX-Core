"""rx5808_tune: when the RX5808 synthesiser register is written.

The testbench plays lock changes and channel changes; every SPI frame is compared,
start time and all 25 bits, with `expected_frames` below, a model of the rule:
first write FIRST after reset whatever the lock says, a write at once on a
channel change, a repeat whenever REPEAT have passed with no write and no lock.

Negative controls: the same sequence with the lock input held low (a design
that ignores the lock) must not match the model, and the idle-level counter
must report violations when it is told to expect DATA low between frames.

Run: .venv/bin/python -m pytest -q gateware/sim/test_rx5808_tune.py"""
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
import vtx_channels as vc  # noqa: E402

FIRST, REPEAT = 50e6, 200e6          # ns, as the testbench sets them
FRAME = 102e3                        # ns: 25 bits of 4 phases plus two guard phases, 1 us each
RESET = 3e3                          # ns: the testbench releases reset here
SYNTH = {ch: reg for b, c, f, reg, _ in vc.table() for ch in [f'{b}{c}']}


def run(scenario=0, use_lock=1, idle_data=1):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_rx5808_tune_{scenario}{use_lock}{idle_data}'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_rx5808_tune',
                    f'-Ptb_rx5808_tune.SCENARIO={scenario}', f'-Ptb_rx5808_tune.USE_LOCK={use_lock}',
                    f'-Ptb_rx5808_tune.IDLE_DATA={idle_data}',
                    str(GW / 'rtl' / 'rx5808_spi.v'), str(GW / 'rtl' / 'rx5808_tune.v'),
                    str(HERE / 'tb_rx5808_tune.v')], cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    events = sorted([(int(t), 'lock', int(v)) for t, v in re.findall(r'^LOCK (\d+) (\d)$', log, re.M)] +
                    [(int(t), 'write', int(s, 16)) for t, s in re.findall(r'^WRITE (\d+) (\w+)$', log, re.M)])
    frames = [(int(t), int(n), int(bits, 16)) for t, n, bits in re.findall(r'^SPI (\d+) (\d+) (\w+)$', log, re.M)]
    res = dict(re.findall(r'(\w+)=(\d+)', next(l for l in log.splitlines() if l.startswith('RESULT'))))
    return events, frames, res


def expected_frames(events, end):
    """(start time in ns, synthesiser word) of every frame. Stepped in microseconds."""
    out, ev = [], list(events)
    locked, synth, want, first_done = False, SYNTH['F4'], False, False
    quiet, busy_until, t = 0.0, 0.0, RESET
    while t < end:
        while ev and ev[0][0] <= t:
            _, kind, val = ev.pop(0)
            if kind == 'lock':
                locked = bool(val)
            else:
                synth, want = val, True
        if not first_done:
            if t - RESET >= FIRST:
                first_done = want = True
        elif locked or t < busy_until:
            quiet = 0.0
        else:
            quiet += 1e3
            if quiet >= REPEAT:
                want = True
        if want and t >= busy_until:
            out.append((t, synth))
            busy_until, want, quiet = t + FRAME, False, 0.0
        t += 1e3
    return out


def word(synth):
    return sum(bit << i for i, bit in enumerate(vc.spi_frame(synth)))


def compare(frames, want):
    assert len(frames) == len(want), (frames, want)
    for (t, n, bits), (t_want, synth) in zip(frames, want):
        assert n == 25 and bits == word(synth), (t, n, hex(bits), hex(word(synth)))
        assert abs(t - t_want) <= 10e3, (t, t_want)             # within 10 clocks


def test_schedule_matches_model():
    events, frames, res = run()
    want = expected_frames(events, 1800e6)
    compare(frames, want)
    # the sequence exercises every rule: first write, repeats, silence while locked, a change while
    # locked, repeats again 200 ms after the lock is gone, a change during a frame
    assert [round(t / 1e6) for t, _ in want] == [50, 250, 450, 700, 1200, 1400, 1710, 1710]
    assert [s for _, s in want] == [SYNTH['F4']] * 3 + [SYNTH['A6']] * 4 + [SYNTH['B1']]
    assert res == {'idle_bad': '0', 'sel_bad': '0'}             # CLK low, DATA high between frames


def test_first_write_comes_even_when_locked():
    events, frames, res = run(scenario=1)
    compare(frames, expected_frames(events, 600e6))
    assert len(frames) == 1 and round(frames[0][0] / 1e6) == 50
    assert res == {'idle_bad': '0', 'sel_bad': '0'}


def test_negative_controls():
    # a design that ignores the lock keeps repeating: the model comparison must reject it
    events, frames, res = run(use_lock=0)
    with pytest.raises(AssertionError):
        compare(frames, expected_frames(events, 1800e6))
    # the idle check must see DATA: told to expect low, it has to count violations
    assert int(run(idle_data=0)[2]['idle_bad']) > 1_000_000
