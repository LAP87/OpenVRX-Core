"""chan_scan.v (SCAN in the M6 menu) against model/chan_scan_ref.py, in sim/tb_chan_scan.v.

The testbench logs every tune, every noise window and the end. From those events alone the
test works out what each channel should have scored (second window after the settling, lock
when the channel was decided; chan_scan_ref.observe) and which channel the scan must keep
(chan_scan_ref.scan); the RTL's choice must equal it.

Worlds: several channels lock with different noise, two of them equal (the earlier wins), the
noisiest channel follows an unlocked very clean one (a first window would see the clean one);
nothing locks (the starting channel stays, found 0); receiver B delivers no windows (A alone
decides, each channel waits MAX_MS); a button during the scan (the starting channel stays).

Negative controls: a copy that scores on the first window after the settling, one that keeps
the highest noise, one that ignores the decoder lock. Each keeps another channel than the model.

Run: .venv/bin/python -m pytest -q gateware/sim/test_chan_scan.py"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import chan_scan_ref as ref  # noqa: E402

N = 48
START = 3
LOCK_MS = 25


def world_main():
    w = [(0, 1, 0, 1)] * N                          # nothing locks, very clean noise
    w[10] = (1, 400, 0, 1)                          # A locks, noise 400
    w[17] = (0, 1, 1, 250)                          # B locks, 250
    w[22] = (1, 300, 1, 120)                        # both lock: the lower one counts (120)
    w[30] = (1, 120, 0, 1)                          # tie with 22: 22 is earlier and wins (neither is the start)
    w[41] = (1, 900, 1, 950)                        # noisy channel after the unlocked clean 40
    return w


def world_tie_with_start():
    """Two clean transmitters: the starting channel (START) and an earlier table entry both lock
    with noise 0 on receiver A. The scan must keep the starting channel (Core #22)."""
    w = [(0, 1, 0, 1)] * N
    w[0] = (1, 0, 0, 1)
    w[START] = (1, 0, 0, 1)
    return w


MUTANTS = {
    'tie_to_earlier': [("({1'b0, sc} < best || (idx == start_idx && {1'b0, sc} == best))", "({1'b0, sc} < best)")],
    'first_window': [("wire        ok_a = (wa == 2'd2) && locked[0];", "wire        ok_a = (wa != 2'd0) && locked[0];"),
                     ("wire        ok_b = (wb == 2'd2) && locked[1];", "wire        ok_b = (wb != 2'd0) && locked[1];"),
                     ("if (new_a && wa != 2'd2) begin wa <= wa + 1'b1; sa <= noise_a; end",
                      "if (new_a && wa != 2'd2) begin wa <= wa + 1'b1; if (wa == 2'd0) sa <= noise_a; end"),
                     ("if (new_b && wb != 2'd2) begin wb <= wb + 1'b1; sb <= noise_b; end",
                      "if (new_b && wb != 2'd2) begin wb <= wb + 1'b1; if (wb == 2'd0) sb <= noise_b; end")],
    'keeps_highest': [("({1'b0, sc} < best || (idx == start_idx && {1'b0, sc} == best))", "(best[20] || {1'b0, sc} > best)")],
    'ignores_lock': [("wire        ok_a = (wa == 2'd2) && locked[0];", "wire        ok_a = (wa == 2'd2);"),
                     ("wire        ok_b = (wb == 2'd2) && locked[1];", "wire        ok_b = (wb == 2'd2);")],
}


def run(name, world, params=None, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'chan_scan.v').read_text()
    for old, new in MUTANTS.get(mutant, []):
        assert src.count(old) == 1, (mutant, old)
        src = src.replace(old, new)
    (work / 'chan_scan.v').write_text(src)
    (work / 'world.txt').write_text(''.join(' '.join(map(str, w)) + '\n' for w in world))
    p = {'START': START, 'LOCK_MS': LOCK_MS, **(params or {})}
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_chan_scan',
                    *[f'-Ptb_chan_scan.{k}={v}' for k, v in p.items()],
                    str(work / 'chan_scan.v'), str(HERE / 'tb_chan_scan.v')], cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    assert 'TIMEOUT' not in log
    tunes, win, end, tuned = [], {'A': [], 'B': []}, None, None
    for line in log.splitlines():
        q = line.split()
        if q[0] == 'T':
            tunes.append((int(q[1]), int(q[2])))
        elif q[0] in ('WA', 'WB'):
            win[q[0][1]].append((int(q[1]), int(q[2])))
        elif q[0] == 'D':
            end = (int(q[1]), int(q[2]), int(q[3]))
        elif q[0] == 'TUNED':
            tuned = int(q[1])
    return tunes, win, end, tuned


def expect(world, tunes, win, end):
    """The model's channel from the events: the scan's tunes are the first N (the last tune is
    the result), each channel decided at the next tune."""
    scan = tunes[:N]
    decided = [t for _, t in tunes[1:N]] + [end[2]]
    # events this close to a boundary could fall either side of it in the RTL
    for i, t0 in scan:
        for t, _ in win['A'] + win['B']:
            assert abs(t - (t0 + 30_000)) > 50 and abs(t - (t0 + 230_000)) > 50, (i, t0, t)
    obs = ref.observe(scan, win, decided, [(w[0], w[2]) for w in world], LOCK_MS)
    return ref.scan(obs, START), obs


def test_scan_keeps_the_quietest_locked_channel():
    w = world_main()
    tunes, win, end, tuned = run('tb_chan_scan_main', w)
    assert [i for i, _ in tunes[:N]] == list(range(N)), 'every channel in order'
    (want, found), obs = expect(w, tunes, win, end)
    assert (end[0], end[1]) == (want, int(found)) and tuned == want == 22, (end, want)
    per = [(end[2] - tunes[0][1]) / 1000 / N]
    assert 95 <= per[0] <= 170, per                 # ms per channel
    assert ref.score(obs[41]) == 900, 'the second window, not the clean channel before it'


def test_scan_keeps_the_start_on_a_tie():
    """Core #22 (review 2 SC-1): channel 0 and the starting channel both lock clean; the earlier
    table entry used to win. Negative control: the mutant with the old strict comparison keeps 0."""
    w = world_tie_with_start()
    tunes, win, end, tuned = run('tb_chan_scan_tie', w)
    (want, found), _ = expect(w, tunes, win, end)
    assert (end[0], end[1]) == (START, 1) and tuned == START and (want, found) == (START, True), (end, want)
    tunes, win, end, tuned = run('tb_chan_scan_tie_old', w, mutant='tie_to_earlier')
    assert end[0] == 0 and tuned == 0, 'the old rule keeps the earlier channel'


def test_scan_without_lock_keeps_the_start():
    w = [(0, 5, 0, 5)] * N
    tunes, win, end, tuned = run('tb_chan_scan_none', w)
    assert (end[0], end[1]) == (START, 0) and tuned == START
    assert expect(w, tunes, win, end)[0] == (START, False)


def test_scan_with_one_receiver():
    w = world_main()
    tunes, win, end, tuned = run('tb_chan_scan_no_b', w, {'NO_B': 1})
    (want, found), obs = expect(w, tunes, win, end)
    assert (end[0], end[1]) == (want, int(found)) == (30, 1), (end, want)  # 22 scores 300 on A alone
    assert all(t2 - t1 >= 230_000 for (_, t1), (_, t2) in zip(tunes[:N], tunes[1:N])), 'MAX_MS per channel'


def test_scan_abort_keeps_the_start():
    tunes, win, end, tuned = run('tb_chan_scan_abort', world_main(), {'ABORT_MS': 1500})
    assert (end[0], end[1]) == (START, 0) and tuned == START
    assert 5 < len(tunes) < N, len(tunes)


@pytest.mark.parametrize('mutant', sorted(k for k in MUTANTS if k != 'tie_to_earlier'))   # tie_to_earlier: its own test
def test_scan_negative_control(mutant):
    w = world_main()
    tunes, win, end, tuned = run(f'tb_chan_scan_{mutant}', w, mutant=mutant)
    want, _ = expect(w, tunes, win, end)
    assert end[0] != want[0], (mutant, end, want)
