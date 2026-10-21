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
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
sys.path.insert(0, str(HERE))
import tvp_status  # noqa: E402
import vtx_channels as vc  # noqa: E402

WINDOW = 270_000
CLK_HZ = 2_700_000                  # what tb_probe.v tells the probe (scales its timers)
LINE = re.compile(r'^([AB]) sclk (\d{8}) (.*) i2c (5C|5D|NA|--) st (\S{4}) ri ([0-9A-F]{2})$')


def test_bringup_example_line():
    """The example report in BRINGUP.md section 3 has the format the probe prints (same
    pattern and length as in test_probe_reports), and its status word is what a healthy
    NTSC decoder reads according to the datasheet's bit tables."""
    text = (GW / 'BRINGUP.md').read_text(encoding='utf-8')
    example = next(l for l in text.splitlines() if l.startswith('A sclk '))
    m = LINE.match(example)
    assert m and len(example) == 88, example
    assert m[4] == '5C' and m[6] == '00' and 'len 1716-1716' in m[3], example
    assert tvp_status.healthy(int(m[5], 16), 'ntsc'), example


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
    # Exercise paths longer than the old Verilog reg[1023:0] (128 bytes).
    # A worktree or CI checkout can exceed that limit even without this fixture.
    fixture = work / ('long_vector_path_' * 5) / vec.name
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vec, fixture)
    assert len(str(fixture).encode()) > 128
    return subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={fixture}'], cwd=work, env=env, check=True,
                          capture_output=True, text=True).stdout


def test_probe_reports():
    log = run()
    assert 'RESULT spi_idle_bad=0' in log, log[-500:]       # SPI CLK low and DATA high between frames
    text = ''.join(chr(int(h, 16)) for h in re.findall(r'^U (\w\w)$', log, re.M))
    raw = text.split('\r\n')
    lines = [l for l in raw[:-1] if l]                     # the run may end inside a line
    assert all(len(l) == 88 for l in lines), [len(l) for l in lines]   # 90 bytes with CR LF
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
        _, _, body, i2c, st, _ = fields(l)
        assert body.startswith('tog FF hi FF len 1716-1716 ln '), l
        m = re.search(r'ln (\d{5}) fld (\d{3}) xe (\d{4})', body)
        assert m and 100 <= int(m[1]) <= 160 and int(m[2]) <= 1 and m[3] == '0000', l
        assert i2c == '5C' and st == '000E', l
    # B is reset at 15 ms (window 2). The poll round that finds 03h back at its default writes the
    # list again and makes B's status not valid; the next whole round, after window 2's report,
    # makes it valid again (tvp_ctrl.v, review 2026-10-06 F2)
    for l, want in zip(b[1:3], ('----', '000E')):
        _, _, body, i2c, st, _ = fields(l)
        assert body.startswith('tog DB hi DF len --------- ln 00000 fld 000 xe 0000'), l
        assert i2c == '5D' and st == want, l       # B is strapped to 5Dh in tb_probe.v

    # B's clock has stopped: the line says so instead of repeating stale values
    _, f_dead, body, _, _, _ = fields(b[3])
    assert body.strip() == 'no SCLK' and int(f_dead) < WINDOW // 2, b[3]
    assert fields(a[3])[2].startswith('tog FF hi FF'), a[3]

    # ri: decoder B's registers fell back to their defaults at 15 ms (during window 2) and were
    # written again; decoder A was never touched
    assert [fields(l)[5] for l in a] == ['00'] * len(a), a
    assert [fields(l)[5] for l in b] == ['00'] + ['01'] * (len(b) - 1), b

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
    # while the decoders report lock, repeats 8 ms apart once both have been read as unlocked
    # (the status is polled every 2 ms plus the I2C time, so that takes a few milliseconds).
    f4 = {(b, c): reg for b, c, f, reg, _ in vc.table()}[('F', 4)]
    want = sum(bit << i for i, bit in enumerate(vc.spi_frame(f4)))
    frames = [(int(t), int(n), int(bits, 16)) for t, n, bits in re.findall(r'^SPI (\d+) (\d+) (\w+)$', log, re.M)]
    assert frames and all((n, bits) == (25, want) for _, n, bits in frames), frames
    unlock = int(re.search(r'^UNLOCK (\d+)$', log, re.M)[1])
    before = [t for t, _, _ in frames if t < unlock]
    after = [t for t, _, _ in frames if t >= unlock]
    assert len(before) == 1 and abs(before[0] - 2_000_000) < 100_000, frames
    assert 1 <= len(after) <= 3 and 8_000_000 < after[0] - unlock < 15_000_000, (unlock, frames)
    assert all(abs((b2 - b1) - 8_000_000) < 100_000 for b1, b2 in zip(after, after[1:])), frames


def run_fields(source, tag):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_probe_fields{tag}'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_probe_fields', str(GW / 'rtl' / 'bt656_rx.v'),
                    str(source), str(HERE / 'tb_probe_fields.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={GW / "vectors" / "f_stuck_fields.hex"}'], cwd=work, env=env,
                         check=True, capture_output=True, text=True).stdout
    m = re.search(r'^FIELDS (\d+) LINES (\d+)$', out, re.M)
    assert m, out[-500:]
    return int(m[1]), int(m[2])


OLD_FIELDS = ("                if (rec_line == 10'd0 && a_fields != 10'h3FF) a_fields <= a_fields + 1'b1;",
              "                if (have_field && rec_field != last_field && a_fields != 10'h3FF) a_fields <= a_fields + 1'b1;\n"
              "                last_field <= rec_field; have_field <= 1'b1;")


def test_probe_counts_fields_of_a_progressive_source():
    """F held at 1 (vectors/f_stuck_fields.hex, four times): the probe counts every field from the line
    numbering, as many as the model's records with line 0 (LOGIKGRANSKNING F8). Negative control: the count
    of F-bit changes it used until 2026-10-21 gives 0."""
    sys.path.insert(0, str(GW / 'model'))
    import bt656
    data = bytes(int(x, 16) for x in (GW / 'vectors' / 'f_stuck_fields.hex').read_text().split())
    recs = bt656.Receiver().feed(data * 4)
    want = sum(r.line_in_field == 0 for r in recs)
    assert want == 12 and all(r.field == 1 for r in recs), want
    fields, lines = run_fields(GW / 'rtl' / 'bt656_probe.v', '')
    assert (fields, lines) == (want, len(recs)), (fields, lines)
    src = (GW / 'rtl' / 'bt656_probe.v').read_text()
    assert src.count(OLD_FIELDS[0]) == 1
    old = HERE / 'build' / 'tb_probe_fields_old'
    old.mkdir(parents=True, exist_ok=True)
    (old / 'bt656_probe.v').write_text(src.replace(OLD_FIELDS[0], OLD_FIELDS[1]).replace(
        '    wire        len_ok', '    reg         last_field = 1\'b0, have_field = 1\'b0;\n    wire        len_ok'))
    assert run_fields(old / 'bt656_probe.v', '_old')[0] == 0
