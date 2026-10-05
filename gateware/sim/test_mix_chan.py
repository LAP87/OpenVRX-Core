"""Whole-line loss and VBI health, with deliberately broken RTL controls."""
import os
from pathlib import Path
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent


def simulate(work, source):
    work.mkdir()
    rtl = work / 'mix_chan.v'
    rtl.write_text(source)
    env = dict(os.environ)
    env['PATH'] = str(GW.parent / '.tools/iverilog/bin') + os.pathsep + env['PATH']
    subprocess.run(['iverilog', '-g2012', '-s', 'tb_mix_chan', '-o', 'sim.vvp',
                    str(rtl), str(GW / 'rtl/dual_clock_ram.v'), str(HERE / 'tb_mix_chan.v')],
                   cwd=work, env=env, check=True, capture_output=True, text=True)
    return subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, capture_output=True, text=True)


def test_line_ring_scoreboard(tmp_path):
    result = simulate(tmp_path / 'good', (GW / 'rtl/mix_chan.v').read_text())
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ring scoreboard passed' in result.stdout


@pytest.mark.parametrize('fault', ['partial', 'timeout', 'capture_bad'])
def test_negative_control_line_ring(tmp_path, fault):
    source = (GW / 'rtl/mix_chan.v').read_text()
    if fault == 'partial':
        source = source.replace('else if (word_matches && !full)', 'else if (!full)')
        source = source.replace('!full && assembling && !discard &&', '!full && assembling &&')
        message = 'partial full line published'
    elif fault == 'timeout':
        source = source.replace('parameter TIMEOUT = 262144', 'parameter TIMEOUT = 65536')
        message = 'healthy channel died in VBI'
    else:
        assert 'wire bad_in = ext_s[1] ||' in source
        source = source.replace('wire bad_in = ext_s[1] ||', 'wire bad_in =')
        message = 'captured fault cleared on recovery'
    result = simulate(tmp_path / fault, source)
    assert result.returncode != 0 and message in result.stdout, result.stdout + result.stderr
