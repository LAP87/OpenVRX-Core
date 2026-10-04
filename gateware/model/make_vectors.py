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
