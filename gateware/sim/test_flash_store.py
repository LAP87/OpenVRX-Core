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
FFFFh; a restart on the image a run left (its last save loads). An erase of a full sector that
power loss stopped half-way (150 images, bits set at random): only the newest written record
loads; a record outside what the menu can set does not load. The HDMI range bit (2026-10-18):
saved and loaded, and a record from before it reads as full range.

Negative controls, each disagrees with the model: a copy that does not check the CRC, one that
checks magic and CRC only (no zero count: a half-erased record loads), one without the range
check (band 7 loads), one that never erases,
one that writes at once instead of after SAVE_MS, one that never drives WP#.

Run: .venv/bin/python -m pytest -q gateware/sim/test_flash_store.py"""
import os
import random
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
    'no_crc': [("if (rec[0] == 8'hA5 && x_rx == crc && rec[13] == zc", "if (rec[0] == 8'hA5 && rec[13] == zc")],
    # the acceptance before 2026-10-14: magic and CRC only
    'no_zero_count': [("x_rx == crc && rec[13] == zc && rec[14] == 8'hFF\n                    && rec[3][7:5] <= 3'd5 && rec[3][1:0] != 2'd3",
                       "x_rx == crc")],
    'no_range': [("\n                    && rec[3][7:5] <= 3'd5 && rec[3][1:0] != 2'd3", "")],
    'no_erase': [("prog_phase <= !need_erase; st <= S_CRC;", "prog_phase <= 1'b1; st <= S_CRC;")],
    'no_wait': [("            else if (t != SAVE_MS * MS) t <= t + 1;\n", "")],
    'no_wp': [("if (pos[3:0] == 4'd15) begin pos <= 0; flash_wp_drive <= 1'b1;", "if (pos[3:0] == 4'd15) begin pos <= 0;")],
    # the save status (2026-10-19): dirty only while writing, dirty without the write in progress, stored never
    'dirty_late': [("dirty <= ready && (cur != saved || writing);", "dirty <= ready && writing;")],
    'dirty_not_writing': [("dirty <= ready && (cur != saved || writing);", "dirty <= ready && (cur != saved);")],
    'stored_never': [("if ((st == S_SCAN_END && have) || st == S_DONE) stored <= 1'b1;", "")],
}
STATUS_MUTANTS = ('dirty_late', 'dirty_not_writing', 'stored_never')


def run(name, mem, sched, end_ms=1500, mutant=None, status=False):
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
    if status:
        st = [tuple(int(x) for x in l.split()[1:]) for l in log.splitlines()
              if l.startswith('STATUS') and 'x' not in l]
        return loads, end, out, ready, st
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


def full_image():
    """Both sectors full: seq 1..256 in sector 0, 257..512 in sector 1 (the next save erases sector 0)."""
    rng = random.Random(14)
    mem = bytearray()
    for s in range(512):
        mn_a, mn_b = rng.randrange(8000), rng.randrange(8000)
        mem += ref.record(s + 1, ref.payload(rng.randrange(6), rng.randrange(8), rng.randrange(3), rng.randrange(2),
                                             rng.randrange(2), mn_a, mn_a + rng.randrange(400, 20000),
                                             mn_b, mn_b + rng.randrange(400, 20000)))
    return bytes(mem)


def half_erased(mem, p, rng):
    """Sector 0 after an erase that stopped: every 0 bit set with probability p (an assumed model;
    erasing only sets bits)."""
    out = bytearray(mem)
    for i in range(4096):
        b = out[i]
        for k in range(8):
            if not b >> k & 1 and rng.random() < p:
                b |= 1 << k
        out[i] = b
    return bytes(out)


def scan_crc_only(mem):
    """The newest record by magic and CRC alone (the acceptance before 2026-10-14)."""
    best = None
    for s in range(ref.SLOTS):
        r = mem[16 * s:16 * s + 16]
        if r[0] == 0xA5 and ref.crc8(r[:15]) == r[15]:
            seq = r[1] << 8 | r[2]
            if best is None or ref.newer(seq, best[0]):
                best = (seq, bytes(r[3:13]))
    return best


def interrupted_erase_images(n=150):
    rng = random.Random(7)
    full = full_image()
    return full, [half_erased(full, p, rng) for p in (0.05, 0.1, 0.2) for _ in range(n // 3)]


def test_interrupted_erase_loads_only_written_records():
    """Review 2026-10-14, FL-1. Power fails while the 513th save erases sector 0 (seq 1..256): 150
    half-erased images. The scan must load the newest real record, seq 512 in sector 1, every time
    (model), and the RTL must do so on the images where magic and CRC alone take a record that was
    never written (model-level negative control: there are such images)."""
    full, images = interrupted_erase_images()
    newest = (full[16 * 511 + 3:16 * 511 + 13], 512)
    for mem in images:
        pay, seq, nxt, erase = ref.scan(mem)
        assert (pay, seq) == newest and (nxt, erase) == (0, True), 'the next save erases sector 0 again'
    fooled = [m for m in images if scan_crc_only(m) != (512, newest[0])]
    assert len(fooled) >= 5, len(fooled)
    for k, mem in enumerate(fooled[:2]):
        loads, end, out, ready = run(f'tb_flash_store_half_erased{k}', mem, [], end_ms=300)
        assert loads == [newest], loads


P_LTD = ref.payload(3, 3, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0, hdmi_ltd=1)     # P1 with HDMI LTD
OLD_P2 = bytes.fromhex('9dc00fa02ee012c03200')    # P2 as the payload was laid out before the HDMI bit


def test_hdmi_bit_is_saved_and_old_records_read_full():
    """The HDMI range (2026-10-18) is bit 5 of payload byte 1, one of the six bits that were 0. A record
    of the layout before it (literal bytes) reads as full range and loads unchanged; a change to LTD is
    saved where the model puts it (the whole image byte for byte) and loads after a restart. This module
    stores the payload whole; where the bit goes in it is the M6 top's wiring, checked with negative
    controls in sim/test_m6_settings.py."""
    assert P2 == OLD_P2 and ref.settings(OLD_P2)['hdmi_ltd'] == 0, 'old records read as full range'
    assert P_LTD[1] == 0x20 and ref.settings(P_LTD) == dict(ref.settings(P1), hdmi_ltd=1)
    loads, end, out, ready = run('tb_flash_store_old_record', image([(0, 41, OLD_P2, True)]), [], end_ms=300)
    assert loads == [(OLD_P2, 41)] and end[:2] == (0, 0), (loads, end)
    sched = [(0, P1), (200, P_LTD)]
    loads, end, out, ready = run('tb_flash_store_hdmi', EMPTY, sched)
    want_loads, want_mem, writes, erases = model(EMPTY, sched, ready)
    assert (loads, writes, erases) == ([], 1, 1) and end[:2] == (1, 1) and out == want_mem, (loads, end)
    assert out[:16] == ref.record(1, P_LTD)
    loads, end, _, _ = run('tb_flash_store_hdmi_restart', out, [(0, P1)], end_ms=400)
    assert loads == [(P_LTD, 1)] and end[:2] == (0, 0), (loads, end)
    assert ref.settings(loads[0][0])['hdmi_ltd'] == 1


GOOD = ref.payload(3, 3, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0)
BAND7 = image([(0, 19, GOOD, True), (1, 20, ref.payload(7, 1, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0), True)])


def test_record_outside_the_menu_is_not_loaded():
    """A record with right magic, Z and CRC but band 7 (the menu has bands 0..5) newer than a good
    one: the good one loads (model and RTL). Before 2026-10-14 band 7 loaded and the RX5808 got the
    empty table entry (synthesiser word 0)."""
    assert ref.scan(BAND7)[:2] == (GOOD, 19)
    loads, end, out, ready = run('tb_flash_store_band7', BAND7, [], end_ms=300)
    assert loads == [(GOOD, 19)], loads


def status_states(st):
    """The (t_us, dirty, stored) states that last at least 50 us (the clocks between a load and the
    menu taking it, and the clock between stored rising and dirty falling, are dropped), merged."""
    kept = [(t, d, s) for k, (t, d, s) in enumerate(st) if k + 1 == len(st) or st[k + 1][0] - t >= 50]
    out, state = [], (0, 0)
    for t, d, s in kept:
        if (d, s) != state:
            out.append((t, d, s))
            state = (d, s)
    return out


def check_status(st, sched, ready, loaded):
    """The save status against the schedule: stored from the start when a record loaded, else from
    the first write (and then while the write still counts as dirty); dirty within 2 ms of every
    standing change and for at least SAVE_MS, never otherwise."""
    rises, falls, stored_at, d_prev = [], [], None, 0
    for t, d, s in status_states(st):
        if d and not d_prev:
            rises.append(t)
        if d_prev and not d:
            falls.append(t)
        d_prev = d
        if s and stored_at is None:
            stored_at = t
    changes = [t for t, _ in sched if t > ready]
    assert len(rises) == len(changes) == len(falls), (rises, falls, changes)
    for t_ms, rise, fall in zip(changes, rises, falls):
        assert 0 <= rise - t_ms * 1000 <= 2000, (t_ms, rise)
        assert fall - rise >= SAVE_MS * 1000, (rise, fall)
    if loaded:
        assert stored_at is not None and stored_at <= (ready + 1) * 1000, (stored_at, ready)
    else:
        assert (stored_at is None) == (not changes), (stored_at, changes)
        if changes:
            assert stored_at > rises[0]
            first = next(c for c in st if c[2] == 1)                      # the raw print: the S_DONE clock
            assert first[1] == 1, 'stored rises while the write still counts as dirty'


STATUS_CASES = {
    'empty': (EMPTY, [(0, P1), (300, P2), (700, P3)], False),
    'record': (image([(0, 7, P2, True)]), [(0, P1), (300, P3)], True),
    'unchanged': (image([(0, 7, P2, True)]), [(0, P1)], True),
}


@pytest.mark.parametrize('case', sorted(STATUS_CASES))
def test_save_status_follows_the_record(case):
    """dirty / stored (2026-10-19, the menu's SAVED / UNSAVED / DEFAULTS): with an empty flash
    nothing is stored until the first write; a change makes the settings dirty at once and the
    write SAVE_MS later clears it only after the read-back; a loaded record is stored from the start."""
    mem, sched, loaded = STATUS_CASES[case]
    loads, end, out, ready, st = run(f'tb_flash_store_status_{case}', mem, sched, end_ms=1100, status=True)
    assert end[4] == 0 and (len(loads) == 1) == loaded
    check_status(st, sched, ready, loaded)


@pytest.mark.parametrize('mutant', STATUS_MUTANTS)
def test_save_status_negative_control(mutant):
    case = 'record' if mutant == 'stored_never' else 'empty'
    mem, sched, loaded = STATUS_CASES[case]
    loads, end, out, ready, st = run(f'tb_flash_store_{mutant}', mem, sched, end_ms=1100, mutant=mutant, status=True)
    with pytest.raises(AssertionError):
        check_status(st, sched, ready, loaded)


@pytest.mark.parametrize('mutant', sorted(set(MUTANTS) - set(STATUS_MUTANTS)))
def test_flash_store_negative_control(mutant):
    if mutant == 'no_zero_count':
        full, images = interrupted_erase_images()
        mem = next(m for m in images if scan_crc_only(m) != (512, full[16 * 511 + 3:16 * 511 + 13]))
        loads, end, out, ready = run('tb_flash_store_no_zero_count', mem, [], end_ms=300, mutant=mutant)
        assert loads != [(full[16 * 511 + 3:16 * 511 + 13], 512)], 'without Z the half-erased record loads'
        return
    if mutant == 'no_range':
        loads, end, out, ready = run('tb_flash_store_no_range', BAND7, [], end_ms=300, mutant=mutant)
        assert loads == [(ref.payload(7, 1, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0), 20)], 'without the range check band 7 loads'
        return
    case = {'no_crc': 'bad_newest', 'no_erase': 'full_sector', 'no_wait': 'empty', 'no_wp': 'empty'}[mutant]
    mem, sched = CASES[case]
    loads, end, out, ready = run(f'tb_flash_store_{mutant}', mem, sched, mutant=mutant)
    want_loads, want_mem, _, _ = model(mem, sched, ready)
    assert (loads, out) != (want_loads, want_mem), mutant
