#!/usr/bin/env python3
"""Receive a field dump from M6 (DEVCMD=1 bitstream, rtl/field_dump.v), check it and write PNGs.

    python gateware/tools/fielddump.py D --out decoder_a        # decoder A before the mixer
    python gateware/tools/fielddump.py F --out fieldstore       # the mixer's output as the field store takes it
    python gateware/tools/fielddump.py D --baud 921600 --out a  # a UART_BAUD=921600 build
    python gateware/tools/fielddump.py --from a.bin --out a     # decode a saved capture again

Sends the command byte, reads until the end frame (or --timeout), and writes <out>.bin (everything received),
<out>_y.png (luma, 720 x lines), <out>_rgb.png (BT.601 from the 4:2:2 samples) and <out>.json (lines received,
missing, CRC errors, field bit). Lines that are missing or failed their CRC are drawn in magenta in the colour
picture and mid-grey in the luma picture, and listed in the JSON. Log lines before and after the dump are skipped.
One line arrives per field period at best, so a whole field takes many fields: the picture is exact per line and
a snapshot only of a still source. Linux (termios) for the serial port; --from works anywhere.
"""
import argparse
import json
import os
import struct
import sys
import time
import zlib
from pathlib import Path

LEN = 1440
F_FIELD, F_MISSING, F_END, F_MATCH = 1, 2, 4, 8
DEFAULT_PORT = '/dev/serial/by-id/usb-SIPEED_USB_Debugger_2025030317-if01-port0'


def crc16(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE, the one field_dump.v appends (polynomial 1021h, start FFFFh)."""
    for b in data:
        x = (crc >> 8) ^ b
        x ^= x >> 4
        crc = ((crc << 8) ^ (x << 12) ^ (x << 5) ^ x) & 0xFFFF
    return crc


def parse(buf):
    """(frames, bad, rest): the frames with a correct CRC in `buf` as dicts, the count of frames whose CRC or
    header failed, and the unparsed tail (an incomplete frame). Text between frames is skipped."""
    frames, bad, i = [], 0, 0
    while True:
        j = buf.find(b'\xA5\x5A', i)
        if j < 0 or len(buf) - j < 8:
            return frames, bad, buf[j:] if j >= 0 else b''
        kind, n = buf[j + 2], (buf[j + 6] << 8) | buf[j + 7]
        if kind not in (ord('D'), ord('F')) or n not in (0, LEN):
            bad += 1
            i = j + 2
            continue
        end = j + 8 + n + 2
        if len(buf) < end:
            return frames, bad, buf[j:]
        body = buf[j + 2:j + 8 + n]
        if crc16(body) != (buf[end - 2] << 8 | buf[end - 1]):
            bad += 1
            i = j + 2
            continue
        flags = buf[j + 5]
        frames.append({'kind': chr(kind), 'line': (buf[j + 3] << 8) | buf[j + 4], 'flags': flags,
                       'field': flags & F_FIELD, 'missing': bool(flags & F_MISSING), 'end': bool(flags & F_END),
                       'data': bytes(buf[j + 8:j + 8 + n])})
        i = end


def assemble(frames):
    """{line: data} of the received lines, the missing line numbers, the number of lines asked for."""
    lines, missing, n = {}, [], 0
    for f in frames:
        if f['end']:
            n = f['line']
        elif f['missing']:
            missing.append(f['line'])
        else:
            lines[f['line']] = f['data']
    return lines, missing, n


def png(path, w, h, rgb_rows):
    raw = bytearray()
    for row in rgb_rows:
        raw += b'\x00' + bytes(row)

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def ycbcr_rgb(y, cb, cr):
    """BT.601 studio range (16-235 / 16-240) to 0-255 RGB, integer."""
    c, d, e = y - 16, cb - 128, cr - 128
    clip = lambda v: max(0, min(255, (v + 128) >> 8))  # noqa: E731
    return clip(298 * c + 409 * e), clip(298 * c - 100 * d - 208 * e), clip(298 * c + 516 * d)


def pictures(lines, n):
    """(luma rows, colour rows) as lists of RGB byte lists, 720 wide, one row per line 0..n-1."""
    rows_y, rows_c = [], []
    for ln in range(n):
        d = lines.get(ln)
        if d is None:
            rows_y.append([128] * (720 * 3))
            rows_c.append([255, 0, 255] * 720)
            continue
        ry, rc = [], []
        for i in range(360):
            cb, y0, cr, y1 = d[4 * i:4 * i + 4]
            ry += [y0] * 3 + [y1] * 3
            rc += [*ycbcr_rgb(y0, cb, cr), *ycbcr_rgb(y1, cb, cr)]
        rows_y.append(ry)
        rows_c.append(rc)
    return rows_y, rows_c


def write(buf, out):
    frames, bad, _ = parse(buf)
    lines, missing, n = assemble(frames)
    n = n or (max(list(lines) + missing) + 1 if (lines or missing) else 0)
    kinds = sorted({f['kind'] for f in frames})
    fields = sorted({f['field'] for f in frames if not f['missing'] and not f['end']})
    summary = {'kind': kinds, 'lines_asked': n, 'lines': len(lines), 'missing': missing, 'crc_errors': bad,
               'field_bits': fields, 'complete': any(f['end'] for f in frames)}
    first = [ln for ln in range(n) if ln in lines]
    summary['first_line'] = first[0] if first else None
    summary['last_line'] = first[-1] if first else None
    if n and lines:
        ry, rc = pictures(lines, n)
        png(f'{out}_y.png', 720, n, ry)
        png(f'{out}_rgb.png', 720, n, rc)
        summary['png'] = [f'{out}_y.png', f'{out}_rgb.png']
    Path(f'{out}.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def receive(port, baud, cmd, timeout):
    import termios
    rates = {115200: termios.B115200, 230400: termios.B230400, 460800: termios.B460800, 921600: termios.B921600,
             1000000: termios.B1000000}
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(fd)
    a[0] = a[1] = a[3] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | (a[2] & termios.HUPCL)
    a[4] = a[5] = rates[baud]
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 2
    termios.tcsetattr(fd, termios.TCSANOW, a)
    buf = b''
    try:
        os.write(fd, cmd.encode('ascii'))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            buf += os.read(fd, 65536)
            frames, _, _ = parse(buf)
            if any(f['end'] for f in frames):
                break
    finally:
        os.close(fd)
    return buf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('which', nargs='?', choices=['D', 'F'], help='D decoder A, F field store input')
    ap.add_argument('--out', required=True, help='path prefix for .bin, .json and the PNGs')
    ap.add_argument('--from', dest='src', help='decode this saved capture instead of the port')
    ap.add_argument('--port', default=DEFAULT_PORT)
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--timeout', type=float, default=180)
    a = ap.parse_args(argv)
    if a.src:
        buf = Path(a.src).read_bytes()
    elif a.which:
        buf = receive(a.port, a.baud, a.which, a.timeout)
        Path(f'{a.out}.bin').write_bytes(buf)
    else:
        ap.error('give D or F, or --from')
    s = write(buf, a.out)
    print(json.dumps(s))
    return 0 if s['complete'] and not s['crc_errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
