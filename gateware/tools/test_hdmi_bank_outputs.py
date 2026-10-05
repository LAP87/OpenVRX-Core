"""No single-ended output may share an I/O bank with the HDMI (TMDS) pins.

Apicula 0.32 sets BANK_VCCIO for every IOB in a bank from the bank's
single-ended outputs (1.2 V when there are none), and that changes how the
true-LVDS TMDS pairs are packed. M4/M6 once had the decoders' RESETB on
pin 25, in the bank of the TMDS clock pair (OpenVRX-Core issue #6).

For every top with a tmds_clk_p port: read its output/inout ports from the
Verilog, their pins from tangnano20k.cst + boards/<top>.cst, and the bank of
each pin from Apicula's chip database. The old RESETB placement is the
negative control."""
import os
import re
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent


def ports(top_v):
    """{port: direction} for output/inout ports, vectors expanded to name[i]."""
    out = {}
    for m in re.finditer(r'^\s*(output|inout)\s+(?:wire|reg)?\s*(\[(\d+):(\d+)\])?\s*([^;]*?)\s*(?:,\s*)?(?://.*)?$',
                         top_v, re.M):
        direction, _, hi, lo, names = m.groups()
        for name in re.split(r'\s*,\s*', names.strip().rstrip(',')):
            if not re.fullmatch(r'\w+', name):
                continue
            if hi is None:
                out[name] = direction
            else:
                for i in range(min(int(hi), int(lo)), max(int(hi), int(lo)) + 1):
                    out[f'{name}[{i}]'] = direction
    return out


def locs(cst):
    return {m[1]: m[2] for m in re.finditer(r'IO_LOC\s+"([^"]+)"\s+(\S+);', cst) for m in [m]}


def offenders(port_dirs, port_locs, bank_of):
    tmds = [p for p in port_locs if p.startswith('tmds_') and p in port_dirs]
    tmds_banks = {bank_of(port_locs[p]) for p in tmds}
    bad = []
    for p, d in port_dirs.items():
        if p.startswith('tmds_') or p not in port_locs:
            continue
        b = bank_of(port_locs[p])
        if b in tmds_banks:
            bad.append((p, port_locs[p], b))
    return tmds_banks, bad


@pytest.fixture(scope='module')
def bank_of():
    from apycula import chipdb
    db = chipdb.load_chipdb(os.path.join(os.path.dirname(chipdb.__file__), 'GW2A-18C.msgpack.xz'))
    pinout = db.pinout['GW2AR-18C']['QFN88']

    def bank(loc):
        name = pinout[loc][0] if loc in pinout else loc       # header pin number, or an IOB name (SDRAM)
        return db.pin_bank.get(name)
    return bank


def test_no_single_ended_output_in_the_tmds_banks(bank_of):
    base = (GW / 'boards' / 'tangnano20k.cst').read_text()
    checked = 0
    for top in sorted((GW / 'top').glob('*.v')):
        text = top.read_text()
        p = ports(text)
        if 'tmds_clk_p' not in p:
            continue
        cst = base + ((GW / 'boards' / f'{top.stem}.cst').read_text() if (GW / 'boards' / f'{top.stem}.cst').exists() else '')
        tmds_banks, bad = offenders(p, locs(cst), bank_of)
        assert tmds_banks and None not in tmds_banks, (top.stem, tmds_banks)
        assert not bad, f'{top.stem}: single-ended outputs in TMDS bank(s) {tmds_banks}: {bad}'
        checked += 1
    assert checked >= 5


def test_negative_control_old_resetb_on_pin_25(bank_of):
    """The M4 placement before the fix must be caught."""
    base = (GW / 'boards' / 'tangnano20k.cst').read_text()
    p = {'tmds_clk_p': 'output', 'tmds_clk_n': 'output', 'tvp_resetb': 'output', 'led[0]': 'output'}
    _, bad = offenders(p, locs(base + 'IO_LOC  "tvp_resetb" 25;\n'), bank_of)
    assert [b[0] for b in bad] == ['tvp_resetb'], bad
