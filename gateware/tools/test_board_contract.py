"""Catch the old false-green LED3/reset mapping, including overlapping drivers."""
from pathlib import Path
import pytest
from board_contract import shared_output_problems

GW = Path(__file__).resolve().parent.parent


def test_current_shared_output_roles():
    for top in ('m3_probe', 'm4_dual_mix', 'm6_puck_proto'):
        assert not shared_output_problems((GW / 'top' / f'{top}.v').read_text(), top)


@pytest.mark.parametrize('driver', ['~cur', "1'b0", '~tvp_resetb'])
def test_negative_control_wrong_reset_function(driver):
    source = (GW / 'top/m4_dual_mix.v').read_text().replace('assign led[3] = tvp_resetb;', f'assign led[3] = {driver};')
    assert any('led[3]' in p for p in shared_output_problems(source, 'm4_dual_mix'))


def test_negative_control_old_led_bus_and_duplicate_driver():
    source = (GW / 'top/m4_dual_mix.v').read_text()
    for broken in (source.replace('assign led[3] = tvp_resetb;', 'assign led = ~{locked_ok, have_video, cur, b_lines, a_lines, sec[24]};'),
                   source + '\nassign led[3] = cur;\n'):
        assert any('led[3]' in p for p in shared_output_problems(broken, 'm4_dual_mix'))
