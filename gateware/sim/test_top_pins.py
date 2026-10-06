"""What the pins of the M4 and M6 tops do: RESETB, the three LEDs and the RX5808 SPI lines.

The real tops are simulated with everything below them (sim/tb_top_pins.v); only
the Gowin primitives are stand-ins (sim/gowin_prim_stubs.v). CLK_HZ shortens the
tops' millisecond timers. The PLL outputs and the decoder clocks stop after
0.6 ms, when both decoders have delivered lines, so that the rest of the run is
cheap. The decoder models report no lock until T_LOCK.

Negative control: in a run where the decoders never lock, the checks that LED0
slows down and that the RX5808 writes stop must fail.

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
TOPS = {
    4: dict(name='m4_dual_mix', clk_hz=27_000, t_lock=7_000_000, t_end=14_000_000),
    6: dict(name='m6_puck_proto', clk_hz=135_000, t_lock=14_000_000, t_end=28_000_000),
}


@functools.lru_cache(maxsize=None)
def run(top, locks=True):
    cfg = TOPS[top]
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_top_pins_{top}_{int(locks)}'
    work.mkdir(parents=True, exist_ok=True)
    src = [HERE / 'gowin_prim_stubs.v', HERE / 'i2c_slave_model.v', HERE / 'tb_top_pins.v',
           *sorted((GW / 'rtl').glob('*.v')), GW / 'top' / f'{cfg["name"]}.v']
    params = dict(TOP=top, CLK_HZ=cfg['clk_hz'], T_B_NS=T_B, T_LOCK_NS=cfg['t_lock'] if locks else 0,
                  T_END_NS=cfg['t_end'])
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


def check_led0_slow_at_end(r):
    """1 Hz once both decoders are locked."""
    half = r['clk_hz'] // 2 * T_CLK
    tg = led0_toggles(r)
    gaps = [b - a for a, b in zip(tg, tg[1:])][-2:]
    assert len(gaps) == 2 and all(abs(g - half) <= T_CLK for g in gaps), (half, gaps)


def check_line_leds(r):
    """LED1 follows lines from A, LED2 lines from B (B delivers none before T_B)."""
    assert led_at(r, T_B - 10_000)[:2] == '10', led_at(r, T_B - 10_000)           # led2 dark, led1 lit
    assert led_at(r, VIDEO_STOP - 10_000)[:2] == '00', led_at(r, VIDEO_STOP - 10_000)


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
    check_resetb(r)
    check_line_leds(r)
    check_led0_fast(r, r['t_lock'])
    check_led0_slow_at_end(r)
    check_rx_frames(r)
    check_rx_stops(r)


def test_m4_pins():
    check_all(run(4))


def test_m6_pins():
    check_all(run(6))


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
