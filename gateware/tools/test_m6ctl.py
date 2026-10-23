"""m6ctl.py against a pretend board on a pty: a command is done when the echo and the count say so.

The pretend board sends DEVCMD log lines built with model/m6_cmd_ref.py and applies each byte it reads with the
model; "?" gets the model's status line. Negative controls: a board that echoes without counting, and one that
never answers, both give ok = False.
"""
import os
import sys
import threading
import time
import tty
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / 'model'))
import m6_cmd_ref as ref  # noqa: E402
import m6ctl  # noqa: E402

pytestmark = pytest.mark.skipif(not hasattr(os, 'openpty'), reason='needs a pty')
BASE = 'S 012345 002345 000017 654321 040 034 025 {ch} {mhz} {mode:3s} {flt} F - -- 12000 04567 075 003 -W 2'
DEC = [dict(init=1, err=0, alt=1, valid=1, st=0x100E, misc_ok=1, misc=0x0D, ri=0),
       dict(init=1, err=1, alt=0, valid=0, st=0, misc_ok=0, misc=0, ri=3)]


def board(master, stop, counting=True, silent=False):
    s = ref.initial()
    os.set_blocking(master, False)
    while not stop.is_set():
        try:
            for b in os.read(master, 64):
                n = ref.apply(s, b)
                if not counting:
                    n = ref.replace(n, count=s.count)
                if n.q_req != s.q_req:
                    os.write(master, (ref.q_line(DEC) + '\r\n').encode())
                s = n
        except BlockingIOError:
            pass
        if not silent:
            f = ref.log_fields(s)
            line = BASE.format(ch=f['channel'], mhz=f['mhz'], mode=f['mode'], flt=f['filter']) + ref.suffix(s)
            os.write(master, (line + '\r\n').encode())
        time.sleep(0.02)


def run(cmds, **kw):
    master, slave = os.openpty()
    tty.setraw(slave)                      # no echo: the pretend board must not read its own lines back
    stop = threading.Event()
    th = threading.Thread(target=board, args=(master, stop), kwargs=kw, daemon=True)
    th.start()
    fd = m6ctl.open_port(os.ttyname(slave), 115200)
    lines = m6ctl.Lines(fd)
    try:
        return [m6ctl.send(fd, lines, c, 2) for c in cmds]
    finally:
        stop.set()
        th.join()
        os.close(fd)
        os.close(slave)
        os.close(master)


def test_receipts():
    r = run('LV+?')
    assert all(x['ok'] for x in r), r
    assert r[0]['line']['lat'] == 'LOW' and r[1]['line']['filter'] == 'V' and r[2]['line']['channel'] == 'F5'
    assert r[3]['status'] == m6ctl.parse_q(ref.q_line(DEC))
    q = r[3]['status']
    assert (q['A']['addr'], q['A']['r88'], q['A']['r03'], q['B']['answer'], q['B']['reinit']) == ('5D', 0x0E, 0x0D,
                                                                                                    'NA', 3)


def test_negative_control_not_counted():
    r = run('L', counting=False)
    assert not r[0]['ok'], r


def test_negative_control_silent():
    r = run('L', silent=True)
    assert not r[0]['ok'] and 'no log line' in r[0]['error'], r


def test_status_line_parser_refuses_damage():
    q = ref.q_line(DEC)
    assert m6ctl.parse_q(q) is not None
    for i in range(len(q)):
        assert m6ctl.parse_q(q[:i] + q[i + 1:]) is None, i
