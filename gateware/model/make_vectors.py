#!/usr/bin/env python3
"""Write BT.656 test vectors + expected per-line records for HDL testbenches.

    python make_vectors.py --out ../vectors

Produces <case>.hex (one byte per line, for $readmemh / textio) and
<case>.expected.json (records the HDL `bt656_rx` + `line_metrics` must report).
"""
import argparse
import json
import random
from pathlib import Path

import bt656


def ramp(line, x):
    return 16 + (line * 5 + x) % 220


def cases():
    yield 'pal_clean_frame', bt656.frame_bytes('pal', ramp) + bt656.line_bytes('pal', 1)
    yield 'ntsc_clean_frame', bt656.frame_bytes('ntsc', ramp) + bt656.line_bytes('ntsc', 1)

    rng = random.Random(1)
    lines = [bytearray(bt656.line_bytes('pal', n, bytes(b for x in range(720) for b in (0x80, ramp(n, x)))))
             for n in range(100, 110)]
    sav = lines[2].index(bytes([0xFF, 0, 0]), 4) + 3
    lines[2][sav] ^= 0x10                      # single-bit error in a timing code
    del lines[4][-500:-380]                    # truncated active video (weak signal)
    for i in range(len(lines[6]) - 1440, len(lines[6])):
        if i % 2:                              # snow on luma, keep reserved codes out
            lines[6][i] = max(1, min(254, lines[6][i] + rng.randint(-60, 60)))
    yield 'pal_faults', b''.join(lines) + bt656.line_bytes('pal', 110)

    # undecodable timing codes: line 101's SAV and the EAV that ends line 104 (it starts
    # line 105); the line numbers after them must not shift
    bad = next(b for b, v in bt656.XY_TABLE.items() if v[3] == 'bad' and b not in (0, 255))
    lines = [bytearray(bt656.line_bytes('pal', n, bytes(b for x in range(720) for b in (0x80, ramp(n, x)))))
             for n in range(100, 108)]
    lines[1][lines[1].index(bytes([0xFF, 0, 0]), 4) + 3] = bad
    lines[5][3] = bad
    yield 'pal_lost_codes', b''.join(lines) + bt656.line_bytes('pal', 108)

    # non-interlaced source: three short fields whose F bit never changes (a TVP5150AM1 forces
    # F = 1 for such video); the numbering must restart after every vertical blanking
    data = bytearray()
    for fld in range(3):
        for i in range(3 + 6):
            v = 1 if i < 3 else 0
            act = bt656.blanking(1440) if v else bytes(b for x in range(720) for b in (0x80, ramp(fld * 9 + i, x)))
            data += (bytes([0xFF, 0, 0, bt656.xy(1, v, 1)]) + bt656.blanking(1716 - 1440 - 8)
                     + bytes([0xFF, 0, 0, bt656.xy(1, v, 0)]) + act)
    yield 'f_stuck_fields', bytes(data) + bytes([0xFF, 0, 0, bt656.xy(1, 1, 1)]) + bt656.blanking(1716 - 1440 - 8)

    # lines that run on: the next line's EAV and SAV are lost (blanking in their place), so the
    # active part goes on to the following EAV. NTSC lines 30-44: line 31 runs on over one line
    # (3156 active bytes), line 34 over three (6588, past 4096), line 39 over one line that is
    # 340 bytes long (3496: its bytes from 2048 on are 1448, a whole line of words to a counter
    # that wraps). The active count saturates at 2047; the first 1440 bytes are the line's own.
    lines = [bytearray(bt656.line_bytes('ntsc', n, bytes(b for x in range(720) for b in (0x80, ramp(n, x)))))
             for n in range(30, 45)]
    blank4 = bytes(bt656.blanking(4))
    for i, extra in ((2, 0), (5, 0), (6, 0), (7, 0), (10, 340)):
        lines[i][0:4] = blank4                                  # EAV
        lines[i][272:276] = blank4                              # SAV (after 268 blanking bytes)
        lines[i][4:4] = bt656.blanking(extra)
    yield 'ntsc_run_on_lines', b''.join(lines) + bt656.line_bytes('ntsc', 45)

    # a line that starts again: NTSC lines 20-27, line 22 has luma spikes in its first 1400 bytes
    # and an extra SAV 1435 bytes into its active part, so the line it starts has one active byte
    # and no whole word before the EAV (noise_stats.v must count 0 for it, not line 22's spikes)
    lines = [bytearray(bt656.line_bytes('ntsc', n, bytes(b for x in range(720) for b in (0x80, ramp(n, x)))))
             for n in range(20, 28)]
    act = len(lines[2]) - 1440
    for x in range(10, 700, 37):
        lines[2][act + 2 * x + 1] = 1 if x % 2 else 254
    lines[2][act + 1435:act + 1439] = bytes([0xFF, 0, 0, bt656.xy(0, 0, 0)])
    yield 'ntsc_restart', b''.join(lines) + bt656.line_bytes('ntsc', 28)

    # impulse noise for the out-of-range luma count (noise_stats.v): NTSC lines 16-56 (vertical
    # blanking, then 37 active lines from line 0). Luma spikes on both sides of 16..235, with the
    # boundary values 15/16 and 235/236; chroma spikes outside 16..240 that must not be counted;
    # one run of 40 clipped samples; every fifth active line clean.
    rng = random.Random(2)
    data = bytearray()
    for n in range(16, 57):
        act = bytearray(b for x in range(720) for b in (0x80, ramp(n, x)))
        k = n - 20                                 # active line number
        if k >= 0 and k % 5 != 4:
            for _ in range(rng.randint(1, 12)):
                act[2 * rng.randrange(720) + 1] = rng.choice((1, 2, 15, 16, 17, 128, 234, 235, 236, 254))
            for _ in range(rng.randint(1, 6)):
                act[2 * rng.randrange(720)] = rng.choice((1, 15, 241, 254))
        if k == 7:
            act[2 * 300 + 1:2 * 340 + 1:2] = bytes([240] * 40)
        data += bt656.line_bytes('ntsc', n, bytes(act))
    yield 'ntsc_spikes', bytes(data) + bt656.line_bytes('ntsc', 57)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=Path(__file__).parent.parent / 'vectors')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, data in cases():
        bt656.write_hex(args.out / f'{name}.hex', data)
        recs = bt656.Receiver().feed(data)
        expected = [{k: v for k, v in vars(r).items() if k not in ('luma', 'active')} for r in recs]
        (args.out / f'{name}.expected.json').write_text(json.dumps(expected, indent=1))
        print(f'{name}: {len(data)} bytes, {len(recs)} active lines')


if __name__ == '__main__':
    main()
