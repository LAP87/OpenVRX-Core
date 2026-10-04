#!/usr/bin/env python3
"""Log the puck's snow meter (m6_puck_proto UART, 115200 8N1) to CSV.

    python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_on --seconds 30 --out emi.csv
    python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_off --seconds 30 --out emi.csv   # appends
    python gateware/tools/snowlog.py --summary emi.csv

Line format from the FPGA (puck_ui.v):  S aaaaaa bbbbbb uaa ubb umm Bc ffff MOD
snow A, snow B (mean line HF energy over 1024 lines, ------ = no lines), % of mixer
decisions from A / B / blended, band+channel, MHz, mode. The Tang Nano 20K's
BL616 shows up as two ttyUSB ports; the UART is usually the second one.

Only compare runs with the same camera scene: the snow value also depends on the
picture content. Change one thing at a time (HDMI on/off, channel, distance, shield).
"""
import argparse
import csv
import os
import statistics
import sys
import termios
import time
from collections import defaultdict

FIELDS = ['time', 'label', 'snow_a', 'snow_b', 'use_a', 'use_b', 'use_mix', 'channel', 'mhz', 'mode']


def parse(line):
    p = line.split()
    if len(p) != 9 or p[0] != 'S':
        return None
    num = lambda s: None if s.startswith('-') else int(s)  # noqa: E731
    return {'snow_a': num(p[1]), 'snow_b': num(p[2]), 'use_a': int(p[3]), 'use_b': int(p[4]),
            'use_mix': int(p[5]), 'channel': p[6], 'mhz': int(p[7]), 'mode': p[8]}


def open_serial(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOCTTY)
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0                                   # iflag: raw
    attrs[1] = 0                                   # oflag
    attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
    attrs[3] = 0                                   # lflag: no echo/canonical
    attrs[4] = attrs[5] = termios.B115200
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 2                    # 0.2 s read timeout
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def log(args):
    fd = open_serial(args.port)
    new = not os.path.exists(args.out)
    end = time.time() + args.seconds
    buf, n = b'', 0
    with open(args.out, 'a', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while time.time() < end:
            buf += os.read(fd, 256)
            while b'\n' in buf:
                raw, buf = buf.split(b'\n', 1)
                rec = parse(raw.decode('ascii', 'replace').strip())
                if rec:
                    w.writerow({'time': f'{time.time():.3f}', 'label': args.label, **rec})
                    n += 1
    os.close(fd)
    print(f'{n} lines -> {args.out} ({args.label})')


def summary(path):
    rows = defaultdict(list)
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows[r['label']].append(r)
    print(f'{"label":16s} {"n":>5s} {"snowA med":>10s} {"snowB med":>10s} {"A%":>5s} {"B%":>5s} {"mix%":>5s}  channels')
    for label, rs in rows.items():
        med = lambda k: statistics.median([int(r[k]) for r in rs if r[k] not in ('', 'None')] or [0])  # noqa: E731
        chans = sorted({r['channel'] for r in rs})
        print(f'{label:16s} {len(rs):5d} {med("snow_a"):10.0f} {med("snow_b"):10.0f} '
              f'{med("use_a"):5.0f} {med("use_b"):5.0f} {med("use_mix"):5.0f}  {",".join(chans)}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('port', nargs='?')
    ap.add_argument('--label', default='run')
    ap.add_argument('--seconds', type=float, default=30)
    ap.add_argument('--out', default='snowlog.csv')
    ap.add_argument('--summary', metavar='CSV')
    a = ap.parse_args(argv)
    if a.summary:
        summary(a.summary)
    elif a.port:
        log(a)
    else:
        ap.error('give a serial port or --summary')
    return 0


if __name__ == '__main__':
    sys.exit(main())
