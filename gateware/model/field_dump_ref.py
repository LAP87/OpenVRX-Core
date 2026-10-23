"""Reference model of the field dump's frames (rtl/field_dump.v).

    frame('D', 12, flags, data)  ->  A5 5A 'D' 00 0C flags 05 A0 <1440 data bytes> CRC_hi CRC_lo

CRC-16/CCITT-FALSE (polynomial 1021h, start FFFFh, no reflection, no final XOR) over the type byte through the
last data byte, computed bit by bit here (gateware/tools/fielddump.py has its own table-free copy; the test checks
one against the other through the simulated bytes). data: the 360 words of a line as the decoder sent the bytes,
Cb Y0 Cr Y1 ... (1440 bytes).
"""
LEN = 1440
F_FIELD, F_MISSING, F_END, F_MATCH = 1, 2, 4, 8


def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame(kind, line, flags, data=b''):
    body = bytes([ord(kind), line >> 8, line & 0xFF, flags, len(data) >> 8, len(data) & 0xFF]) + bytes(data)
    c = crc16(body)
    return b'\xA5\x5A' + body + bytes([c >> 8, c & 0xFF])


def line_bytes(line, field, seed=0):
    """A synthetic line: luma ramps that differ per line and field, chroma that differs per line."""
    out = bytearray()
    for i in range(360):
        y0 = (16 + (line * 7 + i * 2 + field * 101 + seed) % 220)
        y1 = (16 + (line * 7 + i * 2 + 1 + field * 101 + seed) % 220)
        cb = (64 + (line * 3 + i + seed) % 128)
        cr = (192 - (line * 5 + i + field * 17 + seed) % 128)
        out += bytes([cb, y0, cr, y1])
    return bytes(out)


def words(data):
    """The 360 32-bit words {Y1, Cr, Y0, Cb} of a line (word_packer.v: byte 0 = Cb in bits 7:0)."""
    return [int.from_bytes(data[4 * i:4 * i + 4], 'little') for i in range(360)]


def expected(n_lines, lines, field, kind='D'):
    """The frames of a whole dump of lines 0 .. n_lines - 1 when field matching locks to `field` and every line in
    `lines` ({(line, field bit): data}) arrives within the timeout; the others are sent as missing."""
    out, match = b'', 0
    for ln in range(n_lines):
        if (ln, field) in lines:
            out += frame(kind, ln, match * F_MATCH | field, lines[(ln, field)])
            match = 1
        else:
            out += frame(kind, ln, match * F_MATCH | F_MISSING)
    return out + frame(kind, n_lines, match * F_MATCH | F_END)
