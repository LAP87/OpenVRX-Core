"""cocotb: the memory test (rtl/memtest_core.v, the logic of top/m2a_memtest.v) against the timing-aware
SDRAM model. The UART output is decoded here bit by bit. The report must name the sample point that
works for the bench's board delays and SDRAM clock phase, and only that one:

  clock out + data back              phase   line without errors
  3 + 3 ns (the model's assumption)  225     rs=5, the controller's default
  0                                  225     none: every sample point falls where the outputs change
  0                                  180     rs=4
  1 + 1 ns                           225     none
  1 + 1 ns                           270     rs=5
  3 + 17 ns                          225     rs=6

clean_points() derives the last column from tAC, tOH and the clock period; one bench is built per row.
A line from a working sample point must be all zeros, and with `inject` it must show the one deliberate
error: once, at DQ0, in word 5 of the burst. Every other line must count every word as wrong.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_memtest.py
"""
import os
import re
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
CLK_PS = 15432                 # 64.8 MHz
FREQ = 64_800_000
SIM_BAUD = 8_100_000           # tb_memtest's default: 8 clocks per bit
AW = 9                         # tb_memtest's default: 512 words
T_AC, T_OH = 6000, 2500        # ps, as in sdram_model.v
FIRST_RS = 4                   # T_RCD + CAS
LINE = re.compile(r'M rs=(\d) pass=([0-9A-F]{4}) err=([0-9A-F]{8}) bits=([0-9A-F]{32}) pos=([0-9A-F]{8})')


def clean_points(delay_ps, phase16=10):
    """Sample points that read every word of a burst, for a delay of clock out plus data back.
    Sample point FIRST_RS + n lies n periods less the clock phase after the SDRAM clock edge at which a
    word is valid; the word is at the controller from tAC - one period until tOH, both plus the delay."""
    phase = CLK_PS * phase16 // 16
    return [FIRST_RS + n for n in range(3)
            if T_AC - CLK_PS + delay_ps < n * CLK_PS - phase < T_OH + delay_ps]


class Report:
    def __init__(self, text):
        m = LINE.fullmatch(text)
        assert m and len(text) == 80, repr(text)
        self.rs, self.npass, self.err = int(m[1]), int(m[2], 16), int(m[3], 16)
        self.bits = [int(c, 16) for c in reversed(m[4])]       # index = DQ number
        self.pos = [int(c, 16) for c in m[5]]                  # index = word in the burst


def count_range(digit):
    """A digit is the size of a count: 0 for none, n for 2^(n-1) .. 2^n - 1."""
    return (0, 0) if digit == 0 else (1 << (digit - 1), (1 << digit) - 1)


def check(line, clean, injected):
    words = 2 << AW                                            # two patterns
    if line.rs in clean and not injected:
        assert line.err == 0 and not any(line.bits) and not any(line.pos), vars(line)
    elif line.rs in clean:
        assert line.err == 1 and line.bits == [1] + [0] * 31 and line.pos == [0, 0, 0, 0, 0, 1, 0, 0], vars(line)
    else:                                                      # every word wrong, 128 at each position
        assert line.err == words and line.pos == [AW - 1] * 8 and all(line.bits), vars(line)
    # the digits against err: a wrong word is counted at one position and has 1 to 32 wrong bits
    assert sum(count_range(d)[0] for d in line.pos) <= line.err <= sum(count_range(d)[1] for d in line.pos)
    assert sum(count_range(d)[0] for d in line.bits) <= 32 * line.err
    assert sum(count_range(d)[1] for d in line.bits) >= line.err


async def read_line(dut, bit_ps):
    """8N1 receiver on uart_txd: bytes up to CR LF, each bit sampled in its middle."""
    data = bytearray()
    while not data.endswith(b'\r\n'):
        await FallingEdge(dut.uart_txd)
        await Timer(bit_ps * 3 // 2, unit='ps')
        byte = 0
        for i in range(8):
            byte |= int(dut.uart_txd.value) << i
            await Timer(bit_ps, unit='ps')
        assert int(dut.uart_txd.value) == 1, 'no stop bit'
        data.append(byte)
    return data[:-2].decode('ascii')


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PS, unit='ps').start())
    dut.rst.value = 1
    dut.inject.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


@cocotb.test()
async def report(dut):
    clean = [int(x) for x in os.environ['MEMTEST_CLEAN'].split(',') if x]
    bit_ps = FREQ // SIM_BAUD * CLK_PS
    await start(dut)

    async def lines(n):
        got = []
        for _ in range(n):
            text = await read_line(dut, bit_ps)
            dut._log.info(text)
            got.append(Report(text))
        return got

    first = await lines(3)
    assert [(r.rs, r.npass) for r in first] == [(4, 0), (5, 0), (6, 0)]
    for r in first:
        check(r, clean, injected=False)
    assert int(dut.init_done.value) == 1
    assert int(dut.fail_default.value) == (5 not in clean)     # the LED for the default sample point

    dut.inject.value = 1
    await lines(1)                                             # rs=4 of pass 1 was being written already
    second = await lines(3)
    assert [(r.rs, r.npass) for r in second] == [(5, 1), (6, 1), (4, 2)]
    for r in second:
        check(r, clean, injected=True)

    assert int(dut.mem.errors.value) == 0, 'SDRAM protocol error'
    assert int(dut.x_samples.value) == 0, 'X or Z reached the comparison'


@cocotb.test()
async def baud_rate(dut):
    """Bench built with BAUD = 115200: the start bit of the first character ('M', bit 0 is 1) must last
    FREQ / BAUD clocks, within 0.5 % of 115200 baud."""
    await start(dut)
    await FallingEdge(dut.uart_txd)
    t0 = get_sim_time('ps')
    await RisingEdge(dut.uart_txd)
    bit_ps = get_sim_time('ps') - t0
    assert bit_ps == FREQ // 115200 * CLK_PS, bit_ps
    assert abs(1e12 / bit_ps / 115200 - 1) < 0.005, 1e12 / bit_ps


def _run(parameters, clean, tag, test_filter=r'\.report$'):
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / ('tb_memtest' + tag)
    rtl = [GW / 'rtl' / n for n in ('sdram_burst.v', 'uart_tx.v', 'memtest_core.v')]
    r.build(sources=rtl + [HERE / 'sdram_model.v', HERE / 'tb_memtest.v'], hdl_toplevel='tb_memtest',
            build_dir=build, always=True, timescale=('1ns', '1ps'), parameters=parameters)
    r.test(hdl_toplevel='tb_memtest', test_module='test_memtest', test_dir=HERE, build_dir=build,
           test_filter=test_filter, extra_env={'MEMTEST_CLEAN': ','.join(map(str, clean))})


def _delays(clk_ps, dq_ps):
    return {'T_CLK_DLY_PS': clk_ps, 'T_DQ_DLY_PS': dq_ps, 'T_OUT_DLY_PS': clk_ps}


def test_memtest_default_delays():
    """The model's assumed delays: the controller's default sample point is the one clean line."""
    assert clean_points(6000) == [5]
    _run({}, [5], '')


def test_memtest_zero_delays():
    """No board delay: errors at the default sample point, and at 225 degrees at the other two as well
    (rs=4 samples 5.8 ns after the SDRAM clock edge, the data are valid after 6 ns). At 180 degrees rs=4
    is clean."""
    assert clean_points(0) == [] and clean_points(0, 8) == [4]
    _run(_delays(0, 0), [], '_d0')
    _run({**_delays(0, 0), 'PHASE16': 8}, [4], '_d0_p8')


def test_memtest_short_delays():
    """2 ns in all: no sample point at 225 degrees, the default one at 270 degrees."""
    assert clean_points(2000) == [] and clean_points(2000, 12) == [5]
    _run(_delays(1000, 1000), [], '_d2')
    _run({**_delays(1000, 1000), 'PHASE16': 12}, [5], '_d2_p12')


def test_memtest_long_delays():
    """20 ns in all: errors at the default sample point, rs=6 is clean."""
    assert clean_points(20000) == [6]
    _run(_delays(3000, 17000), [6], '_d20')


def test_memtest_uart_baud():
    _run({'BAUD': 115200}, [], '_baud', r'\.baud_rate$')
