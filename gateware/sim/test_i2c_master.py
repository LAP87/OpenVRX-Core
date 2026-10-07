"""i2c_master.v single- and multi-byte writes against sim/i2c_slave_model.v, compared
transaction by transaction with model/i2c_ref.py: every START, STOP, byte and ACK bit
on the bus (seen by a monitor in the testbench, not by the slave), the master's nack,
stuck and wreq pulses, every register the slave stores, and the values read back.

Scenarios (sim/tb_i2c_master.v): writes of 1, 2 and 8 bytes; 8 bytes with the slave
refusing the 4th (the master stops there); multi- and single-byte writes to an absent
address; a NACK on the first data byte; reads; 256 bytes in one write (wextra = 255,
the register pointer wraps); a slave holding SCL low shorter than STRETCH_MAX (nothing
changes), and for good (the master gives up after STRETCH_MAX clocks with nack and stuck,
having released both lines, and the next transactions work).

Negative controls: a slave whose register pointer does not advance, a copy of i2c_master.v
that ignores a NACK in a multi-byte write, and one that never gives up on a held SCL must
each disagree with the model.

Run: .venv/bin/python -m pytest -q gateware/sim/test_i2c_master.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import i2c_ref  # noqa: E402

STRETCH_MAX = 200                     # tb_i2c_master.v
MUTANTS = {
    'master_ignores_nack': ("if (op_multi && nack) tk <= 3'd4;", "if (1'b0) tk <= 3'd4;"),
    'master_never_gives_up': ("if (stretch && st_n == STRETCH_MAX - 1) begin", "if (1'b0) begin"),
}


def fill(n, seed):
    return [(i * 29 + seed) & 0xFF for i in range(n)]


# the same sequence as the initial block of tb_i2c_master.v: (name, [transactions])
SCRIPT = [
    ('one', [('w', 0x5C, 0x10, fill(1, 0xA5), -1)]),
    ('two', [('w', 0x5C, 0x20, fill(2, 0x11), -1)]),
    ('eight', [('w', 0x5C, 0x30, fill(8, 0x31), -1)]),
    ('nack_mid', [('w', 0x5C, 0x40, fill(8, 0x57), 3)]),
    ('absent_multi', [('w', 0x5D, 0x50, fill(2, 0x66), -1)]),
    ('absent_one', [('w', 0x5D, 0x60, fill(1, 0x77), -1)]),
    ('nack_first', [('w', 0x5C, 0x68, fill(4, 0x0C), 0)]),
    ('read', [('r', 0x5C, r) for r in (0x10, 0x21, 0x30, 0x37, 0x42, 0x43, 0x68)] + [('r', 0x5D, 0x10)]),
    ('full', [('w', 0x5C, 0xA0, fill(256, 0x03), -1)]),
    ('read2', [('r', 0x5C, r) for r in (0xA0, 0xFF, 0x00, 0x9F)]),
    ('stretch', [('w', 0x5C, 0xB0, fill(2, 0x44), -1)]),                 # SCL held 150 clocks: as usual
    ('stuck', [('stuck',)]),                                             # SCL held low for good
    ('after_stuck', [('w', 0x5C, 0xD0, fill(1, 0x99), -1), ('r', 0x5C, 0xD0), ('r', 0x5C, 0xB1)]),
]


def model(auto_inc=True):
    s = i2c_ref.Slave(0x5C, auto_inc)
    out = []
    for name, trs in SCRIPT:
        res = []
        for t in trs:
            if t[0] == 'w':
                ev, nack, wreq = i2c_ref.write(s, t[1], t[2], t[3], t[4])
                res.append((ev, int(nack), wreq, None, 0))
            elif t[0] == 'r':
                ev, nack, value = i2c_ref.read(s, t[1], t[2])
                res.append((ev, int(nack), 0, value, 0))
            else:
                # held during the device address: START, no whole byte, no STOP; nothing stored
                res.append((['S'], 1, 0, None, 1))
        out.append((name, res))
    return out, s.writes


def run(auto_inc=1, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_i2c_master_{auto_inc}_{mutant or "rtl"}'
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'i2c_master.v').read_text()
    if mutant:
        old, new = MUTANTS[mutant]
        assert src.count(old) == 1, mutant
        src = src.replace(old, new)
    (work / 'i2c_master.v').write_text(src)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_i2c_master',
                    f'-Ptb_i2c_master.AUTO_INC={auto_inc}', f'-Ptb_i2c_master.STRETCH_MAX={STRETCH_MAX}',
                    str(work / 'i2c_master.v'), str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_i2c_master.v')],
                   cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert 'END' in log and 'TIMEOUT' not in log, log[-2000:]
    out, writes, cur, ev, value = [], [], None, [], None
    for line in log.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == 'T':
            cur = (p[1], [])
            out.append(cur)
        elif p[:2] == ['BUS', 'S']:
            ev.append('S')
        elif p[:2] == ['BUS', 'P']:
            ev.append('P')
        elif p[:2] == ['BUS', 'B']:
            ev.append(('B', int(p[2], 16), int(p[3])))
        elif p[0] == 'RD':
            value = int(p[1], 16)
        elif p[0] == 'DONE':
            cur[1].append((ev, int(p[1]), int(p[2]), value, int(p[3])))
            ev, value = [], None
        elif p[0] == 'HUNG':
            cur[1].append(('HUNG',))
            ev, value = [], None
        elif p[:2] == ['I2C', 'W']:
            writes.append((int(p[2], 16), int(p[3], 16)))
    held = [int(x) for x in re.findall(r'^HELD (\d+)$', log, re.M)]
    return out, writes, held


def test_model_scenarios_say_what_they_claim():
    tr, writes = model()
    by = dict(tr)
    ev, nack, wreq, _, _ = by['nack_mid'][0]
    assert nack == 1 and wreq == 4 and [e[2] for e in ev[1:-1]] == [0, 0, 0, 0, 0, 1]   # dev, reg, 3 data, NACK
    assert by['absent_multi'][0][0] == ['S', ('B', 0x5D << 1, 1), 'P']
    assert len(by['absent_one'][0][0]) == 5                                            # all three bytes sent
    assert [t[3] for t in by['read']][:4] == [0xA5, fill(2, 0x11)[1], fill(8, 0x31)[0], fill(8, 0x31)[7]]
    assert [t[3] for t in by['read']][4:] == [fill(8, 0x57)[2], 0, 0, 0xFF]            # 43h and 68h never written
    assert by['nack_first'][0][1:3] == (1, 1) and len(by['nack_first'][0][0]) == 5        # S dev reg data(NACK) P
    assert by['full'][0][2] == 255
    assert [t[3] for t in by['after_stuck'][1:]] == [0x99, fill(2, 0x44)[1]]            # written after / before
    assert len(writes) == 1 + 2 + 8 + 3 + 256 + 2 + 1


def test_i2c_master_matches_model():
    got, writes, held = run()
    want, want_writes = model()
    assert [n for n, _ in got] == [n for n, _ in want]
    for (name, g), (_, w) in zip(got, want):
        assert len(g) == len(w), name
        for i, (gt, wt) in enumerate(zip(g, w)):
            assert gt == wt, f'{name} #{i}: got {gt}, model {wt}'
    assert writes == want_writes
    # the master gave up STRETCH_MAX clocks after it first found SCL held (plus the few clocks from the
    # hold to the master releasing SCL and its two synchroniser stages)
    assert len(held) == 1 and STRETCH_MAX <= held[0] <= STRETCH_MAX + 12, held


@pytest.mark.parametrize('case', ['slave_no_auto_increment', 'master_ignores_nack', 'master_never_gives_up'])
def test_i2c_master_negative_control(case):
    got, writes, held = run(auto_inc=0) if case == 'slave_no_auto_increment' else run(mutant=case)
    want, want_writes = model()
    assert len(got) == len(want), 'the altered run still completes'
    assert (got, writes) != (want, want_writes)
    if case == 'slave_no_auto_increment':
        assert writes != want_writes and dict(got)['read'] != dict(want)['read']
    elif case == 'master_ignores_nack':
        assert dict(got)['nack_mid'] != dict(want)['nack_mid']
        assert dict(got)['one'] == dict(want)['one'], 'single-byte writes do not depend on the abort'
    else:
        assert dict(got)['stuck'] == [('HUNG',)], dict(got)['stuck']
        assert dict(got)['stretch'] == dict(want)['stretch'], 'a short stretch does not depend on the time-out'
