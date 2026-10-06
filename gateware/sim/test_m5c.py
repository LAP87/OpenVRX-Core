"""M5 alt. C path in simulation: BT.656 -> SDRAM -> 1080p-wide window (x2
horizontally) -> BT.1120 with embedded sync. The output stream is decoded the
way a receiver would (SAV/EAV), and the pixels of one frame are checked
against the model (Bresenham line mapping, source x = (x - 240) / 2,
Cb on even / Cr on odd pixels). Vertical timing is shortened to 40 lines.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_m5c.py
"""
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402
import fb_ref  # noqa: E402
from test_m2 import LINES, field_stream, sample  # noqa: E402

V_ACTIVE, H_ACTIVE = 36, 1920


def expected(field, out_y, x):
    if not (240 <= x < 1680):
        return 0x10, 0x80
    sx = (x - 240) // 2
    src = fb_ref.src_line(out_y, LINES, V_ACTIVE)
    cb, _, cr = sample(field, src, sx & ~1)
    _, y, _ = sample(field, src, sx)
    return y, (cb if x % 2 == 0 else cr)


@cocotb.test()
async def m5c_bt1120_frame(dut):
    cocotb.start_soon(Clock(dut.tvp_clk, 37, unit='ns').start())
    cocotb.start_soon(Clock(dut.sd_clk, 15.4, unit='ns').start())
    cocotb.start_soon(Clock(dut.pix_clk, 6.7, unit='ns').start())
    dut.rst.value = 1
    dut.tvp_d.value = 0x80
    await Timer(500, unit='ns')
    dut.rst.value = 0
    while not dut.sdram_ready.value:
        await RisingEdge(dut.sd_clk)

    fb = dut.core.backend.fb
    pubs = []
    holds = {0: 0}                # buffer -> index of the field written to it last

    async def watch_pubs():
        written = 0
        while True:
            await RisingEdge(dut.sd_clk)
            await ReadOnly()
            if fb.discard.value:                 # the field the writer joined (field 0) is dropped, buffer kept free
                written += 1
                holds[int(fb.nxt.value)] = written
            if fb.publish.value:
                pubs.append((int(fb.cur_buf.value), written))
                written += 1
                holds[int(fb.nxt.value)] = written
    cocotb.start_soon(watch_pubs())

    for fld in range(4):
        for byte in field_stream(fld):
            await FallingEdge(dut.tvp_clk)
            dut.tvp_d.value = byte
    assert len(pubs) >= 2

    # decode the BT.1120 stream: wait for a frame's first active SAV (after blanking SAVs)
    hist, prev_v, frame_buf = [], None, None      # prev_v: V of the last SAV actually seen
    state = 'seek'
    out_y, x, checked, codes = 0, 0, 0, 0
    while True:
        await RisingEdge(dut.pix_clk)
        await ReadOnly()
        y8, c8 = int(dut.bt_y.value), int(dut.bt_c.value)
        hist = (hist + [(y8, c8)])[-4:]
        is_code = len(hist) == 4 and [h[0] for h in hist[:3]] == [0xFF, 0, 0] and [h[1] for h in hist[:3]] == [0xFF, 0, 0]
        if is_code:
            xy = hist[3][0]
            assert hist[3][1] == xy and bt656.XY_TABLE[xy][3] == 'ok', f'bad timing code {hist}'
            f, v, h, _ = bt656.XY_TABLE[xy]
            codes += 1
            if state == 'active' and h == 1:
                assert x == H_ACTIVE + 3, f'EAV after {x} words'
                out_y += 1
                if out_y == V_ACTIVE:
                    break
            if h == 0 and v == 0:
                if state == 'seek' and prev_v == 1:
                    state = 'active'
                    frame_buf = int(fb.show_buf.value)
                x = 0                                    # next word is pixel 0
            if h == 0:
                prev_v = v
            continue
        if state == 'active' and 0 <= x < H_ACTIVE:
            if x % 37 == 0 or x in (238, 239, 240, 241, 1678, 1679, 1680):
                field = holds[frame_buf]
                exp = expected(field, out_y, x)
                assert (y8, c8) == exp, f'line {out_y} x {x} field {field}: got {(y8, c8)}, expected {exp}'
                checked += 1
        x += 1
    dut._log.info(f'{codes} timing codes, {checked} pixels match')


def test_m5c_bt1120():
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / 'tb_m5c'
    rtl = [GW / 'rtl' / n for n in ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'sdram_burst.v', 'field_phase.v',
                                    'fb_sdram.v', 'dual_clock_ram.v', 'genlock_timing.v', 'ycbcr2rgb.v',
                                    'fb_display.v', 'fb_backend.v', 'm2_core.v', 'tvp_sync_rx.v', 'bt1120_tx.v')]
    r.build(sources=rtl + [HERE / 'sdram_model.v', HERE / 'tb_m5c.v'], hdl_toplevel='tb_m5c',
            build_dir=build, always=True, timescale=('1ns', '1ps'))
    r.test(hdl_toplevel='tb_m5c', test_module='test_m5c', test_dir=HERE, build_dir=build)
