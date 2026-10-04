"""cocotb tests for tmds_encoder.v (vs a Python DVI 1.0 reference) and video_timing.v.

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
CTRL = {0: 0b1101010100, 1: 0b0010101011, 2: 0b0101010100, 3: 0b1010101011}


class TmdsRef:
    """DVI 1.0 spec section 3.3.3, straight from the flowchart."""

    def __init__(self):
        self.cnt = 0

    def encode(self, de, d, ctrl):
        if not de:
            self.cnt = 0
            return CTRL[ctrl]
        n1d = bin(d).count('1')
        xnor = n1d > 4 or (n1d == 4 and (d & 1) == 0)
        qm = d & 1
        for i in range(1, 8):
            prev, bit = (qm >> (i - 1)) & 1, (d >> i) & 1
            qm |= ((1 - (prev ^ bit)) if xnor else (prev ^ bit)) << i
        qm8 = 0 if xnor else 1
        n1 = bin(qm & 0xFF).count('1')
        n0 = 8 - n1
        if self.cnt == 0 or n1 == n0:
            q = ((1 - qm8) << 9) | (qm8 << 8) | (qm & 0xFF if qm8 else (~qm) & 0xFF)
            self.cnt += (n1 - n0) if qm8 else (n0 - n1)
        elif (self.cnt > 0 and n1 > n0) or (self.cnt < 0 and n0 > n1):
            q = (1 << 9) | (qm8 << 8) | ((~qm) & 0xFF)
            self.cnt += 2 * qm8 + (n0 - n1)
        else:
            q = (qm8 << 8) | (qm & 0xFF)
            self.cnt += -2 * (1 - qm8) + (n1 - n0)
        return q


def tmds_decode(q):
    """Inverse used to prove the symbols carry the data."""
    d = q & 0xFF
    if q & 0x200:
        d ^= 0xFF
    out = d & 1
    for i in range(1, 8):
        b = ((d >> i) ^ (d >> (i - 1))) & 1
        out |= (b if q & 0x100 else 1 - b) << i
    return out


@cocotb.test()
async def tmds_matches_reference(dut):
    if not hasattr(dut, 'q'):
        return
    cocotb.start_soon(Clock(dut.clk, 10, unit='ns').start())
    ref, rng = TmdsRef(), random.Random(7)
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    stim = [(1, rng.randrange(256), 0) if rng.random() > 0.1 else (0, 0, rng.randrange(4)) for _ in range(4000)]
    stim += [(1, v, 0) for v in (0, 255, 0x10, 0xEB, 0x80) * 40]   # flat colours stress DC balance
    disparity, worst = 0, 0
    for i, (de, d, c) in enumerate(stim):
        await FallingEdge(dut.clk)
        dut.rst.value = 0
        dut.de.value, dut.data.value, dut.ctrl.value = de, d, c
        await RisingEdge(dut.clk)
        await ReadOnly()
        q, q_ref = int(dut.q.value), ref.encode(de, d, c)
        assert q == q_ref, f'symbol {i}: got {q:010b}, expected {q_ref:010b} (de={de} d={d})'
        if de:
            assert tmds_decode(q) == d
            disparity += bin(q).count('1') - 5
            worst = max(worst, abs(disparity))
        else:
            disparity = 0
    assert worst <= 10, f'running disparity drifted to {worst}'


@cocotb.test()
async def timing_counts(dut):
    if not hasattr(dut, 'frame_start'):
        return
    cocotb.start_soon(Clock(dut.clk, 10, unit='ns').start())
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)        # registered outputs are defined from here on
    H, V = (16 + 2 + 3 + 4), (6 + 1 + 2 + 3)       # parameters set in the runner below
    de_total, hs_total, vs_total, fs = 0, 0, 0, 0
    for _ in range(H * V * 2):       # exactly two frames
        await RisingEdge(dut.clk)
        await ReadOnly()
        de_total += int(dut.de.value)
        hs_total += int(dut.hsync.value)
        vs_total += int(dut.vsync.value)
        fs += int(dut.frame_start.value)
    assert fs == 2
    assert de_total == 2 * 16 * 6
    assert hs_total == 2 * V * 3
    assert vs_total == 2 * 2 * H


def _runner(top, sources, parameters=None):
    from cocotb_tools.runner import get_runner
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        os.environ['PATH'] = f'{iverilog_bin}{os.pathsep}' + os.environ['PATH']
    r = get_runner('icarus')
    build = HERE / 'build' / top
    r.build(sources=sources, hdl_toplevel=top, build_dir=build, always=True,
            timescale=('1ns', '1ps'), parameters=parameters or {})
    r.test(hdl_toplevel=top, test_module='test_video', test_dir=HERE, build_dir=build)


def test_tmds_encoder():
    _runner('tmds_encoder', [GW / 'rtl' / 'tmds_encoder.v'])


def test_video_timing():
    _runner('video_timing', [GW / 'rtl' / 'video_timing.v'],
            dict(H_ACTIVE=16, H_FP=2, H_SYNC=3, H_BP=4, V_ACTIVE=6, V_FP=1, V_SYNC=2, V_BP=3))
