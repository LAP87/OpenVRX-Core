"""rx_tune.v: the RX5808 channel is written START_MS after reset and again
every PERIOD_MS only while no decoder is locked; each write is one 25-bit
frame with the F4 register; DATA idles high (its pin is an active-low LED).

Run: .venv/bin/python -m pytest -q gateware/sim/test_rx_tune.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import vtx_channels as vc  # noqa: E402


def test_rx_tune():
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_rx_tune'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_rx_tune',
                    str(GW / 'rtl' / 'rx5808_spi.v'), str(GW / 'rtl' / 'rx_tune.v'), str(HERE / 'tb_rx_tune.v')],
                   cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
                         capture_output=True, text=True).stdout
    marks = dict(re.findall(r'MARK (\w+) frames=(\d+)', log))
    assert marks == {'before_start': '0', 'unlocked': '3', 'locked': '3', 'relost': '5'}, log
    assert 'idle_high=1' in log, log
    reg = next(r for b, c, f, r, _ in vc.table() if (b, c) == ('F', 4))
    want = sum(bit << i for i, bit in enumerate(vc.spi_frame(reg)))
    for n, w in re.findall(r'FRAME \d+ bits=(\d+) word=(\w+)', log):
        assert int(n) == 25 and int(w, 16) == want, (n, w, hex(want))
