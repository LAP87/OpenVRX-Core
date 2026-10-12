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
    before = files(out)
    (model / 'test_sample.py').write_text((model / 'test_sample.py').read_text() + '# changed source\n')
    assert cli(repo, out, '--resume').returncode == 2
    assert files(out) == before
