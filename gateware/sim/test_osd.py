"""osd_overlay pixel-exact: glyph pixels white, box darkened to half, video
untouched outside the box and everywhere when the OSD is hidden.
Run: .venv/bin/python -m pytest -q gateware/sim/test_osd.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import font5x7  # noqa: E402

ROWS = ['>BAND F   CH 4  5800 ', ' MODE MIX   VIEW A   ', 'A  12345 ########    ', ' USE A 40 B 34 M 25  ']
X0, Y0, S, PAD = 10, 20, 2, 3
W, H = 21 * 6 * S, 4 * 8 * S


def run(show):
    env = dict(os.environ)
    ib = PROJECT / '.tools' / 'iverilog' / 'bin'
    if ib.exists():
        env['PATH'] = f'{ib}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_osd_{show}'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'text.hex').write_text('\n'.join(f'{ord(c):02x}' for c in ''.join(ROWS)) + '\n')
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_osd',
                    f'-Ptb_osd.SHOW={show}', str(GW / 'rtl' / 'osd_overlay.v'), str(HERE / 'tb_osd.v')],
                   cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    return {(int(m[0]), int(m[1])): (int(m[2], 16), int(m[3], 16), int(m[4], 16))
            for m in re.findall(r'P (\d+) (\d+) (\w+) (\w+) (\w+)', out)}


def expected(x, y, show):
    video = (x & 0xFF, y & 0xFF, 0x40)
    if not show:
        return video
    if X0 <= x < X0 + W and Y0 <= y < Y0 + H:
        col, gx = divmod((x - X0) // S, 6)
        row, gy = divmod((y - Y0) // S, 8)
        if gx < 5 and gy < 7 and (font5x7.columns(ROWS[row][col])[gx] >> gy) & 1:
            return (0xFF, 0xFF, 0xFF)
    if X0 - PAD <= x < X0 + W + PAD and Y0 - PAD <= y < Y0 + H + PAD:
        return tuple(v >> 1 for v in video)
    return video


def check(show):
    px = run(show)
    assert len(px) == 256 * 120, len(px)
    bad = [(k, v, expected(*k, show)) for k, v in px.items() if v != expected(*k, show)]
    assert not bad, bad[:5]


def test_osd_shown():
    check(1)


def test_osd_hidden():
    check(0)
