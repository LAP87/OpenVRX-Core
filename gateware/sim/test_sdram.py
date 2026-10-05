"""cocotb: sdram_burst against the timing-aware SDRAM model, and the model's own checks.

tb_sdram (controller + model, SDRAM clock 225 degrees late):
  bursts_round_trip    random 8-word bursts to random rows and banks, read back in another order;
                       refresh keeps up (>= 4096 per 64 ms equivalent); no protocol error in the model.
  one_burst            one burst on benches built with other board delays: the limits of the read
                       window and of the command timing, each from both sides.
  sample_point_sweep   the run-time sample point: one clock early reads the word before, the default
                       reads the burst, one clock late reads the word after.
tb_sdram_model (the model alone, pins driven from here):
  model_*              its read timing, a legal command sequence with no error, and one negative
                       control per rule: every deliberate violation must be counted, and nothing else.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_sdram.py
"""
import os
import random
from pathlib import Path

import cocotb
import pytest
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
CLK_PS = 15432         # 64.8 MHz

RULES = ('e_row', 'e_state', 'e_cmd', 'e_init', 'e_pwrup', 'e_trcd', 'e_trp', 'e_trc', 'e_trfc', 'e_tras',
         'e_trrd', 'e_twr', 'e_tmrd', 'e_refresh', 'e_setup', 'e_hold', 'e_tck', 'e_dqx', 'e_bus')


def model_errors(mem):
    """The model's non-zero error counters; their sum must be its `errors`."""
    found = {r: int(getattr(mem, r).value) for r in RULES}
    assert sum(found.values()) == int(mem.errors.value)
    return {r: n for r, n in found.items() if n}


# ---------------------------------------------------------------- controller + model

async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PS, unit='ps').start())
    dut.resetn.value = 0
    dut.rd_sample.value = 0              # the controller's default sample point
    dut.req_valid.value = 0
    dut.req_write.value = 0
    dut.req_addr.value = 0
    dut.wdata.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.resetn.value = 1
    await RisingEdge(dut.init_done)


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


async def read_burst(dut, addr, raw=False):
    """The 8 words of a burst: integers, or the raw values (which may hold X or Z) with raw=True."""
    await wait_ready(dut)
    await FallingEdge(dut.clk)
    dut.req_valid.value, dut.req_write.value, dut.req_addr.value = 1, 0, addr
    got = []
    while len(got) < 8:
        await RisingEdge(dut.clk)
        await ReadOnly()
        accepted = int(dut.ctrl.state.value) == READ
        if dut.rdata_valid.value:
            got.append(dut.rdata.value if raw else int(dut.rdata.value))
        await FallingEdge(dut.clk)
        if accepted:
            dut.req_valid.value = 0
    return got


@cocotb.test()
async def bursts_round_trip(dut):
    await start(dut)
    rng = random.Random(3)
    data = {}
    addrs = rng.sample(range(0, 1 << 21, 8), 64)
    for a in addrs:
        words = [rng.getrandbits(32) for _ in range(8)]
        data[a] = words
        await write_burst(dut, a, words)
    t0 = get_sim_time('ns')
    refresh0 = int(dut.mem.refreshes.value)
    rng.shuffle(addrs)
    for a in addrs:
        got = await read_burst(dut, a)
        assert got == data[a], f'addr {a:#x}: got {[hex(x) for x in got]}, expected {[hex(x) for x in data[a]]}'
    t1 = get_sim_time('ns')
    refreshes = int(dut.mem.refreshes.value) - refresh0
    needed = (t1 - t0) / 64e6 * 4096          # 4096 refreshes per 64 ms
    assert refreshes >= needed, f'{refreshes} refreshes in {t1 - t0:.0f} ns, need {needed:.1f}'
    assert model_errors(dut.mem) == {}
    dut._log.info(f'64 bursts written and read back; {refreshes} refreshes in {(t1 - t0) / 1000:.1f} us')


@cocotb.test()
async def one_burst(dut):
    """One burst written and read back on a bench built with other board delays. SDRAM_EXPECT says what
    must come of it: clean data and no error, undefined data, or a set-up or hold error in the model."""
    expect = os.environ['SDRAM_EXPECT']
    await start(dut)
    words = [0x01010101 * (k + 1) for k in range(8)]
    await write_burst(dut, 0x1230, words)
    got = await read_burst(dut, 0x1230, raw=True)
    errs = model_errors(dut.mem)
    clean = all(v.is_resolvable for v in got) and [int(v) for v in got] == words
    if expect == 'clean':
        assert clean and errs == {}, (got, errs)
    elif expect == 'undefined':
        assert not any(v.is_resolvable for v in got) and errs == {}, (got, errs)
    else:
        assert set(errs) == {expect}, errs


@cocotb.test()
async def sample_point_sweep(dut):
    """rd_sample with the bench's default delays (6 ns round trip). T_RCD + CAS = 4 is the first value
    the controller accepts; 5 is its default."""
    await start(dut)
    words = [0x01010101 * (k + 1) for k in range(8)]
    await write_burst(dut, 0x1230, words)

    async def read_at(rs):
        dut.rd_sample.value = rs
        got = await read_burst(dut, 0x1230, raw=True)
        return [int(v) if v.is_resolvable else None for v in got]

    assert await read_at(4) == [None] + words[:7]         # one clock early: outputs turning on, then the word before
    assert await read_at(5) == words
    assert await read_at(6) == words[1:] + [None]         # one clock late: the next word, then a released bus
    for other in (0, 3, 8, 31):                           # not usable: the default is taken
        assert await read_at(other) == words, other
    assert model_errors(dut.mem) == {}


# ---------------------------------------------------------------- the model alone

NOP, BST, RD, WR, ACT, PRE, REF, MRS = 7, 6, 5, 4, 3, 2, 1, 0
A10 = 1 << 10
T_AC, T_OH, T_LZ = 6000, 2500, 1000      # ps, as in sdram_model.v


class Pins:
    """Drives tb_sdram_model. Every coroutine starts and ends just after a falling clock edge; pins change
    there, half a period away from the rising edge on which the SDRAM samples them."""

    clock = None                                 # the running clock task, one at a time

    def __init__(self, dut, period_ps=CLK_PS):
        self.dut, self.period = dut, period_ps

    def put(self, c, a=None, ba=None):
        d = self.dut
        d.nras.value, d.ncas.value, d.nwe.value = (c >> 2) & 1, (c >> 1) & 1, c & 1
        if a is not None:
            d.a.value = a
        if ba is not None:
            d.ba.value = ba

    async def power_on(self, wait_us=200.5):
        """Power-cycle the model (fresh state and counters), start the clock, idle the pins, wait."""
        d = self.dut
        d.mem.power_cycle.value = 1
        if Pins.clock is not None and not Pins.clock.done():
            Pins.clock.cancel()
        Pins.clock = cocotb.start_soon(Clock(d.clk, self.period, unit='ps').start())
        d.cke.value, d.ncs.value, d.dqm.value, d.dq_oe.value, d.dq_out.value = 1, 0, 0, 0, 0
        self.put(NOP, a=0, ba=0)
        await FallingEdge(d.clk)
        await FallingEdge(d.clk)
        d.mem.power_cycle.value = 0
        await Timer(wait_us, unit='us')
        await FallingEdge(d.clk)

    async def cmd(self, c, a=0, ba=0):
        """One clock with the command on the pins."""
        self.put(c, a, ba)
        await FallingEdge(self.dut.clk)
        self.put(NOP)

    async def nop(self, n):
        for _ in range(n):
            await FallingEdge(self.dut.clk)

    async def init(self, t_rp=2, t_rfc=4, t_mrd=2, mode=0x23, refreshes=2, mrs=True):
        """Precharge all, refreshes, mode register (CAS latency 2, burst length 8). Gaps in clocks."""
        await self.cmd(PRE, a=A10)
        await self.nop(t_rp - 1)
        for _ in range(refreshes):
            await self.cmd(REF)
            await self.nop(t_rfc - 1)
        if mrs:
            await self.cmd(MRS, a=mode)
            await self.nop(t_mrd - 1)

    async def write(self, ba, col, words, ap=True):
        """WRITE with word 0, the other words on the following clocks."""
        d = self.dut
        d.dq_oe.value, d.dq_out.value = 1, words[0]
        self.put(WR, a=col | (A10 if ap else 0), ba=ba)
        await FallingEdge(d.clk)
        self.put(NOP)
        for w in words[1:]:
            d.dq_out.value = w
            await FallingEdge(d.clk)
        d.dq_oe.value = 0

    async def read(self, ba, col, n=8, ap=True):
        """READ at edge e; returns DQ as it is AT edges e+2 .. e+1+n (CAS latency 2)."""
        d = self.dut
        self.put(RD, a=col | (A10 if ap else 0), ba=ba)
        await FallingEdge(d.clk)
        self.put(NOP)
        await RisingEdge(d.clk)
        out = []
        for _ in range(n):
            await RisingEdge(d.clk)
            await ReadOnly()
            out.append(d.dq.value)
        await FallingEdge(d.clk)
        return out


async def fresh(dut, period_ps=CLK_PS, wait_us=200.5, **init):
    p = Pins(dut, period_ps)
    await p.power_on(wait_us)
    await p.init(**init)
    return p


def rnd_words(seed, n=8):
    rng = random.Random(seed)
    return [rng.getrandbits(32) for _ in range(n)]


@cocotb.test()
async def model_legal_sequence(dut):
    """Bursts with auto precharge, a wrapped read, manual precharge, refresh: no error."""
    p = await fresh(dut)
    w1, w2 = rnd_words(1), rnd_words(2)
    await p.cmd(ACT, a=5, ba=1)
    await p.nop(1)                              # tRCD: 2 clocks
    await p.write(1, 0x10, w1)
    await p.nop(3)                              # auto precharge 2 clocks after the last word, then tRP
    await p.cmd(ACT, a=5, ba=1)
    await p.nop(1)
    assert [int(v) for v in await p.read(1, 0x10)] == w1
    await p.cmd(ACT, a=5, ba=1)                 # 2 clocks after the read's auto precharge
    await p.nop(1)
    assert [int(v) for v in await p.read(1, 0x13)] == w1[3:] + w1[:3]      # the burst wraps in its block
    await p.cmd(ACT, a=7, ba=2)
    await p.nop(1)
    await p.write(2, 0x40, w2, ap=False)
    await p.nop(1)                              # tWR: precharge 2 clocks after the last word
    await p.cmd(PRE, ba=2)
    await p.nop(1)
    await p.cmd(REF)
    await p.nop(3)                              # tRFC: 4 clocks
    await p.cmd(ACT, a=7, ba=2)
    await p.nop(1)
    assert [int(v) for v in await p.read(2, 0x40, ap=False)] == w2
    await p.cmd(PRE, a=A10)
    await p.nop(1)
    await p.cmd(REF)
    await p.nop(3)
    assert model_errors(dut.mem) == {}
    assert int(dut.mem.refreshes.value) == 4


@cocotb.test()
async def model_read_timing(dut):
    """CAS latency 2, READ at edge e (t = 0): word j is valid from tAC after edge e+1+j until tOH after
    edge e+2+j. Before that the outputs are off, in between they are X, after the burst they are off."""
    p = await fresh(dut)
    words = [0x11111111 * (k + 1) for k in range(8)]
    await p.cmd(ACT, a=3, ba=0)
    await p.nop(1)
    await p.write(0, 0, words)
    await p.nop(3)
    await p.cmd(ACT, a=3, ba=0)
    await p.nop(1)
    p.put(RD, a=A10, ba=0)
    await RisingEdge(dut.clk)
    t0, per = get_sim_time('ps'), p.period

    async def at(ps):
        await Timer(t0 + ps - get_sim_time('ps'), unit='ps')
        await ReadOnly()
        return str(dut.dq.value).lower()

    def word(j):
        return format(words[j], '032b')

    off, undefined = 'z' * 32, 'x' * 32
    await Timer(per // 2, unit='ps')
    p.put(NOP)
    assert await at(per + T_LZ - 10) == off
    assert await at(per + T_LZ + 10) == undefined
    assert await at(per + T_AC - 10) == undefined
    for j in range(8):
        edge = (j + 2) * per                     # the edge at which word j must be valid
        assert await at(edge - per + T_AC + 10) == word(j), j
        assert await at(edge) == word(j), j
        assert await at(edge + T_OH - 10) == word(j), j
        assert await at(edge + T_OH + 10) == undefined, j
    assert await at(9 * per + T_AC - 10) == undefined
    assert await at(9 * per + T_AC + 10) == off
    await FallingEdge(dut.clk)
    assert model_errors(dut.mem) == {}


@cocotb.test()
async def model_detects_trcd(dut):
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.read(0, 0)                          # 1 clock = 15.4 ns after ACTIVATE, tRCD is 18 ns
    assert model_errors(dut.mem) == {'e_trcd': 1}


@cocotb.test()
async def model_detects_trp(dut):
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(2)                              # tRAS met: 3 clocks = 46 ns
    await p.cmd(PRE, ba=0)
    await p.cmd(ACT, a=1, ba=0)                 # 1 clock after the precharge, tRP is 18 ns (tRC met: 62 ns)
    assert model_errors(dut.mem) == {'e_trp': 1}
    # the same after a write with auto precharge: it starts 2 clocks after the last word
    await p.nop(1)
    await p.write(0, 0, rnd_words(3))
    await p.nop(2)
    await p.cmd(ACT, a=1, ba=0)                 # 1 clock after the auto precharge started
    assert model_errors(dut.mem) == {'e_trp': 2}


@cocotb.test()
async def model_detects_tras_and_trc(dut):
    """tRC = tRAS + tRP in the datasheet (60 = 42 + 18 ns), so tRC cannot be broken alone."""
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.cmd(PRE, ba=0)                      # 1 clock after ACTIVATE, tRAS is 42 ns
    await p.nop(1)
    await p.cmd(ACT, a=1, ba=0)                 # tRP met (2 clocks); 3 clocks = 46 ns after ACTIVATE, tRC is 60 ns
    assert model_errors(dut.mem) == {'e_tras': 1, 'e_trc': 1}


@cocotb.test()
async def model_detects_trfc(dut):
    p = await fresh(dut)
    await p.cmd(REF)
    await p.nop(2)
    await p.cmd(REF)                            # 3 clocks = 46 ns after REFRESH, tRFC is 60 ns
    assert model_errors(dut.mem) == {'e_trfc': 1}
    await p.nop(3)
    await p.cmd(REF)
    await p.nop(2)
    await p.cmd(ACT, a=1, ba=0)
    assert model_errors(dut.mem) == {'e_trfc': 2}


@cocotb.test()
async def model_detects_twr(dut):
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    await p.write(0, 0, rnd_words(4), ap=False)
    await p.cmd(PRE, ba=0)                      # 1 clock after the last word, tWR is 2 clocks
    assert model_errors(dut.mem) == {'e_twr': 1}


@cocotb.test()
async def model_detects_tmrd(dut):
    p = await fresh(dut, t_mrd=1)
    await p.cmd(ACT, a=1, ba=0)                 # 1 clock after MODE REGISTER SET, tMRD is 2 clocks
    assert model_errors(dut.mem) == {'e_tmrd': 1}


@cocotb.test()
async def model_detects_trrd(dut):
    """At 64.8 MHz one clock already meets tRRD (12 ns); at 100 MHz, the fastest clock for CAS latency 2, it does not."""
    p = await fresh(dut, period_ps=10000, t_rfc=6)
    await p.cmd(ACT, a=1, ba=0)
    await p.cmd(ACT, a=1, ba=1)
    assert model_errors(dut.mem) == {'e_trrd': 1}


@cocotb.test()
async def model_detects_short_power_up(dut):
    await fresh(dut, wait_us=100)               # the four start-up commands come 100 us after power-on
    assert model_errors(dut.mem) == {'e_pwrup': 4}


@cocotb.test()
async def model_detects_incomplete_init(dut):
    p = await fresh(dut, mrs=False)             # no mode register set
    await p.cmd(ACT, a=1, ba=0)
    assert model_errors(dut.mem) == {'e_init': 1}
    p = await fresh(dut, refreshes=1)           # one refresh instead of two
    await p.cmd(ACT, a=1, ba=0)
    assert model_errors(dut.mem) == {'e_init': 1}


@cocotb.test()
async def model_detects_late_refresh(dut):
    """The bench's refresh window is 4 refreshes in 62.5 us (15.625 us each, as 4096 in 64 ms)."""
    p = await fresh(dut)

    async def refresh_every(us, n):
        for _ in range(n):
            await Timer(us, unit='us')
            await FallingEdge(dut.clk)
            await p.cmd(REF)
            await p.nop(3)

    await refresh_every(12, 8)                  # in time
    assert model_errors(dut.mem) == {}
    await refresh_every(20, 4)                  # 4 refreshes now span 56, 64, 72, 80 us: three rows late
    assert model_errors(dut.mem) == {'e_refresh': 3}
    await Timer(70, unit='us')                  # no refresh at all: reported once
    await FallingEdge(dut.clk)
    assert model_errors(dut.mem) == {'e_refresh': 4}


@cocotb.test()
async def model_detects_setup_and_hold(dut):
    """tIS 1.5 ns and tIH 1.0 ns on commands, addresses and write data."""
    p = await fresh(dut)
    half = p.period // 2
    # command: appears 1.0 ns before the edge; then one that leaves 0.5 ns after the edge
    await Timer(half - 1000, unit='ps')
    p.put(REF)
    await FallingEdge(dut.clk)
    p.put(NOP)
    await p.nop(4)
    assert model_errors(dut.mem) == {'e_setup': 1}
    p.put(REF)
    await RisingEdge(dut.clk)
    await Timer(500, unit='ps')
    p.put(NOP)
    await p.nop(5)
    assert model_errors(dut.mem) == {'e_setup': 1, 'e_hold': 1}
    # address: the row changes 1.0 ns before the ACTIVATE edge, then 0.5 ns after the READ edge
    p.put(ACT, a=1, ba=0)
    await Timer(half - 1000, unit='ps')
    dut.a.value = 2
    await FallingEdge(dut.clk)
    p.put(NOP)
    await p.nop(1)
    p.put(RD, a=A10, ba=0)
    await RisingEdge(dut.clk)
    await Timer(500, unit='ps')
    dut.a.value = 0
    await FallingEdge(dut.clk)
    p.put(NOP)
    await p.nop(12)
    assert model_errors(dut.mem) == {'e_setup': 2, 'e_hold': 2}
    # write data: word 2 arrives 1.0 ns before its edge, word 5 leaves 0.5 ns after its edge
    words = rnd_words(5)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    dut.dq_oe.value, dut.dq_out.value = 1, words[0]
    p.put(WR, a=A10, ba=0)
    await FallingEdge(dut.clk)
    p.put(NOP)
    for k in range(1, 8):
        if k == 2:
            await Timer(half - 1000, unit='ps')
        dut.dq_out.value = words[k]
        if k == 5:
            await RisingEdge(dut.clk)
            await Timer(500, unit='ps')
            dut.dq_out.value = 0
        await FallingEdge(dut.clk)
    dut.dq_oe.value = 0
    assert model_errors(dut.mem) == {'e_setup': 3, 'e_hold': 3}


@cocotb.test()
async def model_detects_bad_clock(dut):
    p = Pins(dut, 9000)                         # 111 MHz: tCK for CAS latency 2 is 10 ns
    await p.power_on(wait_us=1)
    errs = model_errors(dut.mem)
    assert set(errs) == {'e_tck'} and errs['e_tck'] > 50, errs


@cocotb.test()
async def model_detects_short_clock_high(dut):
    p = Pins(dut)
    p.put(NOP, a=0, ba=0)
    dut.cke.value, dut.ncs.value, dut.dqm.value, dut.dq_oe.value = 1, 0, 0, 0
    dut.mem.power_cycle.value = 1
    dut.clk.value = 0
    await Timer(20, unit='ns')
    dut.mem.power_cycle.value = 0
    await Timer(20, unit='ns')
    for _ in range(6):                          # 2.0 ns high (tCH is 2.5 ns), 13.4 ns low
        dut.clk.value = 1
        await Timer(2000, unit='ps')
        dut.clk.value = 0
        await Timer(13432, unit='ps')
    errs = model_errors(dut.mem)
    assert set(errs) == {'e_tck'}, errs


@cocotb.test()
async def model_detects_closed_row(dut):
    p = await fresh(dut)
    await p.read(0, 0)                          # no ACTIVATE before
    assert model_errors(dut.mem) == {'e_row': 1}
    await p.nop(2)
    await p.write(1, 0, rnd_words(6))
    assert model_errors(dut.mem) == {'e_row': 2}


@cocotb.test()
async def model_detects_illegal_state(dut):
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(4)
    await p.cmd(ACT, a=2, ba=0)                 # the bank already has an open row
    assert model_errors(dut.mem) == {'e_state': 1}
    await p.nop(4)
    await p.cmd(REF)                            # refresh needs all banks idle
    assert model_errors(dut.mem) == {'e_state': 2}
    await p.nop(4)
    p.put(RD, a=0, ba=0)                        # a burst of 8 ...
    await FallingEdge(dut.clk)
    p.put(NOP)
    await p.nop(2)
    await p.cmd(PRE, ba=0)                      # ... cut short by a precharge: not modelled
    assert model_errors(dut.mem) == {'e_state': 3}
    await p.nop(12)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    await p.write(0, 0, rnd_words(7))
    await p.cmd(ACT, a=1, ba=1)                 # 1 clock after the last word: its auto precharge has not started
    assert model_errors(dut.mem) == {'e_state': 4}


@cocotb.test()
async def model_detects_unmodelled_commands(dut):
    p = await fresh(dut)
    await p.cmd(BST)
    assert model_errors(dut.mem) == {'e_cmd': 1}
    await p.cmd(MRS, a=0x13)                    # CAS latency 1 is reserved
    await p.nop(2)
    assert model_errors(dut.mem) == {'e_cmd': 2}
    await p.cmd(MRS, a=0x27)                    # full-page burst
    await p.nop(2)
    assert model_errors(dut.mem) == {'e_cmd': 3}
    dut.cke.value = 0
    await p.nop(1)
    dut.cke.value = 1
    await p.nop(1)
    assert model_errors(dut.mem) == {'e_cmd': 4}
    dut.nwe.value = cocotb.types.Logic('X')
    await p.nop(1)
    p.put(NOP)
    await p.nop(1)
    assert model_errors(dut.mem) == {'e_cmd': 5}


@cocotb.test()
async def model_detects_undefined_write_data(dut):
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    await p.cmd(WR, a=A10, ba=0)                # nobody drives DQ during the 8 words
    await p.nop(12)
    assert model_errors(dut.mem) == {'e_dqx': 8}


@cocotb.test()
async def model_detects_bus_fight(dut):
    p = await fresh(dut)
    words = rnd_words(8)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    await p.write(0, 0, words)
    await p.nop(3)
    await p.cmd(ACT, a=1, ba=0)
    await p.nop(1)
    p.put(RD, a=A10, ba=0)
    await FallingEdge(dut.clk)
    p.put(NOP)
    await p.nop(3)
    dut.dq_out.value, dut.dq_oe.value = words[2] ^ 0xFFFFFFFF, 1      # drive against the read data
    await p.nop(2)
    dut.dq_oe.value = 0
    await p.nop(8)
    errs = model_errors(dut.mem)
    assert set(errs) == {'e_bus'}, errs


@cocotb.test()
async def model_strict_violation(dut):
    """Run only by test_sdram_model_strict_stops, on a bench built with STRICT = 1: the violation must
    end the simulation, so this test never gets to pass."""
    p = await fresh(dut)
    await p.cmd(ACT, a=1, ba=0)
    await p.read(0, 0)                          # tRCD
    await p.nop(4)


# ---------------------------------------------------------------- pytest

def _run(toplevel, test_filter, parameters=None, tag='', expect=''):
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / (toplevel + tag)
    r.build(sources=[GW / 'rtl' / 'sdram_burst.v', HERE / 'sdram_model.v', HERE / 'tb_sdram.v'],
            hdl_toplevel=toplevel, build_dir=build, always=True, timescale=('1ns', '1ps'),
            parameters=parameters or {})
    r.test(hdl_toplevel=toplevel, test_module='test_sdram', test_dir=HERE, build_dir=build,
           test_filter=test_filter, extra_env={'SDRAM_EXPECT': expect})


def test_sdram_burst():
    _run('tb_sdram', r'\.bursts_round_trip$')


def test_sdram_sample_point_sweep():
    _run('tb_sdram', r'\.sample_point_sweep$')


PHASE_PS = CLK_PS * 10 // 16           # the SDRAM clock is 225 degrees late
T_IS, T_IH = 1500, 1000                # ps, as in sdram_model.v


def test_sdram_read_window():
    """The sample point is CAS+1 clocks after READ, which is one period less the phase (5.8 ns) after the
    SDRAM clock edge at which a word is valid. Seen from that edge at the SDRAM, the word is there from
    tAC - one period until tOH. So reads are clean while the delay of the clock out plus the data back is
    between 3.29 and 15.22 ns, and undefined 0.1 ns outside either limit."""
    sample = CLK_PS - PHASE_PS
    lo, hi = sample - T_OH, sample + CLK_PS - T_AC
    assert (lo, hi) == (3287, 15219)
    clk_dly = 3000                     # the model's default; the data delay makes up the rest
    for total, expect in ((lo - 100, 'undefined'), (lo + 100, 'clean'), (hi - 100, 'clean'), (hi + 100, 'undefined')):
        _run('tb_sdram', r'\.one_burst$', {'T_DQ_DLY_PS': total - clk_dly}, f'_rt{total}', expect)


def test_sdram_command_window():
    """Commands and write data against the SDRAM clock: set-up is the phase plus the clock's delay less the
    commands' delay, hold is the rest of the period. Each limit from both sides."""
    setup_limit = PHASE_PS - T_IS                 # commands may be this much slower than the clock: 8.1 ns
    hold_limit = CLK_PS - PHASE_PS - T_IH         # the clock may be this much slower than the commands: 4.8 ns
    assert (setup_limit, hold_limit) == (8145, 4787)
    for clk_dly, out_dly, expect in ((3000, 3000 + setup_limit - 100, 'clean'), (3000, 3000 + setup_limit + 100, 'e_setup'),
                                     (hold_limit - 100, 0, 'clean'), (hold_limit + 100, 0, 'e_hold')):
        _run('tb_sdram', r'\.one_burst$', {'T_CLK_DLY_PS': clk_dly, 'T_OUT_DLY_PS': out_dly, 'T_DQ_DLY_PS': 6000 - clk_dly},
             f'_c{clk_dly}_o{out_dly}', expect)


def test_sdram_model_checks():
    _run('tb_sdram_model', r'\.model_(?!strict)')


def test_sdram_model_strict_stops():
    with pytest.raises(SystemExit):
        _run('tb_sdram_model', r'\.model_strict_violation$', {'STRICT': 1}, '_strict')
