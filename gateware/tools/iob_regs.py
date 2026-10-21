#!/usr/bin/env python3
"""Registers that nextpnr packed into the I/O cells (IOLOGIC), from a routed netlist (build/<top>.pnr.json).

    python gateware/tools/iob_regs.py gateware/build/m2a_memtest.pnr.json            # list them
    python gateware/tools/iob_regs.py gateware/build/m2a_memtest.pnr.json --strict   # fail on CE / SET / RESET

Why: with IOREG=1 (--vopt ireg_in_iob / oreg_in_iob / ioreg_in_iob) every flop next to a pad goes
into the cell, including flops with a clock enable, a synchronous set or reset. The home bench
2026-10-20 received M2a's UART report (its txd flop packed into IOLOGICO with CE and SET) as 82-byte
lines with scrambled bits, while the same transmitter built without the option read 39 of 39 lines
right (hub docs/bench/UART_KLOCKPROV_2026-10-20.md). Whether the IOLOGIC flop honours CE / SET /
RESET on the silicon is what the bench decides; until then --strict names every such flop so that a
build can refuse them. A flop with CLK / D / Q only (like the button inputs) is not reported in
--strict mode.
"""
import argparse
import json
import sys
from collections import Counter

CONTROL = ('CE', 'SET', 'RESET', 'PRESET', 'CLEAR')


def iob_regs(pnr_json):
    """[(cell name, type, mode, connected ports)] for every IOLOGIC cell."""
    d = json.load(open(pnr_json))
    top = next(iter(d['modules'].values()))
    out = []
    for cname, c in top['cells'].items():
        if not c['type'].startswith('IOLOGIC') or c['type'] == 'IOLOGIC_DUMMY':
            continue
        ports = tuple(sorted(p for p, bits in c['connections'].items() if bits))
        params = c.get('parameters', {})
        mode = params.get('OUTMODE') or params.get('INMODE') or ''
        out.append((cname, c['type'], str(mode), ports))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('pnr_json')
    ap.add_argument('--strict', action='store_true', help='exit 1 when any IOB flop has CE, SET or RESET')
    a = ap.parse_args()
    regs = iob_regs(a.pnr_json)
    groups = Counter((t, m, p) for _, t, m, p in regs)
    for (t, m, p), n in groups.most_common():
        print(f'{n:4d} x {t} {m} {", ".join(p)}')
    bad = [(c, p) for c, t, m, p in regs if any(x in p for x in CONTROL)]
    print(f'{len(regs)} registers in I/O cells, {len(bad)} with CE / SET / RESET')
    if a.strict and bad:
        for c, p in bad:
            print(f'  {c}: {", ".join(p)}')
        sys.exit(1)


if __name__ == '__main__':
    main()
