"""flash_store.v (saved settings in the Tang Nano 20K's SPI flash) against model/flash_store_ref.py,
with sim/spi_flash_model.v (sim/tb_flash_store.v).

Each run starts from an 8 KB image of the two settings sectors and a schedule of setting
changes. The start scan must load what the model's scan loads; every change that then stands
still for SAVE_MS (and differs from what is saved) must be written as one record where the model
puts it, and nothing else; the final image must equal the model's byte for byte, and each write
reads back. Cases: an empty flash (first save erases sector 0); quick changes (only the last one
is saved); no change (no write); a full sector 0 with garbage in sector 1 (the next save erases
sector 1 and goes in its slot 0); a newest record with a bad CRC (the one before it loads, and
the slot after it is not erased, so the save moves to the other sector); seq wrapping past
FFFFh; a restart on the image a run left (its last save loads).

Negative controls, each disagrees with the model: a copy that does not check the CRC, one that
never erases, one that writes at once instead of after SAVE_MS, one that never drives WP#.

Run: .venv/bin/python -m pytest -q gateware/sim/test_flash_store.py"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import flash_store_ref as ref  # noqa: E402

SAVE_MS = 50
EMPTY = b'\xff' * 8192
P1 = ref.payload(3, 3, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0)        # F4, MIX, BUF, TV, uncalibrated
P2 = ref.payload(4, 7, 1, 1, 1, 4000, 12000, 4800, 12800)
P3 = ref.payload(0, 0, 2, 0, 1, 100, 9000, 200, 9100)

MUTANTS = {
    'no_crc': [("if (rec[0] == 8'hA5 && x_rx == crc && (!have", "if (rec[0] == 8'hA5 && (!have")],
    'no_erase': [("prog_phase <= !need_erase; st <= S_CRC;", "prog_phase <= 1'b1; st <= S_CRC;")],
    'no_wait': [("            else if (t != SAVE_MS * MS) t <= t + 1;\n", "")],
    'no_wp': [("if (pos[3:0] == 4'd15) begin pos <= 0; flash_wp_drive <= 1'b1;", "if (pos[3:0] == 4'd15) begin pos <= 0;")],
}


def run(name, mem, sched, end_ms=1500, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'flash_store.v').read_text()
    for old, new in MUTANTS.get(mutant, []):
        assert src.count(old) == 1, (mutant, old)
        src = src.replace(old, new)
    (work / 'flash_store.v').write_text(src)
    (work / 'mem.hex').write_text(''.join(f'{b:02x}\n' for b in mem))
    (work / 'sched.txt').write_text(''.join(f'{t} {p.hex()}\n' for t, p in sched))
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_flash_store', f'-Ptb_flash_store.SAVE_MS={SAVE_MS}',
                    f'-Ptb_flash_store.END_MS={end_ms}', str(work / 'flash_store.v'), str(HERE / 'spi_flash_model.v'),
                    str(HERE / 'tb_flash_store.v')], cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    loads = [(bytes.fromhex(q[1]), int(q[2])) for q in (l.split() for l in log.splitlines()) if q and q[0] == 'LOAD']
    ready = next(int(l.split()[1]) for l in log.splitlines() if l.startswith('READY'))
    end = next(tuple(int(x) for x in l.split()[1:]) for l in log.splitlines() if l.startswith('END'))
    out = bytes(int(x, 16) for x in (work / 'mem_out.hex').read_text().split())
    return loads, end, out, ready


def model(mem, sched, ready):
    """(loads, final image, number of writes, erases). The schedule's gaps are either much shorter
    or much longer than SAVE_MS plus a write, so each value either stands or does not. Until the
    start scan is over (ready, ms) nothing is saved: the value then is the starting point, or the
    loaded record, which the menu takes."""
    pay, seq, slot, erase = ref.scan(mem)
    loads = [(pay, seq)] if pay is not None else []
    assert all(not (ready - 5 <= t <= ready + 5) for t, _ in sched), 'a change at the end of the start scan'
    first = pay if pay is not None else [p for t, p in sched if t < ready][-1]
    sched = [(ready, first)] + [s for s in sched if s[0] > ready]
    saved = first
    writes = erases = 0
    for k, (t, p) in enumerate(sched):
        if k == 0:
            continue                          # the starting point is what is saved
        nxt = sched[k + 1][0] if k + 1 < len(sched) else None
        stands = nxt is None or nxt - t > SAVE_MS + 100     # SAVE_MS, then a write with an erase (< 70 ms)
        assert stands or nxt - t < SAVE_MS // 2, 'a gap near SAVE_MS'
        if stands and p != saved:
            seq = (seq + 1) & 0xFFFF
            erases += erase
            mem, slot_n, erase_n = ref.save(mem, slot, erase, seq, p)
            slot, erase, saved, writes = slot_n, erase_n, p, writes + 1
    return loads, mem, writes, erases


def image(records, garbage_from=None):
    """An image with records [(slot, seq, payload, good crc)] and optional non-FF bytes from a slot on."""
    mem = bytearray(ref.SECTOR * 2 * b'\xff')
    if garbage_from is not None:
        for i in range(16 * garbage_from, len(mem)):
            mem[i] = (i * 37) & 0x7F
    for slot, seq, pay, good in records:
        r = bytearray(ref.record(seq, pay))
        if not good:
            r[15] ^= 0x01
        mem[16 * slot:16 * slot + 16] = r
    return bytes(mem)


CASES = {
    # start value at t 0 (the defaults the menu starts with), then changes
    'empty': (EMPTY, [(0, P1), (200, P2), (210, P3), (220, P2), (600, P3), (1000, P2), (1015, P3), (1030, P1)]),
    'full_sector': (image([(s, s + 1, P2 if s % 2 else P3, True) for s in range(256)], garbage_from=256),
                    [(0, P1), (300, P1)]),
    'bad_newest': (image([(s, 10 + s, P2, True) for s in range(4)] + [(4, 14, P3, False)]), [(0, P1), (300, P3)]),
    'seq_wrap': (image([(0, 65534, P1, True), (1, 65535, P2, True), (2, 0, P3, True), (3, 1, P2, True)]),
                 [(0, P1), (300, P2)]),
}


@pytest.mark.parametrize('case', sorted(CASES))
def test_flash_store_matches_model(case):
    mem, sched = CASES[case]
    loads, end, out, ready = run(f'tb_flash_store_{case}', mem, sched)
    assert 60 <= ready <= 90, ready
    want_loads, want_mem, writes, erases = model(mem, sched, ready)
    programs, erased, dirty, blocked, err, seq = end
    assert loads == want_loads, (loads, want_loads)
    assert (programs, erased, dirty, blocked, err) == (writes, erases, 0, 0, 0), end
    assert out == want_mem
    if case == 'empty':
        assert writes == 3 and erases == 1, 'P2, P3 and P1 stood still; the quick ones did not'
        loads2, end2, out2, _ = run('tb_flash_store_restart', out, [(0, P2)], end_ms=400)
        assert loads2 == [(P1, 3)] and end2[:2] == (0, 0) and out2 == out, 'the restart loads the last save, writes nothing'
    if case == 'bad_newest':
        assert loads == [(P2, 13)] and erases == 1 and out[4096:4096 + 16] == ref.record(14, P3)
    if case == 'full_sector':
        assert loads == [(P2, 256)] and erases == 1 and out[4096:4096 + 16] == ref.record(257, P1)
    if case == 'seq_wrap':
        assert loads == [(P2, 1)] and writes == 0


@pytest.mark.parametrize('mutant', sorted(MUTANTS))
def test_flash_store_negative_control(mutant):
    case = {'no_crc': 'bad_newest', 'no_erase': 'full_sector', 'no_wait': 'empty', 'no_wp': 'empty'}[mutant]
    mem, sched = CASES[case]
    loads, end, out, ready = run(f'tb_flash_store_{mutant}', mem, sched, mutant=mutant)
    want_loads, want_mem, _, _ = model(mem, sched, ready)
    assert (loads, out) != (want_loads, want_mem), mutant
