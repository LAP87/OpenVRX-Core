"""cocotb testbench: bt656_rx.v must reproduce gateware/model/bt656.py exactly.

Run:  .venv/bin/python -m pytest -q gateware/sim
(needs Icarus Verilog; the project keeps one in .tools/iverilog/bin)
"""
import json
import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
VECTORS = GW / 'vectors'
FIELDS = ['field', 'line_in_field', 'length', 'active_count', 'xy_corrected', 'xy_bad', 'hf_energy']


async def run_vector(dut, name, max_bytes=None):
    data = [int(x, 16) for x in (VECTORS / f'{name}.hex').read_text().split()]
    expected = json.loads((VECTORS / f'{name}.expected.json').read_text())
    if max_bytes:
        data = data[:max_bytes]
    cocotb.start_soon(Clock(dut.clk, 37, unit='ns').start())  # ~27 MHz
    dut.rst.value = 1
    dut.d.value = 0x80
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    got = []
    px_count = 0
    for b in data + [0x80] * 4:              # a few idle bytes flush the pipeline
        dut.d.value = b
        await RisingEdge(dut.clk)
        if dut.rec_valid.value:
            got.append({
                'field': int(dut.rec_field.value), 'line_in_field': int(dut.rec_line.value),
                'length': int(dut.rec_length.value), 'active_count': int(dut.rec_active.value),
                'xy_corrected': int(dut.rec_xy_corrected.value), 'xy_bad': int(dut.rec_xy_bad.value),
                'hf_energy': int(dut.rec_hf.value)})
        if dut.px_valid.value:
            px_count += 1
    if max_bytes:
        expected = expected[:len(got)]
    assert len(got) == len(expected), f'{name}: {len(got)} records, expected {len(expected)}'
    for i, (g, e) in enumerate(zip(got, expected)):
        assert g == {k: e[k] for k in FIELDS}, f'{name} line {i}: got {g}, expected {e}'
    assert px_count >= sum(e['active_count'] for e in expected)
    dut._log.info(f'{name}: {len(got)} lines match the model')


@cocotb.test()
async def pal_faults(dut):
    """Corrected timing code, truncated line and snow, all as the model reports."""
    await run_vector(dut, 'pal_faults')


@cocotb.test()
async def pal_lost_codes(dut):
    """A lost SAV and a lost EAV: lines go missing but the numbering does not shift."""
    await run_vector(dut, 'pal_lost_codes')


@cocotb.test()
async def ntsc_first_field_start(dut):
    """First 60 000 bytes of a clean NTSC frame (vertical blanking + first active lines)."""
    await run_vector(dut, 'ntsc_clean_frame', max_bytes=60000)


@cocotb.test()
async def f_stuck_fields(dut):
    """Non-interlaced source (F never changes): numbering restarts after every vertical blanking."""
    await run_vector(dut, 'f_stuck_fields')
    expected = json.loads((VECTORS / 'f_stuck_fields.expected.json').read_text())
    assert [e['line_in_field'] for e in expected] == [0, 1, 2, 3, 4, 5] * 3      # the vector tests what it claims


@cocotb.test()
async def ntsc_run_on_lines(dut):
    """Lines whose next EAV and SAV were lost run on into the next line (3156, 6588 and 3496
    active bytes): the active count saturates at 2047 instead of wrapping, so the line's first
    1440 bytes stay its first 1440 (found by sim/test_fuzz_chain.py, seed 2)."""
    await run_vector(dut, 'ntsc_run_on_lines')
    expected = json.loads((VECTORS / 'ntsc_run_on_lines.expected.json').read_text())
    assert sum(e['active_count'] == 2047 for e in expected) == 3      # the vector tests what it claims


def xy_burst_stream(n):
    """A whole line, n undecodable timing codes (each followed by 4 bytes), 200 bytes, two more lines: the
    record of the first line after the burst carries the burst's count (LOGIKGRANSKNING F7)."""
    import sys
    sys.path.insert(0, str(GW / 'model'))
    import bt656
    act = bytes(b for x in range(720) for b in (0x80, 0x50))
    bad = next(b for b, v in bt656.XY_TABLE.items() if v[3] == 'bad' and b not in (0, 255))
    return (bt656.line_bytes('ntsc', 20, act) + (bytes([0xFF, 0, 0, bad]) + bytes([0x80, 0x10] * 2)) * n
            + bytes([0x80, 0x10] * 100) + bt656.line_bytes('ntsc', 21, act) + bt656.line_bytes('ntsc', 22, act))


@cocotb.test()
async def xy_bad_burst(dut):
    """255, 256 and 257 undecodable timing codes between two lines: the count saturates at 255 (the model does
    the same). XY_EXPECT=wrap is the negative control's expectation for the 8-bit counter before 2026-10-21."""
    import sys
    sys.path.insert(0, str(GW / 'model'))
    import bt656
    cocotb.start_soon(Clock(dut.clk, 37, unit='ns').start())
    for n in (255, 256, 257):
        dut.rst.value = 1
        dut.d.value = 0x80
        for _ in range(3):
            await RisingEdge(dut.clk)
        dut.rst.value = 0
        got = []
        for b in list(xy_burst_stream(n)) + [0x80] * 4:
            dut.d.value = b
            await RisingEdge(dut.clk)
            if dut.rec_valid.value:
                got.append(int(dut.rec_xy_bad.value))
        model = [r.xy_bad for r in bt656.Receiver().feed(xy_burst_stream(n))]
        want = n % 256 if os.environ.get('XY_EXPECT') == 'wrap' else min(n, 255)
        assert got[-1] == want, (n, got)
        if os.environ.get('XY_EXPECT') != 'wrap':
            assert got == model, (n, got, model)


def test_bt656_rx_xy_bad_saturates_and_check_is_tested(tmp_path):
    """The burst test above on bt656_rx.v, and on a copy with the counter as it was (8 bits, wrapping):
    there the record after 256 bad codes says 0, which the test expects only in that run."""
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    src = (GW / 'rtl' / 'bt656_rx.v').read_text()
    fix = "if (xy_bad_cnt != 8'hFF) xy_bad_cnt <= xy_bad_cnt + 8'd1;"
    assert src.count(fix) == 1
    old = HERE / 'build' / 'bt656_rx_xy_wrap'
    old.mkdir(parents=True, exist_ok=True)
    (old / 'bt656_rx.v').write_text(src.replace(fix, "xy_bad_cnt <= xy_bad_cnt + 8'd1;"))
    for name, source, expect in (('bt656_rx_xy', GW / 'rtl' / 'bt656_rx.v', 'saturate'),
                                 ('bt656_rx_xy_wrap', old / 'bt656_rx.v', 'wrap')):
        runner = get_runner('icarus')
        runner.build(sources=[source], hdl_toplevel='bt656_rx', build_dir=HERE / 'build' / name, always=True,
                     timescale=('1ns', '1ps'))
        runner.test(hdl_toplevel='bt656_rx', test_module='test_bt656_rx', test_dir=HERE,
                    build_dir=HERE / 'build' / name, test_filter=r'\.xy_bad_burst$', extra_env={'XY_EXPECT': expect})


def test_bt656_rx_matches_model():
    """pytest entry point: build with Icarus and run the cocotb tests above."""
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    runner = get_runner('icarus')
    runner.build(sources=[GW / 'rtl' / 'bt656_rx.v'], hdl_toplevel='bt656_rx',
                 build_dir=HERE / 'build' / 'bt656_rx', always=True, timescale=('1ns', '1ps'))
    # raises if any cocotb test fails
    runner.test(hdl_toplevel='bt656_rx', test_module='test_bt656_rx',
                test_dir=HERE, build_dir=HERE / 'build' / 'bt656_rx', test_filter=r'^(?!.*xy_bad_burst)')
