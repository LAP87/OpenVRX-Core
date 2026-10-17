"""Resume evidence and final completeness regressions; no HDL subprocesses."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import run_suite


def record(nodes, outcomes=None, rc=0):
    return {'unit': run_suite.units_of(nodes)[0][0], 'nodes': nodes, 'rc': rc,
            'wall': 1, 'log': '0001.log', 'claims': {},
            'tests': {n: {'outcome': o, 'duration': 1}
                      for n, o in zip(nodes, outcomes or ['passed'] * len(nodes))}}


NODES = ['gateware/model/test_a.py::test_a', 'gateware/model/test_a.py::test_b']


@pytest.mark.parametrize('mutation', ['empty', 'partial', 'foreign', 'metadata'])
def test_incomplete_resume_refused_before_worker_and_writes(tmp_path, monkeypatch, capsys, mutation):
    rec = record(NODES)
    if mutation == 'empty':
        rec['tests'] = {}
    elif mutation == 'partial':
        rec['tests'].pop(NODES[1])
    elif mutation == 'foreign':
        rec['tests']['gateware/model/test_a.py::test_foreign'] = rec['tests'].pop(NODES[1])
    else:
        rec['nodes'] = [NODES[0]]
    (tmp_path / 'run.json').write_text(json.dumps({'fingerprint': 'source', 'nodes': NODES}))
    (tmp_path / 'results.jsonl').write_text(json.dumps(rec) + '\n')
    (tmp_path / 'durations.json').write_text('{}')
    (tmp_path / 'report.txt').write_text('preserve rejected evidence')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(run_suite, 'collect', lambda *a: NODES)
    monkeypatch.setattr(run_suite, 'fingerprint', lambda: 'source')
    def forbidden(*a):
        pytest.fail('worker started on invalid evidence')
    monkeypatch.setattr(run_suite, 'Job', forbidden)
    assert run_suite.main(['--resume', '--out', str(tmp_path), '--jobs', '1']) == 2
    assert '--resume refused' in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize('outcome', ['passed', 'skipped', 'xfailed', 'failed', 'error', 'missing',
                                      'timeout', 'xpassed'])
def test_cached_outcome_policy(outcome):
    rec = record(NODES, [outcome, outcome])
    assert run_suite.unit_ok(rec) == (outcome in run_suite.ACCEPTED)
    done = run_suite.resume_done([rec], run_suite.units_of(NODES))
    assert bool(done) == (outcome in run_suite.ACCEPTED)
    rec['rc'] = 1
    assert not run_suite.unit_ok(rec)


def test_latest_failed_record_cannot_reuse_older_pass():
    good = record(NODES)
    failed = record(NODES, ['failed', 'passed'], 1)
    assert run_suite.resume_done([good, failed], run_suite.units_of(NODES)) == {}


def test_grouped_subset_and_unrequested_cache_do_not_satisfy_current_request():
    with pytest.raises(ValueError, match='nodes differ'):
        run_suite.resume_done([record(NODES[:1])], run_suite.units_of(NODES))
    with pytest.raises(ValueError, match='unrequested cached unit'):
        run_suite.resume_done([record(['mixer/test_other.py::test_x'])], run_suite.units_of(NODES))


@pytest.mark.parametrize('case,expected_rc', [('complete', 0), ('absent', 1), ('foreign', 1),
                                            ('pending', 3), ('nonzero_skip', 1),
                                            ('nonzero_xfail', 1), ('bad_pending', 1),
                                            ('duplicate_pending', 1), ('overlap', 1), ('extra', 1)])
def test_finish_reconciles_identities_and_pending(tmp_path, case, expected_rc):
    rec = record(NODES)
    finished, pending = {rec['unit']: rec}, []
    if case == 'absent':
        finished = {}
    elif case == 'foreign':
        rec['tests']['foreign'] = rec['tests'].pop(NODES[1])
    elif case == 'pending':
        finished, pending = {}, run_suite.units_of(NODES)
    elif case == 'bad_pending':
        finished, pending = {}, [(rec['unit'], NODES[:1])]
    elif case == 'duplicate_pending':
        finished, pending = {}, run_suite.units_of(NODES) * 2
    elif case == 'overlap':
        pending = run_suite.units_of(NODES)
    elif case == 'extra':
        extra = record(['mixer/test_other.py::test_x'])
        finished[extra['unit']] = extra
    elif case.startswith('nonzero'):
        rec = record(NODES, ['skipped' if case.endswith('skip') else 'xfailed'] * 2, 1)
        finished = {rec['unit']: rec}
    assert run_suite.finish(tmp_path, finished, pending, NODES, time.monotonic()) == expected_rc


def test_pick_quick_takes_every_file_first_and_keeps_the_limit():
    """Two workers, 60 s: the fastest test of each file first (y1 alone is longer than the limit),
    then the rest while the expected wall time (start-up included) stays within 60 s; the list
    comes back longest first, collection order on a tie."""
    nodes = ['gateware/sim/test_x.py::x1', 'gateware/sim/test_x.py::x2', 'gateware/sim/test_y.py::y1',
             'gateware/model/test_m.py::m1', 'gateware/model/test_m.py::m2', 'gateware/sim/test_z.py::z1']
    durations = {'gateware/sim/test_x.py::x1': 10, 'gateware/sim/test_x.py::x2': 50,
                 'gateware/sim/test_y.py::y1': 200, 'gateware/model/test_m.py::m1': 1,
                 'gateware/model/test_m.py::m2': 1}               # z1 never timed: left out
    chosen = run_suite.pick_quick(nodes, durations, 60, 2)
    assert chosen == ['gateware/sim/test_x.py::x2', 'gateware/sim/test_x.py::x1',
                      'gateware/model/test_m.py::m1', 'gateware/model/test_m.py::m2']
    units = [run_suite.unit_time(ns, durations) for _, ns in run_suite.units_of(chosen)]
    assert run_suite.makespan(units, 2) <= 60
    # with one worker the 50 s test no longer fits beside the others
    assert 'gateware/sim/test_x.py::x2' not in run_suite.pick_quick(nodes, durations, 60, 1)


def cli(repo, out, *args):
    return subprocess.run([sys.executable, str(repo / 'gateware/tools/run_suite.py'), '--jobs', '1',
                           '--timeout', '60', '--out', str(out), 'gateware/model/test_sample.py',
                           *args], cwd=repo, capture_output=True, text=True, timeout=60)


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_real_cli_selection_resume_budget_and_source_guard(tmp_path):
    repo = tmp_path / 'repo'
    tools = repo / 'gateware/tools'
    tools.mkdir(parents=True)
    for name in ('run_suite.py', 'build_dirs.py', 'suite_trace.py'):
        shutil.copyfile(Path(run_suite.__file__).with_name(name), tools / name)
    model = repo / 'gateware/model'
    model.mkdir()
    (model / 'test_sample.py').write_text('import pytest\n'
                                        'def test_a(): pass\n'
                                        'def test_b(): pass\n'
                                        'def test_skip(): pytest.skip("fixture")\n'
                                        '@pytest.mark.xfail(strict=True)\n'
                                        'def test_xfail(): assert False\n')
    out = tmp_path / 'baseline'
    baseline = cli(repo, out)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr
    raw = {k: v for k, v in files(out).items() if k.startswith(('logs/', 'trace/')) or k == 'results.jsonl'}
    resumed = cli(repo, out, '--resume')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert '1 already passed, 0 to run' in resumed.stdout
    assert all(files(out)[k] == v for k, v in raw.items())
    subset = tmp_path / 'subset'
    assert cli(repo, subset, '-k', 'test_a').returncode == 0
    before = files(subset)
    expanded = cli(repo, subset, '--resume')
    assert expanded.returncode == 2 and 'selection changed' in expanded.stdout
    assert files(subset) == before
    # Different text selecting the exact same collected nodes remains compatible.
    assert cli(repo, subset, '--resume', '-k', 'test_a or nonexistent').returncode == 0
    # Legacy manifests remain resumable only for the same request text.
    legacy = tmp_path / 'legacy'
    shutil.copytree(out, legacy)
    manifest = legacy / 'run.json'
    value = json.loads(manifest.read_text())
    value.pop('nodes')
    manifest.write_text(json.dumps(value))
    assert cli(repo, legacy, '--resume').returncode == 0
    # Structurally incomplete cache must preserve all logs/trace/report bytes.
    corrupt = tmp_path / 'corrupt'
    shutil.copytree(out, corrupt)
    p = corrupt / 'results.jsonl'
    rec = json.loads(p.read_text())
    rec['tests'].pop(rec['nodes'][0])
    p.write_text(json.dumps(rec) + '\n')
    before = files(corrupt)
    rejected = cli(repo, corrupt, '--resume')
    assert rejected.returncode == 2 and 'missing outcome' in rejected.stdout
    assert files(corrupt) == before
    budget = tmp_path / 'budget'
    limited = cli(repo, budget, '--budget', '0.01', '--guess', '10')
    assert limited.returncode == 3, limited.stdout + limited.stderr
    assert cli(repo, budget, '--resume').returncode == 0
    # cocotb's per-test xUnit output (git-ignored, regenerated every run) must not change
    # the fingerprint: a resume after a cocotb round still reuses the passed tests
    sim = repo / 'gateware/sim'
    sim.mkdir()
    (sim / 'test_x_result.result.xml').write_text('<results/>\n')
    assert cli(repo, out, '--resume').returncode == 0
    # quick (after the resume above: writing the list changes the sources): a list written from
    # the baseline's durations, then a run of only what it names
    quick_list = tools / 'quick_tests.txt'
    picked = cli(repo, out, '--pick-quick', '300')
    assert picked.returncode == 0 and quick_list.exists(), picked.stdout + picked.stderr
    # every timed test fits, longest first; the skipped one has no measured duration and stays out
    listed = run_suite.read_quick(quick_list)
    assert sorted(listed) == sorted(n for n in json.loads((out / 'run.json').read_text())['nodes']
                                    if not n.endswith('::test_skip'))
    measured = json.loads((out / 'durations.json').read_text())
    assert [measured[n] for n in listed] == sorted((measured[n] for n in listed), reverse=True)
    quick_list.write_text('# one test\ngateware/model/test_sample.py::test_a\n')
    quick = tmp_path / 'quick'
    ran = cli(repo, quick, '--quick')
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert json.loads((quick / 'run.json').read_text())['nodes'] == ['gateware/model/test_sample.py::test_a']
    # without --out a quick run writes to its own directory and leaves the full run's alone
    own = subprocess.run([sys.executable, str(tools / 'run_suite.py'), '--jobs', '1', '--timeout', '60',
                          '--quick', 'gateware/model/test_sample.py'],
                         cwd=repo, capture_output=True, text=True, timeout=60)
    assert own.returncode == 0, own.stdout + own.stderr
    assert json.loads((repo / 'gateware/sim/build/quick/run.json').read_text())['nodes'] == \
        ['gateware/model/test_sample.py::test_a']
    assert not (repo / 'gateware/sim/build/suite').exists()
    quick_list.write_text('gateware/model/test_sample.py::test_gone\n')
    stale = cli(repo, tmp_path / 'stale', '--quick')
    assert stale.returncode == 2 and 'not collected' in stale.stdout
    assert cli(repo, tmp_path / 'both', '--quick', '--full').returncode == 2      # one or the other
    before = files(out)
    (model / 'test_sample.py').write_text((model / 'test_sample.py').read_text() + '# changed source\n')
    assert cli(repo, out, '--resume').returncode == 2
    assert files(out) == before


def test_quick_without_durations_starts_in_list_order(tmp_path):
    """The stored list is longest first. A quick run whose output directory has no durations yet
    (a fresh checkout) starts the tests in the list's order, not in collection order, so the
    longest test does not start last."""
    repo = tmp_path / 'repo'
    tools = repo / 'gateware/tools'
    tools.mkdir(parents=True)
    for name in ('run_suite.py', 'build_dirs.py', 'suite_trace.py'):
        shutil.copyfile(Path(run_suite.__file__).with_name(name), tools / name)
    sim = repo / 'gateware/sim'
    sim.mkdir()
    (sim / 'test_order.py').write_text(''.join(f'def test_{i}(): pass\n' for i in (1, 2, 3)))
    order = ['gateware/sim/test_order.py::test_3', 'gateware/sim/test_order.py::test_1',
             'gateware/sim/test_order.py::test_2']
    (tools / 'quick_tests.txt').write_text('# longest first\n' + '\n'.join(order + order[:1]) + '\n')
    out = tmp_path / 'quick'
    r = subprocess.run([sys.executable, str(tools / 'run_suite.py'), '--jobs', '1', '--timeout', '60',
                        '--out', str(out), '--quick', 'gateware/sim/test_order.py'],
                       cwd=repo, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '3 tests in 3 processes' in r.stdout          # the repeated name runs once
    started = [json.loads(l)['unit'] for l in (out / 'results.jsonl').read_text().splitlines()]
    assert started == order
