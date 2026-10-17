"""Reference for rtl/flash_store.v: the record format, what the start scan loads, and what the
two settings sectors hold after a save.

Two 4 KB sectors, 512 slots of 16 bytes: A5h, seq (2 bytes, MSB first), payload (10 bytes),
Z = the number of 0 bits in bytes 0..12, FFh, CRC-8 (poly 07h, init 0) over the first 15 bytes.
A record is valid when the magic, Z, the FFh and the CRC are right and the payload is a setting
the menu can make (band 0..5, mode 0..2). Z catches every error that goes one way: an erase that
power loss stopped half-way only sets bits, a program it stopped only leaves bits set, so the 0
bits of the data drop while Z can only grow (review 2026-10-14, FL-1; with CRC-8 alone such a
record passed in up to a quarter of the interrupted erases in a simple bit model). The valid
record with the newest seq (mod 2^16: a is newer than b if (a - b) mod 2^16 is 1..32767) is
loaded. A save goes in the slot after the newest record if that slot is in the same sector and
erased, else in slot 0 of the other sector after erasing it; with no valid record, in slot 0 of
sector 0 after erasing it.
"""

SECTOR = 4096
SLOTS = 512


def crc8(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def payload(band, ch, mode, low_lat, filter_vcr, min_a, max_a, min_b, max_b):
    """The 80-bit payload as 10 bytes."""
    return bytes([band << 5 | ch << 2 | mode, low_lat << 7 | filter_vcr << 6]) + b''.join(
        v.to_bytes(2, 'big') for v in (min_a, max_a, min_b, max_b))


def zeros(data):
    """Number of 0 bits."""
    return sum(8 - bin(b).count('1') for b in data)


def record(seq, pay):
    head = bytes([0xA5, seq >> 8 & 0xFF, seq & 0xFF]) + pay
    body = head + bytes([zeros(head), 0xFF])
    return body + bytes([crc8(body)])


def valid(r):
    """Magic, CRC, zero count, the FFh byte, and a payload the menu can make."""
    return (r[0] == 0xA5 and crc8(r[:15]) == r[15] and r[13] == zeros(r[:13]) and r[14] == 0xFF
            and r[3] >> 5 <= 5 and r[3] & 3 != 3)


def newer(a, b):
    d = (a - b) & 0xFFFF
    return 0 < d < 0x8000


def scan(mem):
    """(payload or None, seq, next slot, erase first) for the 8 KB of both sectors."""
    best = None
    for s in range(SLOTS):
        r = mem[16 * s:16 * s + 16]
        if valid(r):
            seq = r[1] << 8 | r[2]
            if best is None or newer(seq, best[1]):
                best = (s, seq, bytes(r[3:13]))
    if best is None:
        return None, 0, 0, True
    s, seq, pay = best
    if s % 256 != 255 and all(b == 0xFF for b in mem[16 * (s + 1):16 * (s + 2)]):
        return pay, seq, s + 1, False
    return pay, seq, (256 if s < 256 else 0), True


def save(mem, slot, erase, seq, pay):
    """The array after writing seq/pay at slot (erasing its sector first if asked). Programming
    clears bits only, as in the flash."""
    mem = bytearray(mem)
    if erase:
        base = (slot // 256) * SECTOR
        mem[base:base + SECTOR] = b'\xff' * SECTOR
    for i, b in enumerate(record(seq, pay)):
        mem[16 * slot + i] &= b
    nxt = slot + 1 if slot % 256 != 255 else (256 if slot < 256 else 0)
    return bytes(mem), nxt, slot % 256 == 255
