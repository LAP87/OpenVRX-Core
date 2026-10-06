"""M3 bring-up probe: the report lines must show what is wrong with the wiring.

Decoder A is healthy (clean NTSC); decoder B has YOUT5 stuck low and YOUT2
stuck high, which also destroys every timing code, and its clock stops before
the last report. Checks every field of the fixed-width lines.

Run: .venv/bin/python -m pytest -q gateware/sim/test_probe.py"""
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
WINDOW = 270_000
LINE = re.compile(r'^([AB]) sclk (\d{8}) (.*) i2c (OK|NA|--) st (\S{4})$')


def run():
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_probe'
    work.mkdir(parents=True, exist_ok=True)
    src = [GW / 'rtl' / n for n in ('bt656_rx.v', 'bt656_probe.v', 'i2c_master.v', 'tvp_ctrl.v', 'rx5808_spi.v', 'rx_tune.v',
                                    'bin2bcd.v', 'uart_tx.v')] + [GW / 'top' / 'm3_probe.v']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_probe',
                    *map(str, src), str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_probe.v')],
                   cwd=work, env=env, check=True)
    vec = GW / 'vectors' / 'ntsc_clean_frame.hex'
    return subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={vec}'], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def test_probe_reports():
    log = run()
    assert 'RESULT spi=25' in log, log[-500:]               # one 25-bit RX5808 frame (F4) after start-up
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    raw = text.split('\r\n')
    lines = [l for l in raw[:-1] if l]                     # the run may end inside a line
    assert all(len(l) == 82 for l in lines), [len(l) for l in lines]   # 84 bytes with CR LF
    a = [l for l in lines if l.startswith('A')]
    b = [l for l in lines if l.startswith('B')]
    assert len(a) == len(b) >= 4, lines

    def fields(l):
        m = LINE.match(l)
        assert m, l
        return m.groups()

    # SCLK frequency: SCLK/256 edges per window x 256. A runs at the board clock's rate, B 0.27 % faster.
    fa = int(fields(a[1])[1])
    fb = int(fields(b[1])[1])
    assert abs(fa - WINDOW) <= 512, fa
    assert abs(fb - WINDOW * 37 / 36.9) <= 512, fb

    # windows 2 and 3: A healthy, B with its stuck bits and no timing codes
    for l in a[1:3]:
        _, _, body, i2c, st = fields(l)
        assert body.startswith('tog FF hi FF len 1716-1716 ln '), l
        m = re.search(r'ln (\d{5}) fld (\d{3}) xe (\d{4})', body)
        assert m and 100 <= int(m[1]) <= 160 and int(m[2]) <= 1 and m[3] == '0000', l
        assert i2c == 'OK' and st == '000E', l
    for l in b[1:3]:
        _, _, body, i2c, st = fields(l)
        assert body.startswith('tog DB hi DF len --------- ln 00000 fld 000 xe 0000'), l
        assert i2c == 'OK' and st == '000E', l

    # B's clock has stopped: the line says so instead of repeating stale values
    _, f_dead, body, _, _ = fields(b[3])
    assert body.strip() == 'no SCLK' and int(f_dead) < WINDOW // 2, b[3]
    assert fields(a[3])[2].startswith('tog FF hi FF'), a[3]
