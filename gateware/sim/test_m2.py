"""cocotb integration test of the M2 path: BT.656 -> SDRAM field buffers ->
display window, with three clock domains and the behavioural SDRAM.

Stimulus: fields of 12 active lines (2 VBI lines each), alternating F bit,
known luma/chroma patterns. Checks the SDRAM contents of a published field
and the RGB output pixels against a Python model of the scaling and BT.601
conversion. What the field store decides is tested in test_fb.py.

Run:  .venv/bin/python -m pytest -q gateware/sim
"""
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402
import fb_ref  # noqa: E402

LINES, VBI, V_ACTIVE, V_TOTAL = 12, 2, 36, 40


def sample(field, line, x):
    """(Cb, Y, Cr) for pixel x of a line; avoids the reserved codes 0 and 255."""
    y = 16 + (field * 29 + line * 13 + x) % 220
    cb = 64 + (line * 7 + x // 2 + field * 40) % 128
    cr = 64 + (line * 11 + (x // 2) * 3 + field * 20) % 128
    return cb, y, cr


def active_bytes(field, line):
    out = bytearray()
    for x in range(0, 720, 2):
        cb, y0, cr = sample(field, line, x)
        _, y1, _ = sample(field, line, x + 1)
        out += bytes([cb, y0, cr, y1])
    return bytes(out)


def field_stream(field):
    f = field & 1
    data = bytearray()
    for i in range(VBI + LINES):
        v = 1 if i < VBI else 0
        act = bt656.blanking(1440) if v else active_bytes(field, i - VBI)
        data += bytes([0xFF, 0, 0, bt656.xy(f, v, 1)]) + bt656.blanking(1716 - 1440 - 8)
        data += bytes([0xFF, 0, 0, bt656.xy(f, v, 0)]) + act
    return bytes(data)


def to_rgb(y, cb, cr):
    def clamp(v):
        return 0 if v < 0 else 255 if v > 65280 else (v >> 8) & 0xFF
    ys, cbs, crs = y - 16, cb - 128, cr - 128
    return (clamp(298 * ys + 409 * crs + 128),
            clamp(298 * ys - 208 * crs - 100 * cbs + 128),
            clamp(298 * ys + 516 * cbs + 128))


def expected_pixel(field, out_y, x, low=False):
    """Model of fb_display: line mapping from fb_ref, x window 160..1119, sx = xr*3//4."""
    src = fb_ref.src_line(out_y, LINES, V_ACTIVE, low)
    if not (160 <= x < 1120):
        return (0, 0, 0)
    sx = ((x - 160) * 3) // 4
    cb, _, cr = sample(field, src, sx & ~1)
    _, y, _ = sample(field, src, sx)
    return to_rgb(y, cb, cr)


@cocotb.test()
async def m2_end_to_end(dut):
    cocotb.start_soon(Clock(dut.tvp_clk, 37, unit='ns').start())
    cocotb.start_soon(Clock(dut.sd_clk, 15.4, unit='ns').start())
    cocotb.start_soon(Clock(dut.pix_clk, 13.4, unit='ns').start())
    dut.rst.value = 1
    dut.ll_mode.value = 0
    dut.tvp_d.value = 0x80
    await Timer(500, unit='ns')
    dut.rst.value = 0
    while not dut.sdram_ready.value:
        await RisingEdge(dut.sd_clk)

    fb = dut.core.backend.fb
    pubs = []                     # (buf, lines, field index written)
    holds = {0: 0}                # buffer -> index of the field written to it last

    async def watch_pubs():
        written = 0
        while True:
            await RisingEdge(dut.sd_clk)
            await ReadOnly()
            if fb.publish.value:
                pubs.append((int(fb.cur_buf.value), int(fb.n_now.value), written))
                written += 1
                holds[int(fb.nxt.value)] = written
    cocotb.start_soon(watch_pubs())

    async def feed(nfields):
        for fld in range(nfields):
            for b in field_stream(fld):
                await FallingEdge(dut.tvp_clk)
                dut.tvp_d.value = b
    await feed(5)

    assert len(pubs) >= 3, f'only {len(pubs)} field publications'
    assert all(p[1] == LINES for p in pubs), f'line counts {pubs}'
    assert len({p[0] for p in pubs[-3:]}) >= 2, f'buffers not rotating: {pubs}'

    # SDRAM contents of the newest published field
    buf, _, fld = pubs[-1]
    await RisingEdge(dut.sd_clk)                 # leave the read-only phase before poking
    for line in (0, 5, LINES - 1):
        for idx in (0, 1, 7, 8, 179, 359):
            act = active_bytes(fld, line)
            exp = int.from_bytes(act[4 * idx:4 * idx + 4], 'little')
            dut.mem.peek_addr.value = buf * (1 << 19) + line * 512 + idx
            await Timer(1, unit='ps')
            got = int(dut.mem.peek_data.value)
            assert got == exp, f'field {fld} buf {buf} line {line} word {idx}: {got:#010x} != {exp:#010x}'

    # display: wait for a frame start, find which field it shows (decided in the SDRAM domain
    # a few clocks after the frame's first line request), check pixels
    while True:
        await RisingEdge(dut.pix_clk)
        await ReadOnly()
        if int(dut.core.backend.timing.y.value) == V_TOTAL - 1 and int(dut.core.backend.timing.x.value) == 40:
            break
    shown_field = holds[int(fb.show_buf.value)]
    assert int(dut.core.backend.disp.have_video.value) == 1
    checked, out_y, x = 0, 0, 0
    while out_y < V_ACTIVE:
        await RisingEdge(dut.pix_clk)
        await ReadOnly()
        if dut.de.value:
            if x % 61 == 0 or x in (159, 160, 161, 1118, 1119, 1120):
                got = (int(dut.r.value), int(dut.g.value), int(dut.b.value))
                exp = expected_pixel(shown_field, out_y, x)
                assert got == exp, f'pixel ({x},{out_y}) field {shown_field}: got {got}, expected {exp}'
                checked += 1
            x += 1
            if x == 1280:
                x, out_y = 0, out_y + 1
    dut._log.info(f'{len(pubs)} fields published; SDRAM words and {checked} output pixels match')


TVP_NS, PIX_NS, H_TOTAL = 37, 13.4, 1650
LINE_BYTES = 1716


@cocotb.test()
async def m2_low_latency(dut):
    """ll_mode = 1: no SDRAM buffer. Each output frame must start right after line 1
    of an input field has arrived (genlock), and show that same field."""
    cocotb.start_soon(Clock(dut.tvp_clk, TVP_NS, unit='ns').start())
    cocotb.start_soon(Clock(dut.sd_clk, 15.4, unit='ns').start())
    cocotb.start_soon(Clock(dut.pix_clk, PIX_NS, unit='ns').start())
    dut.rst.value = 1
    dut.ll_mode.value = 1
    dut.tvp_d.value = 0x80
    await Timer(500, unit='ns')
    dut.rst.value = 0

    line1_done = []               # sim time (ns) when line 1 of field n has been sent
    end_of_line1 = (VBI + 2) * LINE_BYTES

    async def feed(nfields):
        for fld in range(nfields):
            for i, b in enumerate(field_stream(fld)):
                await FallingEdge(dut.tvp_clk)
                dut.tvp_d.value = b
                if i == end_of_line1:
                    line1_done.append(get_sim_time('ns'))
    feeder = cocotb.start_soon(feed(8))

    frames = []                   # sim time of each output frame's first active pixel
    async def watch_frames():
        while True:
            await RisingEdge(dut.pix_clk)
            await ReadOnly()
            if dut.core.backend.timing.frame_start.value:
                frames.append(get_sim_time('ns'))
    cocotb.start_soon(watch_frames())

    # check the pixels of the frame that follows field 5's line 1
    while len(line1_done) < 6:
        await RisingEdge(dut.pix_clk)
    shown_field = 5
    while True:
        await RisingEdge(dut.pix_clk)
        await ReadOnly()
        if int(dut.core.backend.timing.y.value) == 0 and int(dut.core.backend.timing.x.value) == 0:
            break
    assert int(dut.core.backend.disp.have_video.value) == 1
    checked, out_y, x = 0, 0, 0
    while out_y < V_ACTIVE:
        await RisingEdge(dut.pix_clk)
        await ReadOnly()
        if dut.de.value:
            if x % 61 == 0 or x in (159, 160, 161, 1118, 1119, 1120):
                got = (int(dut.r.value), int(dut.g.value), int(dut.b.value))
                exp = expected_pixel(shown_field, out_y, x)
                assert got == exp, f'pixel ({x},{out_y}) field {shown_field}: got {got}, expected {exp}'
                checked += 1
            x += 1
            if x == 1280:
                x, out_y = 0, out_y + 1
    await feeder

    # genlock: the output realigns at the third field at the latest (genlock_timing.v ignores two
    # early triggers); from field 3 on, one frame per field, starting 0..2 output lines after line 1
    out_line = H_TOTAL * PIX_NS
    lags = []
    for t in line1_done[3:]:
        nxt = [f for f in frames if f >= t]
        assert nxt, f'no frame after field line 1 at {t}'
        lags.append(nxt[0] - t)
    assert all(0 <= lag <= 2 * out_line for lag in lags), [round(l / out_line, 2) for l in lags]
    locked = [f for f in frames if f > line1_done[3]]
    periods = [b - a for a, b in zip(locked, locked[1:])]
    field_ns = (VBI + LINES) * LINE_BYTES * TVP_NS
    assert all(abs(p - field_ns) <= 1.5 * out_line for p in periods), periods
    # latency, line s: shown from frame start + s * V_ACTIVE/LINES output lines; arrived at line1_done + (s-1) lines
    worst = max(lags) + (LINES - 1) * (V_ACTIVE / LINES * out_line - LINE_BYTES * TVP_NS) + LINE_BYTES * TVP_NS
    dut._log.info(f'{checked} pixels match; lag after line 1: {[round(l / 1000, 1) for l in lags]} us; '
                  f'worst line latency ~{worst / 1000:.0f} us; frame periods {[round(p / 1000, 1) for p in periods]} us')


def _run_m2(testcase):
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / 'tb_m2'
    rtl = [GW / 'rtl' / n for n in ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'sdram_burst.v', 'field_phase.v',
                                    'fb_sdram.v', 'dual_clock_ram.v', 'genlock_timing.v', 'ycbcr2rgb.v',
                                    'fb_display.v', 'fb_backend.v', 'm2_core.v')]
    r.build(sources=rtl + [HERE / 'sdram_model.v', HERE / 'tb_m2.v'], hdl_toplevel='tb_m2',
            build_dir=build, always=True, timescale=('1ns', '1ps'))
    r.test(hdl_toplevel='tb_m2', test_module='test_m2', test_dir=HERE, build_dir=build, testcase=testcase)


def test_m2_end_to_end():
    _run_m2('m2_end_to_end')


def test_m2_low_latency():
    _run_m2('m2_low_latency')
