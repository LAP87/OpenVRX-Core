"""cocotb: sdram_burst against the behavioural SDRAM model.

Writes random 8-word bursts to random rows/banks, reads them back in a
different order, and checks refresh keeps up (>= 4096 per 64 ms equivalent).

Run:  .venv/bin/python -m pytest -q gateware/sim
"""
import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
CLK_NS = 15.4          # 64.8 MHz


async def wait_ready(dut):
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if dut.req_ready.value:
            return


IDLE, READ, WRITE = 2, 3, 4


async def write_burst(dut, addr, words):
    await wait_ready(dut)
    await FallingEdge(dut.clk)
    dut.req_valid.value, dut.req_write.value, dut.req_addr.value = 1, 1, addr
    dut.wdata.value = words[0]
    k = 0
    # wdata_take high during a cycle = the word on wdata is captured at the end of
    # that cycle (FIFO "pop" semantics): sample it mid-cycle, advance after the edge.
    while k < 8:
        await FallingEdge(dut.clk)
        take = int(dut.wdata_take.value)
        if int(dut.ctrl.state.value) == WRITE:
            dut.req_valid.value = 0          # held until the controller took the request
        await RisingEdge(dut.clk)
        if take:
            k += 1
            dut.wdata.value = words[k] if k < 8 else 0


async def read_burst(dut, addr):
    await wait_ready(dut)
    await FallingEdge(dut.clk)
    dut.req_valid.value, dut.req_write.value, dut.req_addr.value = 1, 0, addr
    got = []
    while len(got) < 8:
        await RisingEdge(dut.clk)
        await ReadOnly()
        accepted = int(dut.ctrl.state.value) == READ
        if dut.rdata_valid.value:
            got.append(int(dut.rdata.value))
        await FallingEdge(dut.clk)
        if accepted:
            dut.req_valid.value = 0
    return got


@cocotb.test()
async def bursts_round_trip(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit='ns').start())
    dut.resetn.value = 0
    dut.req_valid.value = 0
    dut.req_write.value = 0
    dut.req_addr.value = 0
    dut.wdata.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.resetn.value = 1
    while not dut.init_done.value:
        await RisingEdge(dut.clk)
    rng = random.Random(3)
    data = {}
    addrs = rng.sample(range(0, 1 << 21, 8), 64)
    for a in addrs:
        words = [rng.getrandbits(32) for _ in range(8)]
        data[a] = words
        await write_burst(dut, a, words)
    t0 = cocotb.utils.get_sim_time('ns')
    refresh0 = int(dut.mem.refreshes.value)
    rng.shuffle(addrs)
    for a in addrs:
        got = await read_burst(dut, a)
        assert got == data[a], f'addr {a:#x}: got {[hex(x) for x in got]}, expected {[hex(x) for x in data[a]]}'
    t1 = cocotb.utils.get_sim_time('ns')
    refreshes = int(dut.mem.refreshes.value) - refresh0
    needed = (t1 - t0) / 64e6 * 4096          # 4096 refreshes per 64 ms
    assert refreshes >= needed, f'{refreshes} refreshes in {t1 - t0:.0f} ns, need {needed:.1f}'
    assert int(dut.mem.errors.value) == 0, 'access to a closed row'
    dut._log.info(f'64 bursts written and read back; {refreshes} refreshes in {(t1 - t0) / 1000:.1f} us')


def test_sdram_burst():
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / 'tb_sdram'
    r.build(sources=[GW / 'rtl' / 'sdram_burst.v', HERE / 'sdram_model.v', HERE / 'tb_sdram.v'],
            hdl_toplevel='tb_sdram', build_dir=build, always=True, timescale=('1ns', '1ps'))
    r.test(hdl_toplevel='tb_sdram', test_module='test_sdram', test_dir=HERE, build_dir=build)
