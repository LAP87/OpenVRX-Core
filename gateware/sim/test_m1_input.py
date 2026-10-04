"""cocotb: frame-buffer writes from bt656_rx + luma_writer must equal what the
Python model implies (every second luma sample, line*360 + column, first 240 lines).

Run:  .venv/bin/python -m pytest -q gateware/sim
"""
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402

COLS, LINES = 360, 240


def expected_writes(data):
    """Writes implied by the model's completed lines, plus the line number of the
    line still open at the end of the stream (hardware writes pixels as they
    arrive, the model only reports a line when its EAV closes it)."""
    out, last = {}, None
    for r in bt656.Receiver().feed(bytes(data)):
        last = r
        if r.line_in_field >= LINES:
            continue
        for col, y in enumerate(r.luma[0::2][:COLS]):
            out[r.line_in_field * COLS + col] = y     # later fields overwrite earlier ones (bob)
    return out, (last.line_in_field + 1 if last else 0)


def check(got, data):
    exp, open_line = expected_writes(data)
    extra = {a for a in got if a not in exp}
    assert all(a // COLS == open_line for a in extra), \
        f'unexpected writes outside the still-open line {open_line}: {sorted(extra)[:5]}'
    missing = [a for a in exp if a not in got]
    assert not missing, f'{len(missing)} expected writes missing, first {missing[0]}'
    bad = [a for a in exp if got[a] != exp[a]]
    assert not bad, f'{len(bad)} wrong values, first at {bad[0]}: {got[bad[0]]} != {exp[bad[0]]}'
    return len(exp), len(extra)


async def drive(dut, data):
    cocotb.start_soon(Clock(dut.clk, 37, unit='ns').start())
    dut.rst.value = 1
    dut.d.value = 0x80
    await RisingEdge(dut.clk)
    writes = {}
    for b in list(data) + [0x80] * 6:
        await FallingEdge(dut.clk)
        dut.rst.value = 0
        dut.d.value = b
        await RisingEdge(dut.clk)
        await ReadOnly()
        if dut.we.value:
            writes[int(dut.addr.value)] = int(dut.data.value)
    return writes


@cocotb.test()
async def faults_vector_writes_match_model(dut):
    data = [int(x, 16) for x in (GW / 'vectors' / 'pal_faults.hex').read_text().split()]
    n, extra = check(await drive(dut, data), data)
    dut._log.info(f'pal_faults: {n} writes match the model, {extra} from the open last line')


@cocotb.test()
async def ntsc_start_writes_match_model(dut):
    data = [int(x, 16) for x in (GW / 'vectors' / 'ntsc_clean_frame.hex').read_text().split()][:60000]
    n, extra = check(await drive(dut, data), data)
    dut._log.info(f'ntsc start: {n} writes match the model, {extra} from the open last line')


def test_m1_input_path():
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / 'tb_m1_input'
    r.build(sources=[GW / 'rtl' / 'bt656_rx.v', GW / 'rtl' / 'luma_writer.v', HERE / 'tb_m1_input.v'],
            hdl_toplevel='tb_m1_input', build_dir=build, always=True, timescale=('1ns', '1ps'))
    r.test(hdl_toplevel='tb_m1_input', test_module='test_m1_input', test_dir=HERE, build_dir=build)
