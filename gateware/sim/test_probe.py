"""M3 bring-up probe: the report lines must show what is wrong with the wiring.

Decoder A is healthy (clean NTSC); decoder B has YOUT5 stuck low and YOUT2
stuck high, which also destroys every timing code, and its clock stops before
the last report. Checks every field of the fixed-width lines.

Also the probe's pins: the LEDs, and the RX5808 channel write (F4) on the SPI
pins. Both decoder models report lock until 32 ms, then neither does: one
frame at the start, none while a decoder is locked, repeats after the lock is
gone (the rule itself is tested in test_rx5808_tune.py).

Run: .venv/bin/python -m pytest -q gateware/sim/test_probe.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import vtx_channels as vc  # noqa: E402

WINDOW = 270_000
CLK_HZ = 2_700_000                  # what tb_probe.v tells the probe (scales its timers)
LINE = re.compile(r'^([AB]) sclk (\d{8}) (.*) i2c (OK|NA|--) st (\S{4})$')


def run():
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / 'tb_probe'
    work.mkdir(parents=True, exist_ok=True)
    src = [GW / 'rtl' / n for n in ('bt656_rx.v', 'bt656_probe.v', 'i2c_master.v', 'tvp_ctrl.v', 'rx5808_spi.v',
                                    'rx5808_tune.v', 'bin2bcd.v', 'uart_tx.v')] + [GW / 'top' / 'm3_probe.v']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_probe',
                    *map(str, src), str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_probe.v')],
                   cwd=work, env=env, check=True)
    vec = GW / 'vectors' / 'ntsc_clean_frame.hex'
    return subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={vec}'], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def test_probe_reports():
    log = run()
    assert 'RESULT spi_idle_bad=0' in log, log[-500:]       # SPI CLK low and DATA high between frames
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    raw = text.split('\r\n')
    lines = [l for l in raw[:-1] if l]                     # the run may end inside a line
    assert all(len(l) == 82 for l in lines), [len(l) for l in lines]   # 84 bytes with CR LF
    a = [l for l in lines if l.startswith('A')]
    b = [l for l in lines if l.startswith('B')]
    assert len(a) == len(b) >= 4, lines

    def fields(l):
        m = LINE.match(l)
        assert m, l
        return m.groups()

    # SCLK frequency: SCLK/256 edges per window x 256. A runs at the board clock's rate, B 0.27 % faster.
    fa = int(fields(a[1])[1])
    fb = int(fields(b[1])[1])
    assert abs(fa - WINDOW) <= 512, fa
    assert abs(fb - WINDOW * 37 / 36.9) <= 512, fb

    # windows 2 and 3: A healthy, B with its stuck bits and no timing codes
    for l in a[1:3]:
        _, _, body, i2c, st = fields(l)
        assert body.startswith('tog FF hi FF len 1716-1716 ln '), l
        m = re.search(r'ln (\d{5}) fld (\d{3}) xe (\d{4})', body)
        assert m and 100 <= int(m[1]) <= 160 and int(m[2]) <= 1 and m[3] == '0000', l
        assert i2c == 'OK' and st == '402E', l
    for l in b[1:3]:
        _, _, body, i2c, st = fields(l)
        assert body.startswith('tog DB hi DF len --------- ln 00000 fld 000 xe 0000'), l
        assert i2c == 'OK' and st == '402E', l

    # B's clock has stopped: the line says so instead of repeating stale values
    _, f_dead, body, _, _ = fields(b[3])
    assert body.strip() == 'no SCLK' and int(f_dead) < WINDOW // 2, b[3]
    assert fields(a[3])[2].startswith('tog FF hi FF'), a[3]

    # LEDs, printed as 'led2 led1 led0', 0 = lit. LED1 / LED2: SCLK A / B seen in the last window.
    leds = [(int(t), v) for t, v in re.findall(r'^LED (\d+) (\S{3})$', log, re.M)]

    def led_at(t):
        return [v for when, v in leds if when <= t][-1]
    win = WINDOW * 37
    assert led_at(win + 100_000)[:2] == '00', leds          # after window 1: both clocks run
    assert led_at(4 * win + 100_000)[:2] == '10', leds      # B's clock stopped during window 4: LED2 dark
    # LED0 is the heartbeat: it changes every CLK_HZ / 2 clocks, once in this run
    beats = [t for (t, v), (_, prev) in zip(leds[1:], leds) if prev[2] in '01' and v[2] != prev[2]]
    assert len(beats) == 1 and abs(beats[0] - CLK_HZ // 2 * 37) < 20 * 37, beats

    # RX5808: every frame is the F4 word. One frame 2 ms after start (20 probe milliseconds), none
    # while the decoders report lock, repeats 5 ms apart once both have been read as unlocked
    # (the status is polled every 2 ms plus the I2C time, so that takes a few milliseconds).
    f4 = {(b, c): reg for b, c, f, reg, _ in vc.table()}[('F', 4)]
    want = sum(bit << i for i, bit in enumerate(vc.spi_frame(f4)))
    frames = [(int(t), int(n), int(bits, 16)) for t, n, bits in re.findall(r'^SPI (\d+) (\d+) (\w+)$', log, re.M)]
    assert frames and all((n, bits) == (25, want) for _, n, bits in frames), frames
    unlock = int(re.search(r'^UNLOCK (\d+)$', log, re.M)[1])
    before = [t for t, _, _ in frames if t < unlock]
    after = [t for t, _, _ in frames if t >= unlock]
    assert len(before) == 1 and abs(before[0] - 2_000_000) < 100_000, frames
    assert 1 <= len(after) <= 3 and 5_000_000 < after[0] - unlock < 12_000_000, (unlock, frames)
    assert all(abs((b2 - b1) - 5_000_000) < 100_000 for b1, b2 in zip(after, after[1:])), frames
