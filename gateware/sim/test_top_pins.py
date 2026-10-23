"""What the pins of the M4 and M6 tops do: RESETB, the three LEDs and the RX5808 SPI lines.

The real tops are simulated with everything below them (sim/tb_top_pins.v); only
the Gowin primitives are stand-ins (sim/gowin_prim_stubs.v). CLK_HZ shortens the
tops' millisecond timers. The PLL outputs and the decoder clocks stop after
0.6 ms, when both decoders have delivered lines, so that the rest of the run is
cheap. The decoder models report no lock until T_LOCK.

Negative control: in a run where the decoders never lock, the checks that LED0
slows down and that the RX5808 writes stop must fail.

The SDRAM pins carry sim/sdram_model.v with its default board delays: the
self-test (sdram_selftest.v) finds read point 5 alone, and M4 shows that on
LED 1 for ST_SHOW_MS. Negative control: with the pins open no point reads
right, and M4 lights LED 1 and 2 while A's lines would light only LED 1.

LED 0 (2026-10-21, hub LOGIKGRANSKNING F2): 4 Hz with no decoder locked, 1 Hz with one,
2 Hz with both. M6 (F10, F13): a log line every second once the mixer windows stop with
the video, and the menu text in the OSD RAM. Negative controls: the never-locked run stays
at 4 Hz; an M6 copy without the heartbeat and without the OSD mirror's reset sends no line
after the video stops and leaves the OSD RAM unknown (X) in simulation.

Run: .venv/bin/python -m pytest -q gateware/sim/test_top_pins.py"""
import functools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import vtx_channels as vc  # noqa: E402

T_CLK = 37                      # ns, board clock of the testbench
T_B = 300_000                   # ns, decoder B starts to deliver lines
VIDEO_STOP = 600_000            # ns, PLL outputs and decoder clocks stop
ST_SHOW_MS = 5                  # M4: LED 1/2 show the SDRAM self-test this long (5 ms at CLK_HZ 27 kHz: 5 us)
TOPS = {
    4: dict(name='m4_dual_mix', clk_hz=27_000, t_lock=7_000_000, t_end=14_000_000),
    6: dict(name='m6_puck_proto', clk_hz=135_000, t_lock=14_000_000, t_end=28_000_000),
}


@functools.lru_cache(maxsize=None)
def run(top, locks=True, sdram=True, t_end=None, lock_b=True, alter=None):
    """alter: ((path relative to gateware, text, replacement), ...) for copies of those files (negative controls)."""
    cfg = dict(TOPS[top], **({'t_end': t_end} if t_end else {}))
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / (f'tb_top_pins_{top}_{int(locks)}{"" if sdram else "_nosdram"}{"" if lock_b else "_oneb"}'
                             f'{"_alt" if alter else ""}')
    work.mkdir(parents=True, exist_ok=True)
    src = [HERE / 'gowin_prim_stubs.v', HERE / 'i2c_slave_model.v', HERE / 'sdram_model.v', HERE / 'tb_top_pins.v',
           *sorted((GW / 'rtl').glob('*.v')), GW / 'top' / f'{cfg["name"]}.v']
    for rel, old, new in (alter or ()):
        text = (GW / rel).read_text()
        assert text.count(old) == 1, (rel, old)
        copy = work / Path(rel).name
        copy.write_text(text.replace(old, new))
        src = [copy if s == GW / rel else s for s in src]
    params = dict(TOP=top, CLK_HZ=cfg['clk_hz'], T_B_NS=T_B, T_LOCK_NS=cfg['t_lock'] if locks else 0,
                  T_END_NS=cfg['t_end'], SDRAM=int(sdram), ST_SHOW_MS=ST_SHOW_MS, LOCK_B=int(lock_b))
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_top_pins',
                    *[f'-Ptb_top_pins.{k}={v}' for k, v in params.items()], *map(str, src)],
                   cwd=work, env=env, check=True)
    vec = GW / 'vectors' / 'ntsc_clean_frame.hex'
    fixture = work / ('long_vector_path_' * 5) / vec.name
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vec, fixture)
    assert len(str(fixture).encode()) > 128
    log = subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={fixture}', f'+pll_stop_ns={VIDEO_STOP}'], cwd=work, env=env,
                         check=True, capture_output=True, text=True).stdout
    assert 'RESULT done spi_idle_bad=0' in log, log[-2000:]         # SPI CLK low, DATA high between frames
    return dict(cfg,
                resetb=[(int(t), v) for t, v in re.findall(r'^RESETB (\d+) (\S)$', log, re.M)],
                led=[(int(t), v) for t, v in re.findall(r'^LED (\d+) (\S{3})$', log, re.M)],
                sdtest=[(int(t), v) for t, v in re.findall(r'^SDRAMTEST (\d+) (\S{3})$', log, re.M)],
                loglines=[int(t) for t in re.findall(r'^LOGLINE (\d+)$', log, re.M)],
                osd=(re.findall(r'^OSDTEXT (\S+)$', log, re.M) or [''])[0],
                spi=[(int(t), int(n), int(bits, 16)) for t, n, bits in re.findall(r'^SPI (\d+) (\d+) (\w+)$', log, re.M)])


def led_at(r, t):
    """The three LED pins (text 'led2 led1 led0', 0 = lit) at time t."""
    return [v for when, v in r['led'] if when <= t][-1]


def led0_toggles(r):
    out, last = [], None
    for t, v in r['led']:
        if v[2] in '01' and last in ('0', '1') and v[2] != last:
            out.append(t)
        last = v[2]
    return out


def check_resetb(r):
    """One low pulse, 20 ms after start and 2 ms long (tvp_ctrl POWER_MS and RESET_MS), then high."""
    ms = r['clk_hz'] // 1000 * T_CLK
    known = [(t, v) for t, v in r['resetb'] if v in '01']
    assert [v for _, v in known] == ['1', '0', '1'], r['resetb']
    fall, rise = known[1][0], known[2][0]
    assert abs(fall - 20 * ms) <= 12 * T_CLK, (fall, 20 * ms)        # plus a few clocks of power-on reset
    assert abs((rise - fall) - 2 * ms) <= 2 * T_CLK, (rise - fall, 2 * ms)


def check_led0_fast(r, until):
    """4 Hz while the decoders are not both locked."""
    half = r['clk_hz'] // 8 * T_CLK
    tg = [t for t in led0_toggles(r) if t <= until]
    gaps = [b - a for a, b in zip(tg, tg[1:])]
    assert len(gaps) >= 4 and all(abs(g - half) <= T_CLK for g in gaps), (half, gaps[:8])


def check_led0_slow_at_end(r, both=True):
    """2 Hz once both decoders are locked, 1 Hz once one is."""
    half = r['clk_hz'] // (4 if both else 2) * T_CLK
    tg = led0_toggles(r)
    gaps = [b - a for a, b in zip(tg, tg[1:])][-2:]
    assert len(gaps) == 2 and all(abs(g - half) <= T_CLK for g in gaps), (half, gaps)


def check_line_leds(r):
    """LED1 follows lines from A, LED2 lines from B (B delivers none before T_B)."""
    assert led_at(r, T_B - 10_000)[:2] == '10', led_at(r, T_B - 10_000)           # led2 dark, led1 lit
    assert led_at(r, VIDEO_STOP - 10_000)[:2] == '00', led_at(r, VIDEO_STOP - 10_000)


def check_sdram_selftest(r, mask):
    """One self-test result, before decoder B starts; M4: LED 1/2 show it for ST_SHOW_MS, then A's lines."""
    assert [m for _, m in r['sdtest']] == [mask], r['sdtest']
    t = r['sdtest'][0][0]
    show = r['clk_hz'] // 1000 * ST_SHOW_MS * T_CLK
    assert t + show + 2_000 < T_B, (t, show)
    if r['name'] == 'm4_dual_mix':
        leds = {'010': '10', '001': '01', '100': '01', '000': '00'}[mask]       # led2 led1, 0 = lit
        assert led_at(r, t + 2_000)[:2] == leds, (mask, led_at(r, t + 2_000))
        assert led_at(r, t + show + 2_000)[:2] == '10', led_at(r, t + show + 2_000)


def f4_word():
    reg = {(b, c): reg for b, c, f, reg, _ in vc.table()}[('F', 4)]
    return sum(bit << i for i, bit in enumerate(vc.spi_frame(reg)))


def check_rx_frames(r):
    """F4 on the SPI pins 0.5 s after start and every 2 s until a decoder locks (rx5808_tune.v)."""
    ms = r['clk_hz'] // 1000 * T_CLK
    first, repeat = 500 * ms, 2000 * ms
    assert r['spi'] and all((n, bits) == (25, f4_word()) for _, n, bits in r['spi']), r['spi']
    early = [t for t, _, _ in r['spi'] if t < r['t_lock']]
    assert len(early) >= 2 and abs(early[0] - first) < repeat / 100, (first, early)
    assert all(abs((b - a) - repeat) < repeat / 100 for a, b in zip(early, early[1:])), (repeat, early)


def check_rx_stops(r):
    """No write once the lock has been read: the status poll may take up to 3.5 ms here."""
    late = [t for t, _, _ in r['spi'] if t > r['t_lock'] + 3_500_000]
    assert not late, (r['t_lock'], late)


def check_all(r):
    check_sdram_selftest(r, '010')
    check_resetb(r)
    check_line_leds(r)
    check_led0_fast(r, r['t_lock'])
    check_led0_slow_at_end(r)
    check_rx_frames(r)
    check_rx_stops(r)


def test_m4_pins():
    check_all(run(4))


def test_m6_pins():
    """Also the log heartbeat and the OSD text (in this test: a second test on the same run would share its
    build directory in the parallel suite)."""
    r = run(6)
    check_all(r)
    check_m6_heartbeat_and_osd(r)


def test_m4_one_decoder_locked_led0_at_1hz():
    """Decoder B never reports lock: LED 0 goes from 4 Hz to 1 Hz (a bench with one module sees the lock),
    not to 2 Hz."""
    r = run(4, lock_b=False)
    check_led0_fast(r, r['t_lock'])
    check_led0_slow_at_end(r, both=False)
    with pytest.raises(AssertionError):
        check_led0_slow_at_end(r, both=True)


def check_m6_heartbeat_and_osd(r):
    """After the video stops no mixer window comes, but a log line still comes every second; the OSD RAM
    holds the menu text (printable characters in the 4 x 21 cells)."""
    second = r['clk_hz'] * T_CLK
    late = [t for t in r['loglines'] if t > VIDEO_STOP + second // 2]
    assert len(late) >= 2, (r['loglines'][:5], late)
    gaps = [b - a for a, b in zip(late, late[1:])]
    assert all(abs(g - second) <= second // 50 for g in gaps), (second, gaps)
    cells = [r['osd'][2 * (row * 32 + col):2 * (row * 32 + col) + 2] for row in range(4) for col in range(21)]
    assert all(c not in ('', 'xx', 'XX') and 0x20 <= int(c, 16) <= 0x7E for c in cells), cells
    assert sum(c != '20' for c in cells) >= 10, cells


def test_m6_heartbeat_and_osd_checks_are_tested():
    """Negative control: puck_ui without the heartbeat and M6 without the OSD mirror's reset, as before
    2026-10-21."""
    r = run(6, t_end=12_000_000, alter=(
        ('rtl/puck_ui.v', '    parameter HEARTBEAT_MS = 1000,', '    parameter HEARTBEAT_MS = 0,'),
        ('top/m6_puck_proto.v', "        if (rst_c[2]) begin scan_row <= 2'd0; scan_col <= 5'd0; scan_we <= 1'b0; end", '')))
    assert not [t for t in r['loglines'] if t > VIDEO_STOP + r['clk_hz'] * T_CLK // 2], r['loglines'][:5]
    with pytest.raises(AssertionError):
        check_m6_heartbeat_and_osd(r)
    assert 'x' in r['osd'].lower(), r['osd'][:60]


def test_without_lock_led0_stays_fast_and_writes_go_on():
    """Negative control: the decoders never report lock."""
    r = run(4, locks=False)
    check_resetb(r)
    check_line_leds(r)
    check_led0_fast(r, r['t_end'])
    check_rx_frames(r)
    with pytest.raises(AssertionError):
        check_led0_slow_at_end(r)
    with pytest.raises(AssertionError):
        check_rx_stops(r)


def test_m4_sdram_selftest_without_sdram():
    """Negative control: open SDRAM pins. No read point is right, and LED 1 and 2 are both lit in the window,
    where A's lines alone light only LED 1; afterwards the line LEDs return."""
    r = run(4, sdram=False, t_end=400_000)
    check_sdram_selftest(r, '000')
    with pytest.raises(AssertionError):
        check_sdram_selftest(r, '010')
