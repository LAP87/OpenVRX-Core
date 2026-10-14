"""rtl/async_fifo.v with RD_REG = 0 and 1 (sim/tb_async_fifo.v) against a queue: every popped word is
the next accepted write, both read modes pop the same words and show the same rd_data on every
read clock while !empty, with a reader that stalls and then pops back to back, a writer faster or
slower than the reader, and a reset of both sides with words in the FIFO. The formal proofs
(formal/run.sh, async_fifo_rd_reg_*) cover the same properties for all inputs on a small FIFO."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
FIFO = (GW / 'rtl' / 'async_fifo.v').read_text()

CASES = {               # name: write clock period, read clock period (ns), seed
    'fast_reader': (37.0, 13.0, 1),
    'slow_reader': (11.0, 41.0, 2),
    'near_equal': (29.0, 27.0, 3),
}


def run(name, tw, tr, seed, source=FIFO):
    work = HERE / 'build' / f'tb_async_fifo_{name}'
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    (work / 'async_fifo.v').write_text(source)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_async_fifo',
                    f'-Ptb_async_fifo.TW={tw}', f'-Ptb_async_fifo.TR={tr}', f'-Ptb_async_fifo.SEED={seed}',
                    str(work / 'async_fifo.v'), str(HERE / 'tb_async_fifo.v')], cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    segments, counts = [{'W': [], 'P0': [], 'P1': []}], {}
    for line in (work / 'out.txt').read_text().split('\n'):
        if not line:
            continue
        if line == 'RESET':
            segments.append({'W': [], 'P0': [], 'P1': []})
            continue
        key, value = line.split()
        if key in ('W', 'P0', 'P1'):
            segments[-1][key].append(int(value))
        else:
            counts[key] = int(value)
    return segments, counts


def faults(segments, counts):
    """What differs from a queue, or between the two read modes."""
    out = []
    for i, s in enumerate(segments):
        if s['P0'] != s['W'][:len(s['P0'])]:
            out.append(f'segment {i}: RD_REG = 0 pops are not the writes in order')
        if s['P1'] != s['W'][:len(s['P1'])]:
            out.append(f'segment {i}: RD_REG = 1 pops are not the writes in order')
        if s['P1'] != s['P0']:
            out.append(f'segment {i}: the two read modes pop different words')
    if counts['D']:
        out.append(f"{counts['D']} read clocks with different rd_data while not empty")
    if counts['E']:
        out.append(f"{counts['E']} read clocks with different empty/full/levels")
    return out


@pytest.mark.parametrize('case', CASES)
def test_async_fifo_both_read_modes_are_a_queue(case):
    tw, tr, seed = CASES[case]
    segments, counts = run(case, tw, tr, seed)
    assert len(segments) == 2
    assert all(len(s['P0']) > 300 for s in segments)     # both halves move data
    assert counts['B'] > 100                               # pops on consecutive clocks happen
    if case == 'slow_reader':
        assert counts['F'] > 100                           # the FIFO runs full
    assert not faults(segments, counts)


def test_async_fifo_check_is_tested():
    """Negative control: a read register loaded from the current read pointer instead of its next
    value shows the popped word again on the clock after a pop."""
    old = 'always @(posedge rclk) rd_q <= mem[rd_next];'
    assert FIFO.count(old) == 1
    tw, tr, seed = CASES['slow_reader']
    segments, counts = run('late', tw, tr, seed, FIFO.replace(old, 'always @(posedge rclk) rd_q <= mem[rbin[AW-1:0]];'))
    found = faults(segments, counts)
    assert any('RD_REG = 1 pops' in f for f in found) and counts['D'] > 0
