"""Zero-count display fallback against the independent framebuffer mapping model."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import fb_ref as fb  # noqa: E402


def display_trace(tmp_path, v_active, display_source=None):
    work = tmp_path / f'active_{v_active}'
    work.mkdir()
    env = dict(os.environ)
    bundled = PROJECT / '.tools' / 'iverilog' / 'bin'
    if bundled.exists():
        env['PATH'] = f'{bundled}{os.pathsep}' + env.get('PATH', '')
    compiler = shutil.which('iverilog', path=env.get('PATH'))
    runtime = shutil.which('vvp', path=env.get('PATH'))
    if not compiler or not runtime:
        pytest.skip('Icarus Verilog is not installed')

    sources = [GW / 'rtl' / 'cdc_sync.v', GW / 'rtl' / 'ycbcr2rgb.v']
    display = display_source or GW / 'rtl' / 'fb_display.v'
    bench = HERE / 'tb_fb_display_default.v'
    subprocess.run([
        compiler, '-g2012', '-s', 'tb_fb_display_default',
        f'-Ptb_fb_display_default.V_ACTIVE={v_active}', '-o', 'sim.vvp',
        *map(str, sources), str(display), str(bench),
    ], cwd=work, env=env, check=True, capture_output=True, text=True)
    result = subprocess.run([runtime, '-n', 'sim.vvp'], cwd=work, env=env,
                            check=True, capture_output=True, text=True)
    trace = []
    for row in result.stdout.splitlines():
        fields = row.split()
        if fields and fields[0] == 'TRACE':
            y, lines, source, slot = map(int, fields[1:])
            trace.append((y, lines, source, slot))
    return trace


def assert_reference_mapping(trace, v_active, expected_lines):
    assert len(trace) == v_active, f'captured {len(trace)} of {v_active} active lines'
    for y, lines, source, slot in trace:
        assert lines == expected_lines, f'line {y}: display used {lines} source lines'
        expected = fb.src_line(y, expected_lines, v_active, low=False)
        assert source == expected, f'line {y}: source {source}, fb_ref.src_line gives {expected}'
        assert slot == (expected & 0xF), f'line {y}: ring slot {slot}, expected {expected & 0xF}'


@pytest.mark.parametrize(('v_active', 'expected_lines'), [(72, 24), (720, 240)])
def test_zero_low_count_uses_geometry_default_and_model_ring_mapping(tmp_path, v_active, expected_lines):
    """The scaled LOW ring maps to 24 lines; the physical 720-line default stays 240."""
    trace = display_trace(tmp_path, v_active)
    assert_reference_mapping(trace, v_active, expected_lines)


def test_fixed_240_fallback_fails_scaled_source_mapping(tmp_path):
    """Negative control: the old 240-line fallback misaddresses a 72-line geometry."""
    source = (GW / 'rtl' / 'fb_display.v').read_text()
    old_default = "localparam [9:0] DEFAULT_LINES = V_ACTIVE / 3;"
    assert source.count(old_default) == 1
    mutant = tmp_path / 'fb_display_fixed_240.v'
    mutant.write_text(source.replace(old_default, "localparam [9:0] DEFAULT_LINES = 10'd240;"))

    trace = display_trace(tmp_path, 72, mutant)
    assert len(trace) == 72, f'captured {len(trace)} of 72 active lines'
    expected = [(y, fb.src_line(y, 24, 72, low=False)) for y in range(72)]
    mismatches = [(y, source, slot, model) for (y, _, source, slot), (y2, model) in zip(trace, expected)
                  if y != y2 or source != model or slot != (model & 0xF)]
    assert mismatches, 'fixed-240 fallback unexpectedly matched the scaled reference mapping'
