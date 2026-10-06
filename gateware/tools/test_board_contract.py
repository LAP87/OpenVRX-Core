"""The header-pin contract of board_contract.py holds for M3, M4 and M6, and breaking it is seen."""
import sys
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GW / 'tools'))
from board_contract import shared_output_problems  # noqa: E402

TOPS = ('m3_probe', 'm4_dual_mix', 'm6_puck_proto')


def constraints(top):
    return (GW / 'boards' / 'tangnano20k.cst').read_text() + (GW / 'boards' / f'{top}.cst').read_text()


@pytest.mark.parametrize('top', TOPS)
def test_tops_meet_the_contract(top):
    assert shared_output_problems((GW / 'top' / f'{top}.v').read_text(), top, constraints(top)) == []


@pytest.mark.parametrize('broken, message', [
    ('.tvp_resetb(tvp_resetb)', '.tvp_resetb()'),                       # reset left unconnected
    ('assign rx_spi_sel_n = sel_n[0];', 'assign rx_spi_sel_n = 1\'b1;'),  # SEL held high
    ('.spi_data(rx_spi_data)', '.spi_data()'),
])
def test_negative_control_source(broken, message):
    source = (GW / 'top' / 'm4_dual_mix.v').read_text()
    assert broken in source
    assert shared_output_problems(source.replace(broken, message), 'm4_dual_mix', constraints('m4_dual_mix'))


def test_negative_control_old_pin():
    """RESETB on pin 25, as before 2026-10-05."""
    cst = constraints('m4_dual_mix').replace('IO_LOC  "tvp_resetb" 18;', 'IO_LOC  "tvp_resetb" 25;')
    problems = shared_output_problems((GW / 'top' / 'm4_dual_mix.v').read_text(), 'm4_dual_mix', cst)
    assert any('pin 18' in p for p in problems)
