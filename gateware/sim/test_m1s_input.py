"""cocotb: tvp_sync_rx + luma_writer on a synthetic discrete-sync stream.

A mini format keeps the simulation short: 200 bytes per line (160 active =
80 luma samples), 4 VBI lines with VSYNC + 20 active lines per field. Checks
that the last field ends up in the frame buffer with luma correctly picked,
for normal and inverted sync polarities and for both luma byte phases.

Run:  .venv/bin/python -m pytest -q gateware/sim
"""
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
COLS, LINES = 30, 16
# AVID ~67 % of the time (real video ~78 %), so polarity detection has a clear majority
LINE, ACTIVE, HS_LEN, VBI, ACT_LINES = 200, 160, 12, 4, 20


def luma(field, line, k):
    return 16 + (field * 37 + line * 11 + k * 5) % 200


def field_stream(field, luma_first, hs_low, vs_low, avid_high):
    """Per-clock tuples (d, hsync, vsync, avid) for one field."""
    out = []
    for line in range(VBI + ACT_LINES):
        active = line >= VBI
        for b in range(LINE):
            in_av = active and b < ACTIVE
            hs = (ACTIVE + 16) <= b < (ACTIVE + 16 + HS_LEN)
            vs = line < 2
            if in_av:
                k, is_luma = (b // 2, b % 2 == 0) if luma_first else (b // 2, b % 2 == 1)
                d = luma(field, line - VBI, k) if is_luma else 128 + ((line + b) % 5) - 2
            else:
                d = 0x10 if b % 2 else 0x80
            out.append((d, int(hs) ^ hs_low, int(vs) ^ vs_low, int(in_av) ^ (1 - avid_high)))
    return out


async def run(dut, luma_first, hs_low, vs_low, avid_high, fields=8):
    cocotb.start_soon(Clock(dut.clk, 37, unit='ns').start())
    dut.rst.value = 1
    dut.d.value, dut.hsync_in.value, dut.vsync_in.value, dut.avid_in.value = 0x80, hs_low, vs_low, 1 - avid_high
    await RisingEdge(dut.clk)
    writes = {}
    for f in range(fields):
        for d, hs, vs, av in field_stream(f, luma_first, hs_low, vs_low, avid_high):
            await FallingEdge(dut.clk)
            dut.rst.value = 0
            dut.d.value, dut.hsync_in.value, dut.vsync_in.value, dut.avid_in.value = d, hs, vs, av
            await RisingEdge(dut.clk)
            await ReadOnly()
            if dut.we.value:
                writes[int(dut.addr.value)] = int(dut.data.value)
    last = fields - 1
    exp = {line * COLS + col: luma(last, line, 2 * col) for line in range(LINES) for col in range(COLS)}
    bad = [a for a in exp if writes.get(a) != exp[a]]
    assert not bad, f'{len(bad)} wrong pixels, first {bad[0]}: {writes.get(bad[0])} != {exp[bad[0]]}'
    assert int(dut.luma_odd.value) == (0 if luma_first else 1)
    assert int(dut.vs_active_high.value) == (1 - vs_low)
    assert int(dut.avid_active_high.value) == avid_high


@cocotb.test()
async def normal_polarity_cb_first(dut):
    """HSYNC/VSYNC active low, AVID active high, Cb Y Cr Y."""
    await run(dut, luma_first=False, hs_low=1, vs_low=1, avid_high=1)


@cocotb.test()
async def inverted_polarity_luma_first(dut):
    """All polarities inverted and luma on the first AVID byte."""
    await run(dut, luma_first=True, hs_low=0, vs_low=0, avid_high=0)


def test_m1s_input_path():
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / 'tb_m1s_input'
    r.build(sources=[GW / 'rtl' / 'tvp_sync_rx.v', GW / 'rtl' / 'luma_writer.v', HERE / 'tb_m1s_input.v'],
            hdl_toplevel='tb_m1s_input', build_dir=build, always=True, timescale=('1ns', '1ps'))
    r.test(hdl_toplevel='tb_m1s_input', test_module='test_m1s_input', test_dir=HERE, build_dir=build)
