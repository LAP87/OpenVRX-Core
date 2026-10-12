"""Low-latency trigger payload (fb_backend.v -> toggle_tx -> toggle_rx): each frame trigger must
reach the pixel domain with the line count of the field before the one that triggered, also
when the next field starts right after the trigger.

Scenario (sim/tb_ll_payload.v): a field of 3 lines the ring writer joins (it fires no trigger
and its count is not kept), a field of 3 lines, a field of 2 lines, then a further field
starting at once (or 20 SDRAM clocks later). The second trigger carries 3. The review on
2026-10-06 (hub docs/reviews/2026-10-06, "LOW-payload över klockdomäner") found 2 arriving
in the first case.

Negative control: a copy of fb_backend.v that hands the receiver the live count instead of
the copy toggle_tx holds receives 2 again.

Run: .venv/bin/python -m pytest -q gateware/sim/test_ll_payload.py"""
import os
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
RTL = ('cdc_sync.v', 'sdram_burst.v', 'field_phase.v', 'fb_sdram.v', 'dual_clock_ram.v', 'genlock_timing.v',
       'ycbcr2rgb.v', 'fb_display.v', 'vblend.v')
HELD, LIVE = '.din(s_ll_pay)', '.din(s_ll_lines)'
EXPECT = [0, 3]                      # no field before the first; the first field had lines 0-2


def run(guard, live=False):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_ll_payload_{guard}{"_live" if live else ""}'
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'fb_backend.v').read_text()
    if live:
        assert src.count(HELD) == 1
        src = src.replace(HELD, LIVE)
    (work / 'fb_backend.v').write_text(src)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_ll_payload', f'-Ptb_ll_payload.GUARD={guard}',
                    *[str(GW / 'rtl' / n) for n in RTL], str(work / 'fb_backend.v'), str(HERE / 'tb_ll_payload.v')],
                   cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert 'DONE' in log, log[-2000:]
    return ([int(x) for x in re.findall(r'^SEND (\d+)$', log, re.M)],
            [int(x) for x in re.findall(r'^RECEIVE (\d+)$', log, re.M)])


@pytest.mark.parametrize('guard', [0, 1])
def test_ll_payload_arrives_whole(guard):
    sent, received = run(guard)
    assert sent == EXPECT, sent
    assert received == EXPECT, received


def test_ll_payload_negative_control():
    sent, received = run(0, live=True)
    assert len(received) == 2, received
    assert received != EXPECT and received[1] == 2, received
