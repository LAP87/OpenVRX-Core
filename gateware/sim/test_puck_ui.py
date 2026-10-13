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
    src = [GW / 'rtl' / n for n in ('i2c_master.v', 'rx5808_spi.v', 'rx5808_tune.v', 'ssd1306_text.v', 'bin2bcd.v',
                                    'uart_tx.v', 'puck_ui.v')]
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
    assert res['spi_idle_bad'] == '0'                 # SPI CLK low and DATA high between frames

    # SPI: F4 after reset, then one frame per band / channel step (R4, L4, A4, A5, A6) while decoder A
    # is locked, each a full 25-bit frame. When no decoder is locked any more, A6 is repeated every
    # 40 ms (RX_REPEAT_MS in the testbench): three times in the 130 ms until decoder B locks, then never.
    frames = re.findall(r'SPI (\d+) (\w+) (\d+)', log)
    expect = [('F', 4), ('R', 4), ('L', 4), ('A', 4), ('A', 5), ('A', 6)] + [('A', 6)] * 3
    assert len(frames) == len(expect), frames
    table = {(b, c): (f, reg) for b, c, f, reg, _ in vc.table()}
    for (n, bits, _), key in zip(frames, expect):
        f, reg = table[key]
        want = sum(b << i for i, b in enumerate(vc.spi_frame(reg)))
        assert int(n) == 25 and int(bits, 16) == want, (key, n, bits, hex(want))
    t_unlock, t_relock = (int(re.search(rf'MARK {m} (\d+)', log)[1]) for m in ('unlock', 'relock'))
    times = [int(t) for _, _, t in frames]
    assert 5_000_000 < times[0] < 5_200_000, times[0]                       # RX_FIRST_MS = 5
    assert all(t < t_unlock for t in times[:6]), (times, t_unlock)
    assert [round((t - t_unlock) / 1e6) for t in times[6:]] == [40, 80, 120], (times, t_unlock)
    assert all(t < t_relock for t in times), (times, t_relock)

    ev = screens(log)
    s0 = screen_before(ev, 'default')
    assert s0 == ['>BAND F   CH 4  5800 ', ' MODE MIX VIEW A  BUF', ' A LOCK    B NOSIG   ', ' SE BAND OK  FILT TV '], s0
    s1 = screen_before(ev, 'band_L')
    assert s1[0] == '>BAND L   CH 4  5473 ' and s1[3] == ' !SE BAND  FILT TV   ', s1
    s_oob_vcr = screen_before(ev, 'filter_oob')
    assert s_oob_vcr[3] == ' !SE BAND >FILT VCR  ', s_oob_vcr
    s2 = screen_before(ev, 'final')
    assert s2 == [' BAND A   CH 6  5765 ', '>MODE A   VIEW B  BUF', ' A LOCK    B NOSIG   ', ' SE BAND OK  FILT VCR'], s2
    final = re.search(r'MARK final force=(\d+)', log)[1]
    assert final == '10', 'mode A must mark receiver B bad'
    s_lat = screen_before(ev, 'lat')
    assert s_lat[1] == ' MODE A   VIEW B >LOW', s_lat
    assert re.search(r'MARK lat low_lat=(\d)', log)[1] == '1'

    s_filter_vcr = screen_before(ev, 'filter_select_vcr')
    s_filter_tv = screen_before(ev, 'filter_select_tv')
    s_page = screen_before(ev, 'page_selected')
    assert s_filter_vcr[3] == ' SE BAND OK >FILT VCR', s_filter_vcr
    assert s_filter_tv[3] == ' SE BAND OK >FILT TV ', s_filter_tv
    assert s_page[3] == '>SE BAND OK  FILT TV ', s_page
    osd_rows = {int(tag): row for tag, row in re.findall(r'^OSDROW (\d+) (.{21})$', log, re.M)}
    assert set(osd_rows) == set(range(5)) and all(len(row) == 21 for row in osd_rows.values()), osd_rows
    assert osd_rows[0] == s0[3]
    assert osd_rows[1] == s_oob_vcr[3]
    assert osd_rows[2] == s_filter_vcr[3]
    assert osd_rows[3] == s_filter_tv[3]
    assert osd_rows[4] == s_page[3]
    assert [int(v) for v in re.findall(r'^FIELD (\d+)$', log, re.M)] == [0, 1, 2, 3, 4, 5, 0]
    assert res['filter_pulses'] == '2' and res['filter_width_errors'] == '0'
    assert res['final_filter_vcr'] == '0'

    s3 = screen_before(ev, 'relock')
    assert s3 == ['>METER   A6  5765    ', 'A  12345 ########    ', 'B   2345 ######      ',
                  ' USE A 40 B 34 M 25  '], s3
    # RSSI page: raw codes, calibrated %, LOW/WEAK flags, CAL field
    s_rssi = screen_before(ev, 'rssi')
    assert s_rssi == ['>RSSI    A6  5765    ', 'A 12000  75          ', 'B  4567   3  LOW WEAK',
                      ' CAL OFF  A OK  B OK '], s_rssi
    s_sel = screen_before(ev, 'cal_selected')
    assert s_sel[0] == ' RSSI    A6  5765    ' and s_sel[3] == '>CAL OFF  A OK  B OK ', s_sel
    assert screen_before(ev, 'cal_on')[3] == '>CAL ON   A OK  B OK '
    assert re.search(r'MARK rssi page=(\d) cal=(\d)', log).groups() == ('2', '0')
    assert re.search(r'MARK cal_selected field=(\d)', log)[1] == '6'
    assert re.search(r'MARK cal_on cal=(\d)', log)[1] == '1'
    assert re.search(r'MARK cal_off cal=(\d)', log)[1] == '0'
    assert re.search(r'MARK wrapped field=(\d) cal=(\d)', log).groups() == ('0', '1')
    assert re.search(r'MARK left page=(\d) cal=(\d)', log).groups() == ('0', '0'), 'leaving the page ends CAL'
    assert screen_before(ev, 'MARK_END')[0] == ' BAND A   CH 6  5765 '

    # UART log: fixed-width lines, the last one reflects the final state
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    lines = [l for l in text.split('\r\n') if l]
    assert lines and all(len(l) == 83 for l in lines), lines[:3]
    assert all(l[60:] == ' 12000 04567 075 003 -W' for l in lines), lines[:3]
    assert all(l[50:53] in ('MIX', 'A  ', 'B  ') and l[53] == ' ' and l[54] in 'TV'
               and l[55] == ' ' and l[56] in '-!' and l[57] == ' '
               and len(l[58:60]) == 2 and all(c in '-L?' for c in l[58:60]) for l in lines), lines[:3]
    assert any(l[54] == 'T' for l in lines) and any(l[54] == 'V' for l in lines), lines[:5]
    assert 'S 012345 002345 000017 654321 040 034 025 F4 5800 MIX T - -- 12000 04567 075 003 -W' in lines, lines[:5]
    # the mixer dropped a line; decoder B has had no whole poll round since "unlock" (its stale bit 4 is ignored)
    assert lines[-1] == 'S 012345 002345 000017 654321 040 034 025 A6 5765 A   T ! -? 12000 04567 075 003 -W', lines[-3:]
    # decoder A read 88h bit 4 ("lost lock") in one poll round: exactly one line says so
    lost = [l for l in lines if l[58] == 'L']
    assert len(lost) == 1 and lost[0][57:60] == ' L-', [l[56:60] for l in lines]
    assert all(l[59] in '-?' for l in lines)
    # OSD: shown after reset, hidden after OSD_MS, back on a button press, held on the meter page
    osd = [(int(t), int(v)) for t, v in re.findall(r'^OSD (\d+) (\d)$', log, re.M)]
    vals = [v for _, v in osd]
    assert vals[:2] == [1, 0] or vals[:3] == [0, 1, 0], osd[:4]
    # held on the meter page (no button between unlock and relock), hidden again on the main page at the end
    before = [v for tt, v in osd if tt <= t_unlock]
    assert before[-1] == 1 and not [tt for tt, _ in osd if t_unlock < tt <= t_relock], osd
    assert vals[-1] == 0
