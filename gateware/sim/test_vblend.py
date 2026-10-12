"""rtl/vblend.v (vertical interpolation of one sample, fb_display.v VINTERP = 1) against
model/fb_ref.py vblend(): every weight 0..8 with a grid of sample pairs and random ones."""
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import fb_ref as fb  # noqa: E402

VBLEND = (GW / 'rtl' / 'vblend.v').read_text()


def vectors():
    rnd = random.Random(7)
    grid = list(range(0, 256, 15)) + [255]
    pairs = [(a, b) for a in grid for b in grid] + [(rnd.randrange(256), rnd.randrange(256)) for _ in range(400)]
    return [(w, a, b) for w in range(9) for a, b in pairs]


def run(name, vec, source=VBLEND):
    work = HERE / 'build' / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    (work / 'vblend.v').write_text(source)
    (work / 'vec.hex').write_text(''.join(f'{w:x}{a:02x}{b:02x}\n' for w, a, b in vec))
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_vblend', f'-Ptb_vblend.N={len(vec)}',
                    str(work / 'vblend.v'), str(HERE / 'tb_vblend.v')], cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    return [int(x) for x in (work / 'out.txt').read_text().split()]


def mismatches(vec, got):
    return [(w, a, b, y, fb.vblend(a, b, w)) for (w, a, b), y in zip(vec, got) if y != fb.vblend(a, b, w)]


def test_vblend_matches_the_model():
    vec = vectors()
    got = run('tb_vblend', vec)
    assert len(got) == len(vec)
    assert not mismatches(vec, got)[:5]
    assert all(y == a for (w, a, b), y in zip(vec, got) if w == 0)       # w = 0: a untouched
    assert all(y == b for (w, a, b), y in zip(vec, got) if w == 8)       # w = 8: b


@pytest.mark.parametrize('fault, old, new', [
    ('swapped', 'a * wa + b * w', 'a * w + b * wa'),            # the weight on the wrong line
    ('rounded', 'sum[10:3]', '(sum + 12\'d4) >> 3'),             # rounding to nearest instead of down
])
def test_vblend_check_is_tested(fault, old, new):
    """Negative controls: a blend with the weights swapped, or rounded to nearest, differs."""
    assert VBLEND.count(old) == 1
    vec = vectors()
    assert mismatches(vec, run(f'tb_vblend_{fault}', vec, VBLEND.replace(old, new)))
