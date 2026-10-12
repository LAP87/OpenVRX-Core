"""Exercise the build shell with bounded tool doubles, including failed runs.

These tests certify artifact handling, not synthesis or hardware timing.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

GW = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which('bash') is None or shutil.which('flock') is None,
                                reason='the build shell needs bash and flock')

STUB = r'''
import json, os, re, sys
from pathlib import Path
stage = Path(sys.argv[0]).name
root = Path(sys.argv[0]).resolve().parents[2]
with (root / 'gateware/build/calls.log').open('a') as f:
    f.write(stage + '\n')
failure = os.environ.get('BUILD_TEST_FAILURE', '')
def arg(name): return sys.argv[sys.argv.index(name) + 1]
if stage == 'yowasp-yosys':
    Path(arg('-l')).write_text('new synthesis log\n')
    if failure == 'synthesis': sys.exit(2)
    command = arg('-p')
    source = Path(re.search(r'(\S+/rtl/fixture.v)\s', command)[1])
    original = (root / 'gateware/rtl/fixture.v').read_text()
    if failure == 'transient_source':
        (root / 'gateware/rtl/fixture.v').write_text('// temporary edit during synthesis\n')
    compiled = source.read_text()
    (root / 'gateware/rtl/fixture.v').write_text(original)
    Path(re.search(r'-json ([^;\s]+)', command)[1]).write_text(json.dumps({'compiled_source': compiled}))
    Path(re.search(r'tee -o (\S+)', command)[1]).write_text('new statistics\n')
elif stage == 'yowasp-nextpnr-himbaechel-gowin':
    (root / 'gateware/build/nextpnr.args').write_text(' '.join(sys.argv[1:]) + ' ')
    log = "Info: Max frequency for clock 'clk': 120.00 MHz (PASS at 75.00 MHz)\nRouting...\n"
    log += "Info: Max frequency for clock 'clk': 90.00 MHz (PASS at 75.00 MHz)\n"
    if failure == 'routing': log += 'ERROR: routing failed\n'
    if failure == 'error_exit_zero': log += 'ERROR: route incomplete\n'
    if failure == 'timing': log = log.replace('90.00 MHz (PASS', '40.00 MHz (FAIL')
    if failure == 'no_timing': log = 'Info: no timing table\n'
    Path(arg('--log')).write_text(log)
    if failure != 'no_pnr_output': Path(arg('--write')).write_text('{"fresh": true}')
    if failure == 'routing': sys.exit(3)
elif stage == 'gowin_pack':
    if not Path(sys.argv[-1]).is_file(): sys.exit(4)
    if failure != 'no_packed_output':
        data = b'' if failure == 'empty_bitstream' else (b'partial' if failure == 'packing' else b'new packed bitstream')
        Path(arg('-o')).write_bytes(data)
    if failure == 'packing': sys.exit(5)
    if failure == 'changed_source':
        with (root / 'gateware/rtl/fixture.v').open('a') as f: f.write('// changed during build\n')
'''


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    for rel in ('gateware/rtl', 'gateware/top', 'gateware/boards', 'gateware/tools', 'gateware/build', '.venv/bin'):
        (root / rel).mkdir(parents=True)
    for rel in ('build.sh', 'tools/build_manifest.py'):
        shutil.copy2(GW / rel, root / 'gateware' / rel)
    (root / 'gateware/rtl/fixture.v').write_text('module fixture; endmodule\n')
    (root / 'gateware/rtl/fixture.vh').write_text('// included source\n')
    (root / 'gateware/top/demo.v').write_text('module demo; endmodule\n')
    (root / 'gateware/top/m4_dual_mix.v').write_text('module m4_dual_mix; endmodule\n')
    (root / 'gateware/boards/tangnano20k.cst').write_text('IO_LOC "clk" 4;\n')
    (root / 'gateware/boards/demo.seed').write_text('2\n')
    (root / '.venv/bin/python').symlink_to(sys.executable)
    for name in ('yowasp-yosys', 'yowasp-nextpnr-himbaechel-gowin', 'gowin_pack'):
        p = root / '.venv/bin' / name
        p.write_text(f'#!{sys.executable}\n' + STUB)
        p.chmod(0o755)
    old = root / 'gateware/build/demo.fs'
    old.write_bytes(b'old successful bitstream')
    (old.parent / 'demo.pnr.json').write_text('{"stale": true}')
    (old.parent / 'demo.build.json').write_text('{"stale": true}')
    return root


def build(project, failure='', top='demo', **settings):
    env = {k: v for k, v in os.environ.items() if k not in ('PULL', 'SDRAM_PHASE', 'SEED', 'FREQ_MHZ', 'IOREG')}
    env.update(settings, BUILD_TEST_FAILURE=failure)
    return subprocess.run(['bash', str(project / 'gateware/build.sh'), top],
                          cwd=project, env=env, capture_output=True, text=True, timeout=20)


def verify(project):
    return subprocess.run([sys.executable, str(project / 'gateware/tools/build_manifest.py'), 'verify',
                           str(project / 'gateware/build/demo.build.json'), '--root', str(project)],
                          capture_output=True, text=True, timeout=20)


def test_success_publishes_fresh_artifacts_and_last_clock_result(project):
    r = build(project)
    assert r.returncode == 0, r.stdout + r.stderr
    out = project / 'gateware/build'
    assert (out / 'demo.fs').read_bytes() == b'new packed bitstream'
    archived = list((out / 'previous').glob('demo.*/demo.fs'))
    assert len(archived) == 1 and archived[0].read_bytes() == b'old successful bitstream'
    record = json.loads((out / 'demo.build.json').read_text())
    assert record['options']['seed'] == '2'
    assert record['timing']['clk'] == dict(max_mhz=90.0, required_mhz=75.0, passed=True)
    assert 'gateware/rtl/fixture.vh' in record['inputs']
    assert record['artifacts']['demo.fs'] == hashlib.sha256((out / 'demo.fs').read_bytes()).hexdigest()
    assert json.loads((out / 'demo.pnr.json').read_text()) == {'fresh': True}
    assert not list(out.glob('.demo.*'))
    checked = verify(project)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize('changed', ['gateware/build/demo.fs', 'gateware/build/demo.cst', 'gateware/rtl/fixture.vh'])
def test_verification_rejects_a_changed_result_or_current_source(project, changed):
    assert build(project).returncode == 0
    with (project / changed).open('ab') as f:
        f.write(b'changed')
    checked = verify(project)
    assert checked.returncode != 0
    assert 'does not match' in checked.stderr or 'do not match' in checked.stderr


def test_compiler_reads_the_snapshot_when_a_live_edit_is_restored(project):
    original = (project / 'gateware/rtl/fixture.v').read_text()
    assert build(project, 'transient_source').returncode == 0
    synth = project / 'gateware/build/demo.synth.json'
    assert json.loads(synth.read_text())['compiled_source'] == original
    assert verify(project).returncode == 0


def test_snapshot_control_exposes_compilation_from_live_sources(project):
    original = (project / 'gateware/rtl/fixture.v').read_text()
    shell = project / 'gateware/build.sh'
    good = shell.read_text()
    broken = good.replace('source_here="$work/source/gateware"', 'source_here="$here"')
    assert broken != good
    shell.write_text(broken)
    assert build(project, 'transient_source').returncode == 0
    synth = project / 'gateware/build/demo.synth.json'
    assert json.loads(synth.read_text())['compiled_source'] != original
    # Start/end hashing alone misses the transient edit; the positive test's
    # independent compiled-content check would fail on this broken shell.
    assert verify(project).returncode == 0


@pytest.mark.parametrize('failure', ['synthesis', 'routing', 'error_exit_zero', 'timing', 'no_timing',
                                     'no_pnr_output', 'packing', 'empty_bitstream', 'no_packed_output', 'changed_source'])
def test_failed_build_cannot_leave_an_old_or_partial_flash_target(project, failure):
    r = build(project, failure)
    assert r.returncode != 0, (failure, r.stdout, r.stderr)
    out = project / 'gateware/build'
    assert not (out / 'demo.fs').exists(), 'a failed run left a flashable result'
    assert not (out / 'demo.build.json').exists()
    archived = list((out / 'previous').glob('demo.*/demo.fs'))
    assert len(archived) == 1 and archived[0].read_bytes() == b'old successful bitstream'
    assert list(out.glob('.demo.*/inputs.json')), 'failed-run evidence was lost'
    calls = (out / 'calls.log').read_text().splitlines()
    if failure in ('synthesis', 'routing', 'error_exit_zero', 'timing', 'no_timing'):
        assert 'gowin_pack' not in calls


@pytest.mark.parametrize('settings,suffix', [({'PULL': 'UP'}, '_pullup'),
                                           ({'PULL': 'DOWN', 'SDRAM_PHASE': '12'}, '_pulldown_phase12')])
def test_variant_outputs_and_manifests_do_not_replace_the_normal_build(project, settings, suffix):
    r = build(project, **settings)
    assert r.returncode == 0, r.stdout + r.stderr
    out = project / 'gateware/build'
    assert (out / 'demo.fs').read_bytes() == b'old successful bitstream'
    assert (out / f'demo{suffix}.fs').read_bytes() == b'new packed bitstream'
    record = json.loads((out / f'demo{suffix}.build.json').read_text())
    assert all(name.startswith(f'demo{suffix}.') for name in record['artifacts'])
    assert record['options']['pull'] == settings['PULL']
    assert record['options']['sdram_phase'] == settings.get('SDRAM_PHASE', '')


@pytest.mark.parametrize('top,settings', [('missing', {}), ('../demo', {}), ('demo', {'PULL': 'SIDEWAYS'}),
                                         ('demo', {'SDRAM_PHASE': '16'}), ('demo', {'SEED': 'two'}),
                                         ('demo', {'FREQ_MHZ': '0'}), ('demo', {'IOREG': '2'})])
def test_invalid_request_keeps_the_previous_result_and_does_not_start_tools(project, top, settings):
    r = build(project, top=top, **settings)
    assert r.returncode != 0
    out = project / 'gateware/build'
    assert (out / 'demo.fs').read_bytes() == b'old successful bitstream'
    assert not (out / 'calls.log').exists()


IOB_OPTS = '--vopt ireg_in_iob --vopt oreg_in_iob --vopt ioreg_in_iob '


@pytest.mark.parametrize('top,settings,suffix,iob', [
    ('m4_dual_mix', {}, '', True),                       # an SDRAM top: on by default
    ('demo', {}, '', False),                             # any other top: off by default
    ('m4_dual_mix', {'IOREG': '0'}, '_ioreg0', False),   # against the default: a variant beside the normal build
    ('demo', {'IOREG': '1'}, '_ioreg1', True),
    ('m4_dual_mix', {'IOREG': '1'}, '', True)])          # the default, asked for explicitly
def test_io_registers_in_the_io_cells_by_top_and_recorded(project, top, settings, suffix, iob):
    r = build(project, top=top, **settings)
    assert r.returncode == 0, r.stdout + r.stderr
    args = (project / 'gateware/build/nextpnr.args').read_text()
    assert (IOB_OPTS in args) == iob and args.count('_in_iob') == (3 if iob else 0), args
    out = project / 'gateware/build'
    record = json.loads((out / f'{top}{suffix}.build.json').read_text())
    assert record['options']['ioreg'] == ('1' if iob else '0')
    assert (out / f'{top}{suffix}.fs').read_bytes() == b'new packed bitstream'
    assert (out / 'demo.fs').read_bytes() == (b'new packed bitstream' if top == 'demo' and not suffix
                                              else b'old successful bitstream')
