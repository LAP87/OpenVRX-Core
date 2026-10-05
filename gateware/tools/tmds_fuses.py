#!/usr/bin/env python3
"""Do built bitstreams pack the TMDS output pairs alike?

Apicula 0.32 gives every IOB of an I/O bank the BANK_VCCIO of the bank's first
single-ended output or inout (gowin_pack.py, second IO pass), and 1.2 V when
the bank has none. A single-ended output in bank 4 or 5 (pins 25-42 of the Tang
Nano 20K) therefore changes the IOB fuses of the true-LVDS TMDS pairs on pins
33-40. M0 has no such output; it is the first bitstream to be tried on a
screen, so it is the reference:

    gateware/build.sh m0_testpattern
    gateware/build.sh m4_dual_mix
    gateware/build.sh m6_puck_proto
    .venv/bin/python gateware/tools/tmds_fuses.py                  # M4 and M6 against M0
    .venv/bin/python gateware/tools/tmds_fuses.py m0_testpattern m2_moneagle_color

Reads gateware/build/<top>.fs and <top>.pnr.json. Only fuses that belong to an
IOBA/IOBB attribute are compared (routing excluded), as in
tools/test_lvds_bank_inputs.py. Exit status 1 when a pair differs.
tools/test_tmds_bank_outputs.py guards the pin plan with the same functions.
"""
import json
import os
import sys
from pathlib import Path

GW = Path(__file__).resolve().parent.parent
BUILD = GW / 'build'
DEVICE = 'GW2A-18C'


def load_db():
    from apycula import chipdb
    return chipdb.load_chipdb(os.path.join(os.path.dirname(chipdb.__file__), f'{DEVICE}.msgpack.xz'))


def tile_bitmaps(db, fs_path):
    from apycula import chipdb
    from apycula.bslib import read_bitstream
    return chipdb.tile_bitmap(db, read_bitstream(str(fs_path))[0])


def iob_fuses(db, bitmaps, rc):
    """The fuses set in tile rc = (row, column) that configure its two IOBs."""
    ttyp = db[rc].ttyp
    mask = {f for tbl in ('IOBA', 'IOBB') for fuses in db.longval[ttyp][tbl].values()
            for f in fuses if isinstance(f, tuple)}
    return {(r, c) for r, line in enumerate(bitmaps[rc]) for c, v in enumerate(line) if v} & mask


def io_tiles(pnr_json, match='tmds'):
    """{(row, column): [cell names]} of the placed I/O cells whose name contains `match`."""
    with open(pnr_json) as fh:
        cells = next(iter(json.load(fh)['modules'].values()))['cells']
    tiles = {}
    for name, cell in cells.items():
        bel = cell.get('attributes', {}).get('NEXTPNR_BEL', '')
        if 'IOB' in bel and match in name:
            x, y = bel.split('/')[0][1:].split('Y')
            tiles.setdefault((int(y), int(x)), []).append(name)
    return tiles


def compare(ref, others, build=BUILD):
    """Per TMDS pair of `ref`: (tile, cell names, fuses set in ref, {top: (only in ref, only in top)})."""
    db = load_db()
    bitmaps = {top: tile_bitmaps(db, build / f'{top}.fs') for top in (ref, *others)}
    rows = []
    for rc, names in sorted(io_tiles(build / f'{ref}.pnr.json').items()):
        base = iob_fuses(db, bitmaps[ref], rc)
        diff = {}
        for top in others:
            here = iob_fuses(db, bitmaps[top], rc)
            diff[top] = (sorted(base - here), sorted(here - base))
        rows.append((rc, sorted(names), len(base), diff))
    return rows


def main(argv):
    ref, others = (argv[0], argv[1:]) if len(argv) >= 2 else ('m0_testpattern', ['m4_dual_mix', 'm6_puck_proto'])
    missing = [top for top in (ref, *others) if not (BUILD / f'{top}.fs').exists()]
    if missing:
        sys.exit(f'not built: {", ".join(missing)} (gateware/build.sh <top>)')
    differs = False
    for rc, names, n, diff in compare(ref, others):
        print(f'tile {rc} {names[0]}: {n} IOB fuses set in {ref}')
        for top, (only_ref, only_top) in diff.items():
            if only_ref or only_top:
                differs = True
                print(f'    {top}: DIFFERS, only in {ref} {only_ref}, only in {top} {only_top}')
            else:
                print(f'    {top}: same')
    return int(differs)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
