"""snow_stats: window means and decision counts (16-line windows in the test)."""
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent


def test_snow_stats():
    env = dict(os.environ)
    ib = PROJECT / '.tools' / 'iverilog' / 'bin'
    if ib.exists():
        env['PATH'] = f'{ib}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_snow_stats'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_snow_stats', str(GW / 'rtl' / 'snow_stats.v'),
                    str(HERE / 'tb_snow_stats.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    lines = out.split()
    a = [int(lines[i + 1]) for i, t in enumerate(lines) if t == 'A']
    b = [int(lines[i + 1]) for i, t in enumerate(lines) if t == 'B']
    u = [tuple(int(x) for x in lines[i + 1:i + 4]) for i, t in enumerate(lines) if t == 'U']
    assert a == [sum(range(100, 116)) // 16, sum(range(116, 132)) // 16], a     # 107, 123
    assert b == [5000, 5000], b                                                 # 32 lines from i = 8: two windows
    assert u == [(8, 4, 4), (8, 4, 4)], u                                       # A,A,B,blend repeating
