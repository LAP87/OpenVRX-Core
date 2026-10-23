#!/usr/bin/env python3
"""Send development commands to M6 (a DEVCMD=1 bitstream, puck_ui.v) and read the receipt in the log.

    python gateware/tools/m6ctl.py L             # latency LOW; prints the first log line that shows it
    python gateware/tools/m6ctl.py B T m         # BUF, filter TV, mode MIX, one after the other
    python gateware/tools/m6ctl.py '?'           # status line, parsed
    python gateware/tools/m6ctl.py --port /dev/ttyUSB1 --baud 921600 V

Commands (one byte each; puck_ui.v has the list): B / L latency, T / V filter, m / a / b mode MIX / A / B,
H / h HOLD on / off, + / - channel, O / o / * OSD on / off / buttons, ? status line, D / F field dump.

A command counts as done when a log line arrives whose echo is that byte with the count one higher than in
the line before it was sent; for "?" when the status line arrives. Over usbipd the log comes in bursts, sometimes
half a minute late, hence the long default timeout. Output: one JSON object per command (the parsed line).
Linux only (termios); the port is opened without touching DTR/RTS after the open.
"""
import argparse
import json
import os
import re
import sys
import termios
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snowlog  # noqa: E402

COMMANDS = 'BLTVmabHh+-Oo*?DF'
DEFAULT_PORT = '/dev/serial/by-id/usb-SIPEED_USB_Debugger_2025030317-if01-port0'
BAUDS = {115200: termios.B115200, 230400: termios.B230400, 460800: termios.B460800, 921600: termios.B921600,
         1000000: termios.B1000000}
Q_RE = re.compile(r'^Q A (?P<a>(?:5C|5D|NA|--) (?:[0-9A-F]{4}|----) (?:[0-9A-F]{2}|--) [0-9A-F]{2}) '
                  r'B (?P<b>(?:5C|5D|NA|--) (?:[0-9A-F]{4}|----) (?:[0-9A-F]{2}|--) [0-9A-F]{2}) '
                  r'T (?P<t>[-0-7]) (?P<build>[HD]) (?P<first>5C|5D) (?P<baud>\d{7})$')


def parse_q(line):
    """The status line as a dict, or None."""
    m = Q_RE.match(line.strip())
    if not m:
        return None

    def dec(s):
        addr, st, misc, ri = s.split()
        return {'addr': addr if addr in ('5C', '5D') else None, 'answer': addr, 'st': None if st == '----' else st,
                'r88': None if st == '----' else int(st[2:], 16), 'r89': None if st == '----' else int(st[:2], 16),
                'r03': None if misc == '--' else int(misc, 16), 'reinit': int(ri, 16)}
    return {'A': dec(m['a']), 'B': dec(m['b']), 'sdram': None if m['t'] == '-' else int(m['t']),
            'hdmi_build': m['build'] == 'H', 'tvp_first': m['first'], 'baud': int(m['baud'])}


def open_port(path, baud):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    a = termios.tcgetattr(fd)
    a[0] = 0
    a[1] = 0
    a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL | (a[2] & termios.HUPCL)
    a[3] = 0
    a[4] = a[5] = BAUDS[baud]
    a[6][termios.VMIN] = 0
    a[6][termios.VTIME] = 2
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd


class Lines:
    def __init__(self, fd):
        self.fd, self.buf = fd, b''

    def next(self, deadline):
        while time.monotonic() < deadline:
            if b'\n' in self.buf:
                raw, self.buf = self.buf.split(b'\n', 1)
                return raw.decode('ascii', 'replace').strip()
            self.buf += os.read(self.fd, 4096)
        return None


def last_count(lines, deadline):
    """The command count of the next DEVCMD log line, or None."""
    while (text := lines.next(deadline)) is not None:
        rec = snowlog.parse(text)
        if rec and 'cmd_count' in rec:
            return rec['cmd_count']
        if rec:
            raise SystemExit('the log line has no command echo: not a DEVCMD=1 bitstream')
    return None


def send(fd, lines, cmd, timeout):
    deadline = time.monotonic() + timeout
    base = last_count(lines, deadline)
    if base is None:
        return {'cmd': cmd, 'ok': False, 'error': 'no log line'}
    os.write(fd, cmd.encode('ascii'))
    want = (base + 1) & 0xFF
    while (text := lines.next(deadline)) is not None:
        if cmd == '?' and text.startswith('Q '):
            q = parse_q(text)
            if q:
                return {'cmd': cmd, 'ok': True, 'raw': text, 'status': q}
        rec = snowlog.parse(text)
        if rec and rec.get('cmd_count') == want and rec.get('cmd') == ord(cmd) and cmd != '?':
            return {'cmd': cmd, 'ok': True, 'raw': text, 'line': rec}
        if rec and rec.get('cmd_count') not in (None, base, want):
            return {'cmd': cmd, 'ok': False, 'error': f"count went from {base} to {rec['cmd_count']}", 'raw': text}
    return {'cmd': cmd, 'ok': False, 'error': f'no receipt within {timeout} s'}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('commands', nargs='+', help='one or more command characters')
    ap.add_argument('--port', default=DEFAULT_PORT)
    ap.add_argument('--baud', type=int, default=115200, choices=sorted(BAUDS))
    ap.add_argument('--timeout', type=float, default=40)
    a = ap.parse_args(argv)
    cmds = [c for group in a.commands for c in group]
    bad = [c for c in cmds if c not in COMMANDS]
    if bad:
        ap.error(f'not a command: {"".join(bad)} (commands: {COMMANDS})')
    fd = open_port(a.port, a.baud)
    lines = Lines(fd)
    ok = True
    try:
        for c in cmds:
            r = send(fd, lines, c, a.timeout)
            ok &= r['ok']
            print(json.dumps(r))
    finally:
        os.close(fd)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
