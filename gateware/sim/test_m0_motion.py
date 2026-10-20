"""M0's bouncing square over 5000 frames against a model of the motion (sim/tb_m0_motion.v: the top
with its clocks, timing and transmitter stubbed, frame_start forced).

Found on the first hardware run (home bench 2026-10-20, hub docs/bench/HANDOFF_CLAUDE_2026-10-20.md):
the 11-bit x counter wrapped at the left edge (1 - 3 = 2046) and the square then alternated between
x = 1 and 2046 from frame 777 on. The fix clamps the position to the edge before turning.

Negative control: a copy of the top with the motion block as it was must leave the picture at frame
777 exactly as the bench trace did.

Run: .venv/bin/python -m pytest -q gateware/sim/test_m0_motion.py"""
import os
import re
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
FRAMES = 5000
X_MAX, Y_MAX = 1280 - 64, 720 - 64

ORIGINAL = ("""        if (dx) begin
            if (bx >= 1280 - 64 - 3) begin bx <= 1280 - 64; dx <= 0; end
            else bx <= bx + 11'd3;
        end else begin
            if (bx <= 3) begin bx <= 0; dx <= 1; end
            else bx <= bx - 11'd3;
        end
        if (dy) begin
            if (by >= 720 - 64 - 2) begin by <= 720 - 64; dy <= 0; end
            else by <= by + 11'd2;
        end else begin
            if (by <= 2) begin by <= 0; dy <= 1; end
            else by <= by - 11'd2;
        end
""", """        bx <= dx ? bx + 3 : bx - 3;
        by <= dy ? by + 2 : by - 2;
        if (bx >= 1280 - 64 - 3) dx <= 0; else if (bx <= 3) dx <= 1;
        if (by >= 720 - 64 - 2)  dy <= 0; else if (by <= 2) dy <= 1;
""")


def run(name, alter=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    top = (GW / 'top' / 'm0_testpattern.v').read_text()
    for old, new in (alter or []):
        assert top.count(old) == 1, old
        top = top.replace(old, new)
    (work / 'm0_testpattern.v').write_text(top)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_m0_motion', f'-Ptb_m0_motion.FRAMES={FRAMES}',
                    str(work / 'm0_testpattern.v'), str(HERE / 'tb_m0_motion.v')], cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    assert f'MOTION_END {FRAMES}' in log, log[-300:]
    rows = [tuple(int(v) for v in m) for m in re.findall(r'^T \d+ (\d+) (\d+) (\d) (\d)$', log, re.M)]
    holds = [tuple(int(v) for v in m) for m in re.findall(r'^H \d+ (\d+) (\d+) (\d) (\d)$', log, re.M)]
    assert len(rows) == len(holds) == FRAMES and rows == holds, 'the position changes only on frame_start'
    return rows


def model():
    """(x, y, dx, dy) after every frame: 3 and 2 pixels per frame, turned at the edges, never outside."""
    x = y = 100
    dx = dy = 1
    out = []
    for _ in range(FRAMES):
        x += 3 if dx else -3
        y += 2 if dy else -2
        if x >= X_MAX:
            x, dx = X_MAX, 0
        elif x <= 0:
            x, dx = 0, 1
        if y >= Y_MAX:
            y, dy = Y_MAX, 0
        elif y <= 0:
            y, dy = 0, 1
        out.append((x, y, dx, dy))
    return out


def test_bouncing_square_stays_in_the_picture():
    rows = run('tb_m0_motion')
    want = model()
    assert rows == want, next((i, r, w) for i, (r, w) in enumerate(zip(rows, want)) if r != w)
    assert all(0 <= x <= X_MAX and 0 <= y <= Y_MAX for x, y, _, _ in rows)
    for col, edge in ((0, 0), (0, X_MAX), (1, 0), (1, Y_MAX)):
        assert sum(r[col] == edge for r in rows) >= 5, (col, edge)


def test_motion_negative_control():
    """The block as it was before 2026-10-20: x wraps to 2046 at frame 777 and never recovers."""
    rows = run('tb_m0_motion_original', alter=[ORIGINAL])
    bad = next((i for i, (x, y, _, _) in enumerate(rows) if not (0 <= x <= X_MAX and 0 <= y <= Y_MAX)), None)
    assert bad == 777 and rows[777][0] == 2046, (bad, rows[777])
    assert all(r[0] in (1, 2046) for r in rows[777:])
    with pytest.raises(AssertionError):
        assert rows == model()
