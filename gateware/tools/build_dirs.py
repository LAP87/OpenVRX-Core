"""Audit: does every test have a build directory and a cocotb results file of its own?

Reads the traces run_suite.py collected (one per process, written by
suite_trace.py) and lists, per test, the build directories and results files its
subprocesses used. A directory or file that two tests use is a duplicate: run in
parallel, the second build overwrites the first one's simulator or results.

    .venv/bin/python gateware/tools/build_dirs.py [--list] [OUT]

OUT defaults to gateware/sim/build/suite. Exit status 1 when there is a duplicate.
"""
import argparse
import json
import sys
from pathlib import Path

GW = Path(__file__).resolve().parent.parent
DEFAULT_OUT = GW / 'sim' / 'build' / 'suite'
COLLECT = '<collect>'


def load(out):
    """{test: [claim, ...]} from the newest record of each unit in OUT/results.jsonl."""
    units = {}
    path = Path(out) / 'results.jsonl'
    for line in path.read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            units[rec['unit']] = rec
    claims = {}
    for rec in units.values():
        for test in rec.get('tests', {}):
            claims.setdefault(test, set())
        for test, cl in rec.get('claims', {}).items():
            if test == COLLECT:
                test = f'{COLLECT} {rec["unit"]}'
            claims.setdefault(test, set()).update(cl)
    return claims


def duplicates(claims):
    """{claim: [tests]} for every claim held by more than one test."""
    holders = {}
    for test, cl in claims.items():
        for c in cl:
            holders.setdefault(c, set()).add(test)
    return {c: sorted(t) for c, t in sorted(holders.items()) if len(t) > 1}


def report(claims, listing=False, file=sys.stdout):
    dup = duplicates(claims)
    if listing:
        for test in sorted(claims):
            print(test, file=file)
            for c in sorted(claims[test]) or ['(none)']:
                print(f'    {c}{"   <-- shared" if c in dup else ""}', file=file)
    n_dirs = len({c for cl in claims.values() for c in cl if c.startswith('dir:')})
    n_files = len({c for cl in claims.values() for c in cl if c.startswith('file:')})
    print(f'build-dir audit: {len(claims)} tests, {n_dirs} build directories, '
          f'{n_files} results files, {len(dup)} shared', file=file)
    for c, tests in dup.items():
        print(f'  SHARED {c}', file=file)
        for t in tests:
            print(f'      {t}', file=file)
    return dup


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out', nargs='?', default=DEFAULT_OUT)
    ap.add_argument('--list', action='store_true', help='print every test with its claims')
    a = ap.parse_args(argv)
    return 1 if report(load(a.out), a.list) else 0


if __name__ == '__main__':
    sys.exit(main())
