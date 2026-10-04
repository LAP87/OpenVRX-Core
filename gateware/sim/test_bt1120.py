"""bt1120_tx: timing codes at the right places with the right XY, pixel data
and Cb/Cr alternation in between. Run: .venv/bin/python -m pytest -q gateware/sim/test_bt1120.py"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402

HA, HT, VA, VT = 16, 28, 4, 6


def expected(x, y):
    yn = 0 if y == VT - 1 else y + 1
    v = 1 if yn >= VA else 0
    for start, h in ((HA, 1), (HT - 4, 0)):
        if start <= x < start + 4:
            w = [0xFF, 0x00, 0x00, bt656.xy(0, v, h)][x - start]
            return w, w
    if x < HA and y < VA:
        return (40 + x + 8 * y) & 0xFF, (100 + x if x % 2 == 0 else 150 + y) & 0xFF
    return 0x10, 0x80


def test_bt1120_codes_and_data():
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_bt1120'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_bt1120', str(GW / 'rtl' / 'bt1120_tx.v'),
                    str(HERE / 'tb_bt1120.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    rows = [l.split()[1:] for l in out.splitlines() if l.startswith('O ')]
    assert len(rows) > HT * VT
    seen_v = set()
    for x, y, oy, oc in rows:
        x, y = int(x), int(y)
        got = (int(oy, 16), int(oc, 16))
        assert got == expected(x, y), (x, y, got, expected(x, y))
        if x == HT - 1:
            seen_v.add(got[0] >> 5 & 1)
    assert seen_v == {0, 1}                                  # both active and blanking SAVs occurred
