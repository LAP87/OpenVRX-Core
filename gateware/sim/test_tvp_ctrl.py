"""tvp_ctrl (I2C bring-up and status polling of our own TVP5150AM1s) against
behavioural I2C slaves.  Run: .venv/bin/python -m pytest -q gateware/sim/test_tvp_ctrl.py"""
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent


def run(present1, split=0):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_tvp_ctrl_{present1}{split}'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_tvp_ctrl', f'-Ptb_tvp_ctrl.PRESENT1={present1}', f'-Ptb_tvp_ctrl.SPLIT={split}',
                    str(GW / 'rtl' / 'i2c_master.v'), str(GW / 'rtl' / 'tvp_ctrl.v'),
                    str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_tvp_ctrl.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    line = next(l for l in out.splitlines() if l.startswith('RESULT'))
    assert 'timeout' not in line, out[-2000:]
    return dict(re.findall(r'(\w+)=(\w+)', line))


def test_two_decoders():
    r = run(1)
    assert r['reset_low'] == '1'
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_0d'], r['s0_00']) == ('0d', '47', '00')
    assert (r['s1_03'], r['s1_0d']) == ('0d', '47')
    assert r['s0_writes'] == '3' and r['s1_writes'] == '3'
    assert r['st0'] == '000e' and r['st1'] == '0006' and r['valid'] == '3'


def test_missing_decoder_flagged():
    r = run(0)
    assert r['err'] == '2'                      # decoder 1 (5Dh) did not acknowledge
    assert (r['s0_03'], r['s0_0d']) == ('0d', '47')
    assert r['st0'] == '000e' and r['valid'] == '1'


def test_same_address_split_sda():
    """Two identical modules (both 5Ch) on separate SDA lines with a shared SCL."""
    r = run(1, split=1)
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_0d'], r['s1_03'], r['s1_0d']) == ('0d', '47', '0d', '47')
    assert r['s0_writes'] == '3' and r['s1_writes'] == '3'
    assert r['st0'] == '000e' and r['st1'] == '0006' and r['valid'] == '3'
