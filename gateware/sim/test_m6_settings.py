"""M6 top: the HDMI range in the saved settings, from the onboard flash to the transmitter.

The real top (sim/tb_top_pins.v with TOP = 6 and FLASH = 1, the onboard flash being
sim/spi_flash_model.v) starts from an image with one settings record. The start scan loads it
(flash_store.v); the HDMI range bit, bit 69 of the payload (model/flash_store_ref.py), must reach
the menu (puck_ui hdmi_ltd) and the transmitter (dvi_tx_gowin rgb_full, the inverse), and since
the menu then holds what was loaded nothing is written back within the run (SAVE_MS is 3 s,
15 ms of this run). A record of the layout before the bit, with the neighbouring bit (filter VCR)
set, loads as full range.

Negative controls, copies of top/m6_puck_proto.v: the menu takes the bit from bit 70, the top
saves it in bit 68 (the loaded record then differs from what the menu holds and is written again),
rgb_full tied to 1 (the state before this). Each must fail the check.

Run: .venv/bin/python -m pytest -q gateware/sim/test_m6_settings.py"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import flash_store_ref as ref  # noqa: E402

PARAMS = dict(TOP=6, CLK_HZ=135_000, T_B_NS=300_000, T_LOCK_NS=14_000_000, T_END_NS=28_000_000, FLASH=1)
VIDEO_STOP = 600_000            # ns, PLL outputs and decoder clocks stop (as in sim/test_top_pins.py)
UNCAL = (0xFFFF, 0, 0xFFFF, 0)
# F4, MIX, BUF, TV, RSSI uncalibrated, HDMI LTD
LTD = ref.payload(3, 3, 0, 0, 0, *UNCAL, hdmi_ltd=1)
# the same with filter VCR, in the layout before the HDMI bit (byte 1 = {low_lat, filter_vcr, 6'b0})
OLD_VCR = bytes([3 << 5 | 3 << 2 | 0, 0x40]) + b''.join(v.to_bytes(2, 'big') for v in UNCAL)

# mutant: (change to top/m6_puck_proto.v, the check that must fail)
MUTANTS = {
    'load_from_bit_70': ([('.set_hdmi(saved[69])', '.set_hdmi(saved[70])')], 'menu'),
    'save_in_bit_68': ([("filter_vcr, hdmi_ltd, 5'd0, rssi_min_a", "filter_vcr, 1'b0, hdmi_ltd, 4'd0, rssi_min_a")],
                       'write'),
    'range_not_wired': ([('.rgb_full(!hdmi_ltd)', ".rgb_full(1'b1)")], 'rgb_full'),
}


def run(name, pay, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    top = (GW / 'top' / 'm6_puck_proto.v').read_text()
    for old, new in MUTANTS[mutant][0] if mutant else []:
        assert top.count(old) == 1, (mutant, old)
        top = top.replace(old, new)
    (work / 'm6_puck_proto.v').write_text(top)
    mem = bytearray(b'\xff' * 8192)
    mem[0:16] = ref.record(7, pay)                  # one record, seq 7, in slot 0
    (work / 'mem.hex').write_text(''.join(f'{b:02x}\n' for b in mem))
    src = [HERE / 'gowin_prim_stubs.v', HERE / 'i2c_slave_model.v', HERE / 'spi_flash_model.v', HERE / 'tb_top_pins.v',
           *sorted((GW / 'rtl').glob('*.v')), work / 'm6_puck_proto.v']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_top_pins',
                    *[f'-Ptb_top_pins.{k}={v}' for k, v in PARAMS.items()], *map(str, src)],
                   cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={GW / "vectors" / "ntsc_clean_frame.hex"}',
                          f'+pll_stop_ns={VIDEO_STOP}'], cwd=work, env=env, check=True, capture_output=True,
                         text=True).stdout
    assert 'RESULT done' in log, log[-2000:]
    prog = re.search(r'^FLASH programs=(\d+) erases=(\d+)$', log, re.M)
    return dict(loads=[(int(t), bytes.fromhex(p)) for t, p in re.findall(r'^SETLOAD (\d+) (\w{20})$', log, re.M)],
                hdmi=[(int(t), v) for t, v in re.findall(r'^HDMI (\d+) (\S)$', log, re.M) if v in '01'],
                rgb_full=[(int(t), v) for t, v in re.findall(r'^RGBFULL (\d+) (\S)$', log, re.M) if v in '01'],
                programs=int(prog[1]), erases=int(prog[2]))


def check(r, pay):
    """The record loads once; the menu and rgb_full take its HDMI range at the load (from reset: FULL)
    and keep it; nothing is written."""
    assert [p for _, p in r['loads']] == [pay], r['loads']
    t_load = r['loads'][0][0]
    ltd = ref.settings(pay)['hdmi_ltd']
    want = ['0', '1'] if ltd else ['0']
    assert [v for _, v in r['hdmi']] == want, ('menu', r['hdmi'])
    assert [v for _, v in r['rgb_full']] == ['1', '0'][:len(want)], ('rgb_full', r['rgb_full'])
    if ltd:                                        # the menu takes set_load on the clock edge it is printed at
        assert t_load <= r['hdmi'][1][0] < t_load + 1000 and t_load <= r['rgb_full'][1][0] < t_load + 1000, (
            t_load, r['hdmi'], r['rgb_full'])
    assert (r['programs'], r['erases']) == (0, 0), ('write', 'what was loaded is what the menu holds')


@pytest.mark.parametrize('case', ['ltd', 'old_vcr'])
def test_m6_loads_the_hdmi_range(case):
    pay = {'ltd': LTD, 'old_vcr': OLD_VCR}[case]
    assert ref.settings(OLD_VCR)['hdmi_ltd'] == 0 and ref.settings(OLD_VCR)['filter_vcr'] == 1
    check(run(f'tb_m6_settings_{case}', pay), pay)


@pytest.mark.parametrize('mutant', sorted(MUTANTS))
def test_m6_settings_negative_control(mutant):
    with pytest.raises(AssertionError, match=MUTANTS[mutant][1]):
        check(run(f'tb_m6_settings_{mutant}', LTD, mutant), LTD)
