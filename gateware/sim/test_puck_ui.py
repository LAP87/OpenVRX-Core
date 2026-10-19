"""Puck UI: buttons -> RX5808 SPI frames (checked bit for bit against model/vtx_channels.py) and the
OLED picture (reconstructed from the I2C writes and read back through the font; the double-size rows
through model/oled_ref.py, which also gives the expected page bytes) at points of a button sequence:
the flight view, the menu, the information pages, HOLD, the menu timeout, an aborted and a whole scan,
a flash load; the OSD text, the UART log. A fake second master shares the I2C bus; there must be no
collision.

Negative controls: copies of puck_ui.v (one of ssd1306_text.v) with one rule broken, run up to the
mark where the rule shows (+hdmi_only, +hold_only, +timeout_only); the check of that rule must fail
on each. The DVI build (HDMI_BUILD = 0) is run to the HDMI marks: the item says N/A and NEXT leaves it.

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
import oled_ref  # noqa: E402
import vtx_channels as vc  # noqa: E402

SRC = ('i2c_master.v', 'rx5808_spi.v', 'rx5808_tune.v', 'bin2bcd.v', 'uart_tx.v', 'chan_scan.v')
BIG = (True, False)
SMALL = (False, False)
HINT = 'OK:NEXT  NEXT:CHANGE '
ROW2 = 'A:LOCK  75 B:NOSIG  3'                     # decoder A locked, B not; RSSI 75 % and 3 %
ROW2_B = 'A:NOSIG 75 B:LOCK   3'                   # after the relock: B locked, A not


def run(name='tb_puck_ui', alter=None, alter_oled=None, plusargs=(), params=()):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    local = []
    for fname, alters in (('puck_ui.v', alter), ('ssd1306_text.v', alter_oled)):
        text = (GW / 'rtl' / fname).read_text()
        for old, new in (alters or []):
            assert text.count(old) == 1, (fname, old)
            text = text.replace(old, new)
        (work / fname).write_text(text)
        local.append(str(work / fname))
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_puck_ui',
                    *[f'-Ptb_puck_ui.{k}={v}' for k, v in params],
                    *[str(GW / 'rtl' / n) for n in SRC], *local, str(HERE / 'i2c_slave_model.v'),
                    str(HERE / 'tb_puck_ui.v')], cwd=work, env=env, check=True)
    return subprocess.run(['vvp', '-n', 'sim.vvp', *plusargs], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def big_rows(top, row2, row3):
    """The four rows of a screen whose top pair is one double-size row of 10 characters."""
    assert len(top) <= 10 and len(row2) == 21 and len(row3) == 21, (top, row2, row3)
    return [(top + ' ' * 10)[:10] + ' ' * 11, ' ' * 21, row2, row3]


def marks(log):
    """MARK <label> k=v ... -> {label: {k: v}}."""
    out = {}
    for m in re.finditer(r'^MARK (\w+)(.*)$', log, re.M):
        out[m[1]] = dict(re.findall(r'(\w+)=(\w+)', m[2]))
    return out


def mark_time(log, label):
    return int(re.search(rf'^MARK {label} (\d+)', log, re.M)[1])


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


def screens(log):
    """Replay the SSD1306 writes (horizontal addressing, window 0-127 x 0-3) and return, every time the
    window is reset, the screen as (rows, big, page bytes), plus the MARK labels."""
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
                    rows, big = oled_ref.decode(ram)
                    events.append(('screen', (rows, big, [r[:] for r in ram])))
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
    """(rows, big, page bytes) of the last complete screen before MARK <label>."""
    last = None
    for kind, val in events:
        if kind == 'screen':
            last = val
        elif val.startswith(label):
            return last
    if label == 'MARK_END':
        return last                                   # the last complete screen of the run
    raise AssertionError(f'no mark {label}')


def rows_before(events, label):
    return screen_before(events, label)[0]


# ---- the checks the negative controls share with the main test

def check_default(ev):
    """The flight view at start: the double-size channel row, byte for byte against the model; the save
    status blank before the flash is ready and DEFAULTS when it holds no record."""
    rows, big, ram = screen_before(ev, 'default')
    want = big_rows('F4 5800', ROW2, 'MIX BUF TV           ')
    assert (rows, big) == (want, BIG), (rows, big)
    assert ram == oled_ref.page_bytes(want, BIG), 'the double-size row, byte for byte'
    assert rows_before(ev, 'defaults')[3] == 'MIX BUF TV   DEFAULTS', rows_before(ev, 'defaults')


def check_hdmi_field(ev, log, until=None, dvi=False):
    """The HDMI item: FULL, NEXT makes it LTD on the screen, the output and the log (the DVI build says
    N/A and NEXT leaves it at FULL)."""
    m = marks(log)
    assert m['hdmi_selected'] == {'field': '5', 'ltd': '0'}, m['hdmi_selected']
    rows = rows_before(ev, 'hdmi_selected')
    if dvi:
        assert rows == big_rows('HDMI N/A', 'DVI BUILD: NO EFFECT ', 'OK:NEXT  DVI BUILD   '), rows
        assert rows_before(ev, 'hdmi_ltd') == rows and m['hdmi_ltd']['ltd'] == '0'
        toks = hdmi_tokens(log, None, None)
        assert toks and set(toks) == {'F'}, toks
        return
    assert rows == big_rows('HDMI FULL', 'RGB 0-255 FULL       ', HINT), rows
    rows = rows_before(ev, 'hdmi_ltd')
    assert rows == big_rows('HDMI LTD', 'RGB 16-235 LIMITED   ', HINT), rows
    assert m['hdmi_ltd'] == {'ltd': '1', 'filter_vcr': '1'}, m['hdmi_ltd']
    toks = hdmi_tokens(log, 'hdmi_ltd', until)
    assert toks and set(toks) == {'L'}, toks


def check_hold(ev, log):
    """HOLD: the item, the padlock on the flight view, BAND / CH / SCAN inert while it is on, and the
    save status UNSAVED and SAVE ERR on the flight view."""
    m = marks(log)
    assert m['hold_on'] == {'hold': '1', 'field': '7'}, m['hold_on']
    assert rows_before(ev, 'hold_on') == big_rows('HOLD ON', 'ON: LOCKS CH AND SCAN', 'OK:EXIT  NEXT:CHANGE ')
    assert m['fly_hold'] == {'page': '0', 'hold': '1'}, m['fly_hold']
    rows, big, _ = screen_before(ev, 'fly_hold')
    assert (rows, big) == (big_rows('A6 5765  @', ROW2, 'A   LOW TV    UNSAVED'), BIG), rows
    assert m['hold_band'] == {'band': '0', 'ch': '5', 'field': '0'}, m['hold_band']
    assert rows_before(ev, 'hold_band') == big_rows('BAND A', 'A6 5765 MHZ  SE OK   ', 'OK:NEXT  HOLD IS ON  ')
    assert m['hold_ch'] == {'band': '0', 'ch': '5'}, m['hold_ch']
    assert m['hold_scan'] == {'busy': '0', 'field': '6'}, m['hold_scan']
    assert rows_before(ev, 'hold_scan') == big_rows('SCAN', 'SEARCH 48 CHANNELS   ', 'OK:NEXT  HOLD IS ON  ')
    assert m['save_err'] == {'page': '0', 'hold': '0'}, m['save_err']
    assert rows_before(ev, 'save_err') == big_rows('A6 5765', ROW2, 'A   LOW TV   SAVE ERR')


def check_timeout(log):
    m = marks(log)
    assert m['menu_again'] == {'page': '3'} and m['timeout'] == {'page': '0'}, (m['menu_again'], m['timeout'])


def test_puck_ui():
    log = run()
    res = dict(re.findall(r'(\w+)=(\w+)', next(l for l in log.splitlines() if l.startswith('RESULT'))))
    assert 'RESULT timeout' not in log                 # the run did not hit the testbench deadline
    assert res['collisions'] == '0' and res['nack'] == '0'
    assert res['spi_idle_bad'] == '0'                 # SPI CLK low and DATA high between frames
    m = marks(log)

    # SPI: F4 after reset, then one frame per band / channel step (R4, L4, A4, A5, A6) while decoder A
    # is locked, each a full 25-bit frame; the steps under HOLD write nothing. When no decoder is locked
    # any more, A6 is repeated every 40 ms (RX_REPEAT_MS in the testbench): three times in the 130 ms
    # until decoder B locks, then never.
    frames = re.findall(r'SPI (\d+) (\w+) (\d+)', log)
    expect = [('F', 4), ('R', 4), ('L', 4), ('A', 4), ('A', 5), ('A', 6)] + [('A', 6)] * 3
    t_scan, t_scan2 = mark_time(log, 'scan_start'), mark_time(log, 'scan2_start')
    scan_frames = [fr for fr in frames if t_scan < int(fr[2]) <= t_scan2]
    scan2_frames = [fr for fr in frames if int(fr[2]) > t_scan2]
    frames = [fr for fr in frames if int(fr[2]) <= t_scan]
    assert len(frames) == len(expect), frames
    table = {(b, c): (f, reg) for b, c, f, reg, _ in vc.table()}
    for (n, bits, _), key in zip(frames, expect):
        f, reg = table[key]
        want = sum(b << i for i, b in enumerate(vc.spi_frame(reg)))
        assert int(n) == 25 and int(bits, 16) == want, (key, n, bits, hex(want))
    t_unlock, t_relock = mark_time(log, 'unlock'), mark_time(log, 'relock')
    times = [int(t) for _, _, t in frames]
    assert 5_000_000 < times[0] < 5_200_000, times[0]                       # RX_FIRST_MS = 5
    assert all(t < t_unlock for t in times[:6]), (times, t_unlock)
    assert [round((t - t_unlock) / 1e6) for t in times[6:]] == [40, 80, 120], (times, t_unlock)
    assert all(t < t_relock for t in times), (times, t_relock)

    ev = screens(log)
    # the flight view, then the menu one item per screen
    check_default(ev)
    assert m['default'] == {'page': '0', 'field': '0'} and m['menu'] == {'page': '3', 'field': '0'}
    assert rows_before(ev, 'menu') == big_rows('BAND F', 'F4 5800 MHZ  SE OK   ', HINT), rows_before(ev, 'menu')
    rows = rows_before(ev, 'band_L')
    assert rows == big_rows('BAND L', 'L4 5473 MHZ  !SE     ', HINT) and m['band_L'] == {'force': '00'}, rows
    assert rows_before(ev, 'filter_oob') == big_rows('FILT VCR', 'DECODER MODE REQUEST ', HINT)
    # HDMI: FULL -> LTD; the log says F before, L from then to the step back, F again until the flash load,
    # and L after it
    check_hdmi_field(ev, log, 'filter_select_tv')
    for start, end, tok in ((None, 'hdmi_selected', 'F'), ('hdmi_full', 'scan_aborted', 'F'), ('loaded', None, 'L')):
        toks = hdmi_tokens(log, start, end)
        assert toks and set(toks) == {tok}, (start, end, toks)
    # OK after the last item leaves the menu: the flight view, outside the SE band, filter VCR
    assert m['exit'] == {'page': '0'}
    assert rows_before(ev, 'exit') == big_rows('L4 5473 !', ROW2, 'MIX BUF VCR  DEFAULTS'), rows_before(ev, 'exit')
    assert m['final'] == {'force': '10', 'band': '0', 'ch': '5', 'mode': '1', 'field': '2'}, m['final']
    assert rows_before(ev, 'final') == big_rows('MODE A', 'A: RECEIVER A ONLY   ', HINT)
    assert m['lat'] == {'low_lat': '1'}
    assert rows_before(ev, 'lat') == big_rows('LAT LOW', 'LOW: FOLLOWS INPUT   ', HINT)
    assert rows_before(ev, 'filter_select_vcr') == big_rows('FILT VCR', 'DECODER MODE REQUEST ', HINT)
    assert rows_before(ev, 'filter_select_tv') == big_rows('FILT TV', 'DECODER MODE REQUEST ', HINT)
    assert m['hdmi_full'] == {'ltd': '0'}
    assert rows_before(ev, 'hdmi_full') == big_rows('HDMI FULL', 'RGB 0-255 FULL       ', HINT)
    # two NEXT on the filter and the flash load at the end, which requests the filter again
    assert res['filter_pulses'] == '3' and res['filter_width_errors'] == '0'
    assert res['final_filter_vcr'] == '0'
    # HOLD, the save status, the menu timeout
    check_hold(ev, log)
    check_timeout(log)

    # the information pages: meter, RSSI with the calibration on OK, back to the flight view on NEXT
    assert m['meter'] == {'page': '1'}
    rows, big, _ = screen_before(ev, 'meter')
    assert (rows, big) == ([' METER   A6  5765    ', 'A  12345 ########    ', 'B   2345 ######      ',
                            ' USE A 40 B 34 M 25  '], SMALL), rows
    assert m['rssi'] == {'page': '2', 'cal': '0'}
    assert rows_before(ev, 'rssi') == [' RSSI    A6  5765    ', 'A 12000  75          ', 'B  4567   3  LOW WEAK',
                                       'OK:CAL OFF  A OK B OK'], rows_before(ev, 'rssi')
    assert m['cal_on'] == {'cal': '1'} and m['cal_off'] == {'cal': '0'}
    assert rows_before(ev, 'cal_on')[3] == 'OK:CAL ON   A OK B OK'
    assert m['left'] == {'page': '0', 'cal': '0'}, 'leaving the page ends CAL'
    assert rows_before(ev, 'left') == big_rows('A6 5765', ROW2_B, 'A   LOW TV      SAVED'), rows_before(ev, 'left')

    # SCAN: the channels in table order from the first, then back to A6 on the abort, and the SCAN
    # screen as it was (an abort is not NONE)
    rows_t = vc.table()
    keys = [(b, c) for b, c, *_ in rows_t]
    want_bits = [sum(b << i for i, b in enumerate(vc.spi_frame(rows_t[i][3]))) for i in range(len(rows_t))]
    order = [int(bits, 16) for _, bits, _ in scan_frames]
    assert 3 <= len(order) - 1 <= 8, len(order)                  # 0.6 s at 100-200 ms per channel
    assert order[:-1] == want_bits[:len(order) - 1], 'channels 0, 1, 2, ... in table order'
    assert order[-1] == want_bits[keys.index(('A', 6))], 'the abort retunes the starting channel'
    assert m['scan_selected'] == {'field': '6', 'page': '3'}
    assert rows_before(ev, 'scan_selected') == big_rows('SCAN', 'SEARCH 48 CHANNELS   ', 'OK:NEXT  NEXT:START  ')
    assert m['scan_busy'] == {'busy': '1'}
    rows = rows_before(ev, 'scan_busy')
    assert rows[0] == 'SCANNING' + ' ' * 13 and rows[3] == 'ANY BUTTON ABORTS    ', rows
    assert re.fullmatch(r'TRYING [A-L][1-8] \d{4} MHZ   ', rows[2]), rows
    assert m['scan_aborted'] == {'busy': '0', 'band': '0', 'ch': '5', 'field': '6', 'page': '3'}, m['scan_aborted']
    assert rows_before(ev, 'scan_aborted') == big_rows('SCAN', 'SEARCH 48 CHANNELS   ', 'OK:NEXT  NEXT:START  ')
    # a whole scan: decoder B locked with the same noise on every channel, the tie keeps A6 (Core #22),
    # all 48 channels written and A6 again, and the menu ends on the flight view
    order2 = [int(bits, 16) for _, bits, _ in scan2_frames]
    assert order2 == want_bits + [want_bits[keys.index(('A', 6))]], (len(order2), order2[:3])
    assert m['scan_found'] == {'page': '0', 'band': '0', 'ch': '5'}, m['scan_found']
    assert mark_time(log, r'scan_found page=0 band=0 ch=5') - t_scan2 > 1_400_000_000, 'at least 30 ms per channel'
    assert rows_before(ev, 'scan_found') == big_rows('A6 5765', ROW2_B, 'A   LOW TV      SAVED')
    # the flash load: the saved LTD takes effect, the other settings were the current ones and stay
    assert m['loaded'] == {'ltd': '1', 'band': '0', 'ch': '5', 'mode': '1', 'low_lat': '1', 'filter_vcr': '0'}, m['loaded']
    assert rows_before(ev, 'MARK_END') == big_rows('A6 5765', ROW2_B, 'A   LOW TV      SAVED')

    # the OSD port gives the same rows as the OLED (the double-size row as its 10 characters)
    osd = {}
    for tag, r, text in re.findall(r'^OSDROW (\d+) (\d) (.{21})$', log, re.M):
        osd.setdefault(int(tag), {})[int(r)] = text
    assert set(osd) == set(range(7)) and all(set(v) == set(range(4)) for v in osd.values()), osd
    for tag, label in enumerate(('default', 'menu', 'filter_oob', 'hdmi_ltd', 'filter_select_vcr', 'hold_on', 'fly_hold')):
        assert [osd[tag][r] for r in range(4)] == rows_before(ev, label), (label, osd[tag])

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
    # OSD: shown after reset, hidden after OSD_MS, back on a button press, held on the information pages
    # and in the menu, hidden on the flight view at the end
    osd_v = [(int(t), int(v)) for t, v in re.findall(r'^OSD (\d+) (\d)$', log, re.M)]
    vals = [v for _, v in osd_v]
    assert vals[:2] == [1, 0] or vals[:3] == [0, 1, 0], osd_v[:4]
    before = [v for tt, v in osd_v if tt <= t_unlock]
    assert before[-1] == 1 and not [tt for tt, _ in osd_v if t_unlock < tt <= t_relock], osd_v
    assert vals[-1] == 0


def test_dvi_build_shows_hdmi_na():
    """HDMI_BUILD = 0 (the DVI build): the HDMI item says N/A with the hint DVI BUILD, NEXT leaves the
    range at FULL, and the log keeps saying F."""
    log = run('tb_puck_ui_dvi', plusargs=['+hdmi_only'], params=[('HDMI_BUILD', 0)])
    assert 'RESULT hdmi_only' in log, log[-500:]
    check_hdmi_field(screens(log), log, dvi=True)


# mutant: (change to puck_ui.v, value of MARK hdmi_ltd ltd=, what the failing check reports)
NEGATIVE = {
    'no_step': ([("                F_HDMI: if (HDMI_BUILD != 0) hdmi_ltd <= ~hdmi_ltd;\n", "                F_HDMI: ;\n")],
                '0', 'HDMI FULL'),
    'screen_always_full': ([('hdmi_ltd ? "LTD  " : "FULL "', '"FULL "')], '1', 'HDMI FULL'),
    'log_always_f': ([('hdmi_ltd ? "L" : "F", " ", ovf_s[1]', '"F", " ", ovf_s[1]')], '1', r"\['F'"),
}


@pytest.mark.parametrize('mutant', sorted(NEGATIVE))
def test_hdmi_field_negative_control(mutant):
    """A copy of puck_ui.v with the HDMI item broken, run up to the HDMI marks (+hdmi_only): the run gets
    there, and the checks of the item fail on the broken part (the step, the screen or the log)."""
    alter, ltd, reported = NEGATIVE[mutant]
    log = run(f'tb_puck_ui_{mutant}', alter=alter, plusargs=['+hdmi_only'])
    assert 'RESULT hdmi_only' in log, log[-500:]
    assert re.search(r'MARK hdmi_ltd ltd=(\d)', log)[1] == ltd
    with pytest.raises(AssertionError, match=reported):
        check_hdmi_field(screens(log), log)


# mutant: (change to puck_ui.v, change to ssd1306_text.v, plusarg, the check that must fail)
UI_NEGATIVE = {
    'saved_always': ([('wire [71:0] save_s = !set_ready ? "         " : set_err ? " SAVE ERR" : set_dirty ? "  UNSAVED"\n'
                       '                       : set_stored ? "    SAVED" : " DEFAULTS";', 'wire [71:0] save_s = "    SAVED";')],
                     None, 'hdmi_only', lambda ev, log: check_default(ev)),
    'no_big': (None, [("    wire       big  = text_big[pg[1]];\n", "    wire       big  = 1'b0;\n")], 'hdmi_only',
               lambda ev, log: check_default(ev)),
    'hold_ignored': ([("            default: if (!item_blocked) case (field)\n", "            default: case (field)\n")],
                     None, 'hold_only', check_hold),
    'no_timeout': ([("        if (menu_timeout) page <= P_FLY;\n", "")], None, 'timeout_only',
                   lambda ev, log: check_timeout(log)),
}


@pytest.mark.parametrize('mutant', sorted(UI_NEGATIVE))
def test_ui_negative_control(mutant):
    """Copies with the save status always SAVED, the double-size row drawn single size, HOLD not blocking
    the items, and no menu timeout: each run gets to its marks and the check of that rule fails."""
    alter, alter_oled, stop, check = UI_NEGATIVE[mutant]
    log = run(f'tb_puck_ui_{mutant}', alter=alter, alter_oled=alter_oled, plusargs=[f'+{stop}'])
    assert f'RESULT {stop}' in log, log[-500:]
    with pytest.raises(AssertionError):
        check(screens(log), log)
