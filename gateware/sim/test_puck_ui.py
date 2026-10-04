"""Puck UI: buttons -> RX5808 SPI frames (checked bit for bit against
model/vtx_channels.py) and the OLED picture (reconstructed from the I2C
writes and read back through the font) at three points of a button sequence.
A fake second master shares the I2C bus; there must be no collision.

Run: .venv/bin/python -m pytest -q gateware/sim/test_puck_ui.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import font5x7  # noqa: E402
import vtx_channels as vc  # noqa: E402


def run():
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_puck_ui'
    work.mkdir(parents=True, exist_ok=True)
    src = [GW / 'rtl' / n for n in ('i2c_master.v', 'rx5808_spi.v', 'ssd1306_text.v', 'bin2bcd.v', 'uart_tx.v', 'puck_ui.v')]
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_puck_ui',
                    *map(str, src), str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_puck_ui.v')],
                   cwd=work, env=env, check=True)
    return subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def screens(log):
    """Replay the SSD1306 writes (horizontal addressing, window 0-127 x 0-3) and
    return the 4 text rows every time the window is reset, plus MARK labels."""
    ram = [[0] * 128 for _ in range(4)]
    col = page = 0
    cmd_args, pending = [], None
    events = []
    for line in log.splitlines():
        if line.startswith('MARK'):
            events.append(('mark', line[5:]))
            continue
        m = re.match(r'I2C W (\w\w) (\w\w)', line)
        if not m:
            continue
        ctrl, b = int(m[1], 16), int(m[2], 16)
        if ctrl == 0x40:
            ram[page][col] = b
            col += 1
            if col == 128:
                col, page = 0, (page + 1) % 4
                if page == 0:
                    events.append(('screen', [font5x7.render_text(r) for r in ram]))
        else:
            if pending is None:
                if b in (0x21, 0x22):
                    pending, cmd_args = b, []
            else:
                cmd_args.append(b)
                if len(cmd_args) == 2:
                    if pending == 0x21:
                        col = cmd_args[0]
                    else:
                        page = cmd_args[0]
                    pending = None
    return events


def screen_before(events, label):
    last = None
    for kind, val in events:
        if kind == 'screen':
            last = val
        elif val.startswith(label):
            return last
    if label == 'MARK_END':
        return last                                   # the last complete screen of the run
    raise AssertionError(f'no mark {label}')


def test_puck_ui():
    log = run()
    res = dict(re.findall(r'(\w+)=(\w+)', next(l for l in log.splitlines() if l.startswith('RESULT'))))
    assert 'timeout' not in log
    assert res['collisions'] == '0' and res['nack'] == '0'

    # SPI: initial F4, then R4, L4, A4, A5, A6 — each a full 25-bit frame
    frames = re.findall(r'SPI (\d+) (\w+)', log)
    expect = [('F', 4), ('R', 4), ('L', 4), ('A', 4), ('A', 5), ('A', 6)]
    assert len(frames) == len(expect), frames
    table = {(b, c): (f, reg) for b, c, f, reg, _ in vc.table()}
    for (n, bits), key in zip(frames, expect):
        f, reg = table[key]
        want = sum(b << i for i, b in enumerate(vc.spi_frame(reg)))
        assert int(n) == 25 and int(bits, 16) == want, (key, n, bits, hex(want))

    ev = screens(log)
    s0 = screen_before(ev, 'default')
    assert s0 == ['>BAND F   CH 4  5800 ', ' MODE MIX VIEW A  BUF', ' A LOCK    B NOSIG   ', ' SE BAND OK          '], s0
    s1 = screen_before(ev, 'band_L')
    assert s1[0] == '>BAND L   CH 4  5473 ' and s1[3] == ' !OUTSIDE SE BAND    ', s1
    s2 = screen_before(ev, 'final')
    assert s2 == [' BAND A   CH 6  5765 ', '>MODE A   VIEW B  BUF', ' A LOCK    B NOSIG   ', ' SE BAND OK          '], s2
    final = re.search(r'MARK final force=(\d+)', log)[1]
    assert final == '10', 'mode A must mark receiver B bad'
    s_lat = screen_before(ev, 'lat')
    assert s_lat[1] == ' MODE A   VIEW B >LOW', s_lat
    assert re.search(r'MARK lat low_lat=(\d)', log)[1] == '1'

    s3 = screen_before(ev, 'MARK_END')
    assert s3 == ['>METER   A6  5765    ', 'A  12345 ########    ', 'B   2345 ######      ',
                  ' USE A 40 B 34 M 25  '], s3

    # UART log: fixed-width lines, the last one reflects the final state
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    lines = [l for l in text.split('\r\n') if l]
    assert lines and all(len(l) == 39 for l in lines), lines[:3]
    assert 'S 012345 002345 040 034 025 F4 5800 MIX' in lines, lines[:5]
    assert lines[-1] == 'S 012345 002345 040 034 025 A6 5765 A  ', lines[-3:]
    # OSD: shown after reset, hidden after OSD_MS, back on a button press, held on the meter page
    osd = [(int(t), int(v)) for t, v in re.findall(r'^OSD (\d+) (\d)$', log, re.M)]
    vals = [v for _, v in osd]
    assert vals[:2] == [1, 0] or vals[:3] == [0, 1, 0], osd[:4]
    assert vals[-1] == 1
