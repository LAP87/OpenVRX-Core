#!/usr/bin/env python3
"""Log the puck's snow meter (m6_puck_proto UART, 115200 8N1) to CSV.

    python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_on --seconds 30 --out emi.csv
    python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_off --seconds 30 --out emi.csv   # appends
    python gateware/tools/snowlog.py --summary emi.csv
On Windows the port is COM5 and the like (set up with the `mode` command; not tried on a real port yet).

Line format from the FPGA (puck_ui.v):  S aaaaaa bbbbbb nnnnnn mmmmmm uaa ubb umm Bc ffff MOD o
snow A, snow B (mean line HF energy over 1024 lines, ------ = no lines), noise A, noise B
(luma samples outside 16..235 in the last 1024 lines), % of mixer decisions from A / B /
blended, band+channel, MHz, mode, and "!" once the mixer has dropped a line since reset
(else "-"). Lines from older bitstreams (no noise values, possibly no "!"/"-") are read
too; their noise columns stay empty. The Tang Nano 20K's BL616 shows up as two ttyUSB
ports; the UART is usually the second one.

Only compare runs with the same camera scene: the snow value also depends on the
picture content. The noise value should not, but that is not shown on a real signal yet.
Change one thing at a time (HDMI on/off, channel, distance, shield).
"""
import argparse
import csv
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict

FIELDS = ['time', 'label', 'snow_a', 'snow_b', 'noise_a', 'noise_b', 'use_a', 'use_b', 'use_mix', 'channel',
          'mhz', 'mode', 'dropped']


def parse(line):
    """A log line as a dict, or None for anything else (also a line damaged on the way)."""
    p = line.split()
    if len(p) == 12:                                   # current format, with the noise values
        noise, p = p[3:5], p[:3] + p[5:]
    elif len(p) in (9, 10):                            # older bitstreams: no noise values
        noise = None
    else:
        return None
    if p[0] != 'S' or (len(p) == 10 and p[9] not in '-!'):
        return None
    num = lambda s: None if s.startswith('-') else int(s)  # noqa: E731
    try:
        return {'snow_a': num(p[1]), 'snow_b': num(p[2]),
                'noise_a': num(noise[0]) if noise else None, 'noise_b': num(noise[1]) if noise else None,
                'use_a': int(p[3]), 'use_b': int(p[4]), 'use_mix': int(p[5]), 'channel': p[6], 'mhz': int(p[7]),
                'mode': p[8], 'dropped': int(len(p) == 10 and p[9] == '!')}
    except ValueError:
        return None


def open_serial(path):
    if os.name == 'nt':
        return open_serial_windows(path)
    import termios                                 # Unix only
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


def open_serial_windows(path):
    """COM port at 115200 8N1 with a 0.2 s read timeout."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    name = path.upper().replace('\\\\.\\', '')
    subprocess.run(['mode', f'{name}:', 'BAUD=115200', 'PARITY=N', 'DATA=8', 'STOP=1'], shell=True, check=True,
                   stdout=subprocess.DEVNULL)
    fd = os.open('\\\\.\\' + name, os.O_RDONLY | os.O_BINARY)

    class Timeouts(ctypes.Structure):               # COMMTIMEOUTS: return what has arrived after 200 ms
        _fields_ = [(n, wintypes.DWORD) for n in ('interval', 'read_mul', 'read_const', 'write_mul', 'write_const')]
    ctypes.windll.kernel32.SetCommTimeouts(wintypes.HANDLE(msvcrt.get_osfhandle(fd)),
                                           ctypes.byref(Timeouts(0xFFFFFFFF, 0, 200, 0, 0)))
    return fd


def log(args):
    new = not os.path.exists(args.out)
    if not new:
        with open(args.out, newline='') as fh:
            header = next(csv.reader(fh), None)
        if header != FIELDS:
            sys.exit(f'{args.out} has other columns ({",".join(header or [])}); write to a new file')
    fd = open_serial(args.port)
    end = time.time() + args.seconds
    buf, n, bad = b'', 0, 0
    with open(args.out, 'a', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        while time.time() < end:
            buf += os.read(fd, 256)
            while b'\n' in buf:
                raw, buf = buf.split(b'\n', 1)
                text = raw.decode('ascii', 'replace').strip()
                rec = parse(text)
                if rec:
                    w.writerow({'time': f'{time.time():.3f}', 'label': args.label, **rec})
                    n += 1
                elif text.startswith('S'):
                    bad += 1
    os.close(fd)
    print(f'{n} lines -> {args.out} ({args.label})' + (f', {bad} damaged lines skipped' if bad else ''))


def summary(path):
    rows = defaultdict(list)
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows[r['label']].append(r)
    print(f'{"label":16s} {"n":>5s} {"snowA med":>10s} {"snowB med":>10s} {"noiseA med":>10s} {"noiseB med":>10s} '
          f'{"A%":>5s} {"B%":>5s} {"mix%":>5s}  channels   (! = the mixer dropped lines)')
    for label, rs in rows.items():
        med = lambda k: statistics.median([int(r[k]) for r in rs if r.get(k) not in (None, '', 'None')] or [0])  # noqa: E731
        chans = sorted({r['channel'] for r in rs})
        print(f'{label:16s} {len(rs):5d} {med("snow_a"):10.0f} {med("snow_b"):10.0f} '
              f'{med("noise_a"):10.0f} {med("noise_b"):10.0f} '
              f'{med("use_a"):5.0f} {med("use_b"):5.0f} {med("use_mix"):5.0f}  {",".join(chans)}'
              + (' !' if any(r.get('dropped') == '1' for r in rs) else ''))


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
