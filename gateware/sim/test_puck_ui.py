"""Puck UI: buttons -> RX5808 SPI frames (checked bit for bit against
model/vtx_channels.py) and the OLED picture (reconstructed from the I2C
writes and read back through the font) at points of a button sequence, the
OSD text, the UART log and a flash load at the end.
A fake second master shares the I2C bus; there must be no collision.

The HDMI field (FULL/LTD, 2026-10-18) has negative controls: copies of puck_ui.v
where NEXT does not step it, the screen always says FULL, or the log always says F,
run up to the HDMI marks; the checks of the field must fail on each.

Run: .venv/bin/python -m pytest -q gateware/sim/test_puck_ui.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import font5x7  # noqa: E402
import vtx_channels as vc  # noqa: E402


def run(name='tb_puck_ui', alter=None, plusargs=()):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src = [GW / 'rtl' / n for n in ('i2c_master.v', 'rx5808_spi.v', 'rx5808_tune.v', 'ssd1306_text.v', 'bin2bcd.v',
                                    'uart_tx.v', 'chan_scan.v')]
    ui = (GW / 'rtl' / 'puck_ui.v').read_text()
    for old, new in (alter or []):
        assert ui.count(old) == 1, old
        ui = ui.replace(old, new)
    (work / 'puck_ui.v').write_text(ui)
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_puck_ui',
                    *map(str, src), str(work / 'puck_ui.v'), str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_puck_ui.v')],
                   cwd=work, env=env, check=True)
    return subprocess.run(['vvp', '-n', 'sim.vvp', *plusargs], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def hdmi_tokens(log, start, end=None):
    """The HDMI token (F/L) of every log line received whole after MARK <start> (from the beginning if None)
    and before MARK <end> (to the end if None). A line is taken when its first byte is sent, so a line whose
    bytes all arrive after a mark was taken at most one byte before it; the marks come two OLED frames after
    the button that changed the range."""
    text, on = '', start is None
    for ln in log.splitlines():
        if start and ln.startswith(f'MARK {start}'):
            on = True
        elif end and ln.startswith(f'MARK {end}'):
            break
        elif on and ln.startswith('U '):
            text += chr(int(ln[2:], 16))
    whole = text.split('\r\n')[1:-1]                 # drop the line in flight at each end
    return [l[56] for l in whole if len(l) == 85]


def check_hdmi_field(ev, log, until=None):
    """OK after the filter selects HDMI; NEXT steps FULL -> LTD on the screen, the output and the log."""
    s_sel = screen_before(ev, 'hdmi_selected')
    assert s_sel[3] == ' !SE   VCR >HDMI FULL', s_sel
    assert re.search(r'MARK hdmi_selected field=(\d) ltd=(\d)', log).groups() == ('5', '0')
    s_ltd = screen_before(ev, 'hdmi_ltd')
    assert s_ltd[3] == ' !SE   VCR >HDMI LTD ', s_ltd
    assert re.search(r'MARK hdmi_ltd ltd=(\d) filter_vcr=(\d)', log).groups() == ('1', '1')
    toks = hdmi_tokens(log, 'hdmi_ltd', until)
    assert toks and set(toks) == {'L'}, toks
    return s_sel, s_ltd


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
    t_scan = int(re.search(r'MARK scan_start (\d+)', log)[1])
    scan_frames = [fr for fr in frames if int(fr[2]) > t_scan]
    frames = [fr for fr in frames if int(fr[2]) <= t_scan]
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
    assert s0 == ['>BAND F   CH 4  5800 ', ' MODE MIX VIEW A  BUF', ' A LOCK  B NOSIG SCAN', ' SE OK TV   HDMI FULL'], s0
    s1 = screen_before(ev, 'band_L')
    assert s1[0] == '>BAND L   CH 4  5473 ' and s1[3] == ' !SE   TV   HDMI FULL', s1
    s_oob_vcr = screen_before(ev, 'filter_oob')
    assert s_oob_vcr[3] == ' !SE  >VCR  HDMI FULL', s_oob_vcr
    # HDMI: OK after the filter selects it, NEXT steps FULL -> LTD; the filter stays VCR. The log says F
    # before, L from then to the step back, F again until the flash load, and L after it
    s_hdmi_sel, s_hdmi_ltd = check_hdmi_field(ev, log, 'filter_select_tv')
    for start, end, tok in ((None, 'hdmi_selected', 'F'), ('hdmi_full', 'scan_aborted', 'F'), ('loaded', None, 'L')):
        toks = hdmi_tokens(log, start, end)
        assert toks and set(toks) == {tok}, (start, end, toks)
    s2 = screen_before(ev, 'final')
    assert s2 == [' BAND A   CH 6  5765 ', '>MODE A   VIEW B  BUF', ' A LOCK  B NOSIG SCAN', ' SE OK VCR  HDMI LTD '], s2
    final = re.search(r'MARK final force=(\d+)', log)[1]
    assert final == '10', 'mode A must mark receiver B bad'
    s_lat = screen_before(ev, 'lat')
    assert s_lat[1] == ' MODE A   VIEW B >LOW', s_lat
    assert re.search(r'MARK lat low_lat=(\d)', log)[1] == '1'

    s_filter_vcr = screen_before(ev, 'filter_select_vcr')
    s_filter_tv = screen_before(ev, 'filter_select_tv')
    s_hdmi_full = screen_before(ev, 'hdmi_full')
    s_page = screen_before(ev, 'page_selected')
    assert s_filter_vcr[3] == ' SE OK>VCR  HDMI LTD ', s_filter_vcr
    assert s_filter_tv[3] == ' SE OK>TV   HDMI LTD ', s_filter_tv
    assert s_hdmi_full[3] == ' SE OK TV  >HDMI FULL', s_hdmi_full
    assert re.search(r'MARK hdmi_full ltd=(\d)', log)[1] == '0'
    assert s_page[3] == '>SE OK TV   HDMI FULL', s_page
    osd_rows = {int(tag): row for tag, row in re.findall(r'^OSDROW (\d+) (.{21})$', log, re.M)}
    assert set(osd_rows) == set(range(8)) and all(len(row) == 21 for row in osd_rows.values()), osd_rows
    assert [osd_rows[k] for k in range(8)] == [s[3] for s in (s0, s_oob_vcr, s_hdmi_sel, s_hdmi_ltd, s_filter_vcr,
                                                                s_filter_tv, s_hdmi_full, s_page)], osd_rows
    assert [int(v) for v in re.findall(r'^FIELD (\d+)$', log, re.M)] == [0, 1, 2, 3, 4, 5, 6, 7, 0]
    # two NEXT on the filter and the flash load at the end, which requests the filter again
    assert res['filter_pulses'] == '3' and res['filter_width_errors'] == '0'
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
    assert re.search(r'MARK cal_selected field=(\d)', log)[1] == '7'
    assert re.search(r'MARK cal_on cal=(\d)', log)[1] == '1'
    assert re.search(r'MARK cal_off cal=(\d)', log)[1] == '0'
    assert re.search(r'MARK wrapped field=(\d) cal=(\d)', log).groups() == ('0', '1')
    assert re.search(r'MARK left page=(\d) cal=(\d)', log).groups() == ('0', '0'), 'leaving the page ends CAL'
    # SCAN: the channels in table order from the first, then back to A6 on the abort
    rows = vc.table()
    keys = [(b, c) for b, c, *_ in rows]
    order = [int(bits, 16) for _, bits, _ in scan_frames]
    want_bits = [sum(b << i for i, b in enumerate(vc.spi_frame(rows[i][3]))) for i in range(len(rows))]
    assert 3 <= len(order) - 1 <= 8, len(order)                  # 0.6 s at 100-200 ms per channel
    assert order[:-1] == want_bits[:len(order) - 1], 'channels 0, 1, 2, ... in table order'
    assert order[-1] == want_bits[keys.index(('A', 6))], 'the abort retunes the starting channel'
    assert re.search(r'MARK scan_selected field=(\d)', log)[1] == '7'
    assert screen_before(ev, 'scan_selected')[2] == ' A NOSIG B LOCK >SCAN'
    assert re.search(r'MARK scan_busy busy=(\d)', log)[1] == '1'
    assert screen_before(ev, 'scan_busy')[2] == ' A NOSIG B LOCK >BUSY'
    m = re.search(r'MARK scan_aborted busy=(\d) band=(\d) ch=(\d) field=(\d)', log).groups()
    assert m == ('0', '0', '5', '7'), 'A6 again, the button only aborted (the field did not move)'
    # the flash load: the saved LTD takes effect, the other settings were the current ones and stay
    m = re.search(r'MARK loaded ltd=(\d) band=(\d) ch=(\d) mode=(\d) low_lat=(\d) filter_vcr=(\d)', log).groups()
    assert m == ('1', '0', '5', '1', '1', '0'), m
    s_end = screen_before(ev, 'MARK_END')
    assert s_end[0] == ' BAND A   CH 6  5765 ' and s_end[3] == ' SE OK TV   HDMI LTD ', s_end

    # UART log: fixed-width lines, the last one reflects the final state
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    lines = [l for l in text.split('\r\n') if l]
    assert lines and all(len(l) == 85 for l in lines), lines[:3]
    assert all(l[62:] == ' 12000 04567 075 003 -W' for l in lines), lines[:3]
    assert all(l[50:53] in ('MIX', 'A  ', 'B  ') and l[53] == ' ' and l[54] in 'TV'
               and l[55] == ' ' and l[56] in 'FL' and l[57] == ' ' and l[58] in '-!' and l[59] == ' '
               and len(l[60:62]) == 2 and all(c in '-L?' for c in l[60:62]) for l in lines), lines[:3]
    assert any(l[54] == 'T' for l in lines) and any(l[54] == 'V' for l in lines), lines[:5]
    assert any(l[56] == 'F' for l in lines) and any(l[56] == 'L' for l in lines), [l[54:57] for l in lines]
    assert 'S 012345 002345 000017 654321 040 034 025 F4 5800 MIX T F - -- 12000 04567 075 003 -W' in lines, lines[:5]
    # the mixer dropped a line; decoder B has had no whole poll round since "unlock" (its stale bit 4 is ignored);
    # LTD from the flash load
    assert lines[-1] == 'S 012345 002345 000017 654321 040 034 025 A6 5765 A   T L ! -? 12000 04567 075 003 -W', lines[-3:]
    # decoder A read 88h bit 4 ("lost lock") in one poll round: exactly one line says so
    lost = [l for l in lines if l[60] == 'L']
    assert len(lost) == 1 and lost[0][59:62] == ' L-', [l[58:62] for l in lines]
    assert all(l[61] in '-?' for l in lines)
    # OSD: shown after reset, hidden after OSD_MS, back on a button press, held on the meter page
    osd = [(int(t), int(v)) for t, v in re.findall(r'^OSD (\d+) (\d)$', log, re.M)]
    vals = [v for _, v in osd]
    assert vals[:2] == [1, 0] or vals[:3] == [0, 1, 0], osd[:4]
    # held on the meter page (no button between unlock and relock), hidden again on the main page at the end
    before = [v for tt, v in osd if tt <= t_unlock]
    assert before[-1] == 1 and not [tt for tt, _ in osd if t_unlock < tt <= t_relock], osd
    assert vals[-1] == 0


# mutant: (change to puck_ui.v, value of MARK hdmi_ltd ltd=, what the failing check reports)
NEGATIVE = {
    'no_step': ([("            3'd5: hdmi_ltd <= ~hdmi_ltd;\n", "")], '0', 'HDMI FULL'),
    'screen_always_full': ([('hdmi_ltd ? "HDMI LTD " : "HDMI FULL"', '"HDMI FULL"')], '1', 'HDMI FULL'),
    'log_always_f': ([('hdmi_ltd ? "L" : "F", " ", ovf_s[1]', '"F", " ", ovf_s[1]')], '1', r"\['F'"),
}


@pytest.mark.parametrize('mutant', sorted(NEGATIVE))
def test_hdmi_field_negative_control(mutant):
    """A copy of puck_ui.v with the HDMI field broken, run up to the HDMI marks (+hdmi_only): the run gets
    there, and the checks of the field fail on the broken part (the step, the screen or the log)."""
    alter, ltd, reported = NEGATIVE[mutant]
    log = run(f'tb_puck_ui_{mutant}', alter=alter, plusargs=['+hdmi_only'])
    assert 'RESULT hdmi_only' in log, log[-500:]
    assert re.search(r'MARK hdmi_ltd ltd=(\d)', log)[1] == ltd
    with pytest.raises(AssertionError, match=reported):
        check_hdmi_field(screens(log), log)
