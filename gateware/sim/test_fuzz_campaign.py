"""Campaign resume gates with worker doubles; these tests do not simulate RTL."""
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fuzz_campaign_under_test', HERE / 'fuzz_campaign.py')
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    calls = []
    source = dict(revision='fixture', files={'rtl/block.v': 'original'}, simulator={}, python='fixture')
    monkeypatch.setattr(fc, 'HERE', tmp_path)
    monkeypatch.setattr(fc, 'source_snapshot', lambda: copy.deepcopy(source))
    monkeypatch.setattr(fc.cf, 'ProcessPoolExecutor', concurrent.futures.ThreadPoolExecutor)

    def worker(args):
        calls.append(args)
        return dict(seed=args[0], result='pass', first=None, classes=[], seconds=0)

    monkeypatch.setattr(fc, '_one', worker)
    return tmp_path / 'round.jsonl', calls, source


def run(path, seeds=(1,), **opts):
    classes = opts.pop('classes', None)
    return fc.run_many([(s, s, classes) for s in seeds], path, 1, 1000, 'round', **opts)


def saved(path):
    return path.read_bytes(), path.with_suffix('.contract.json').read_bytes()


def test_resume_runs_only_missing_seeds(campaign):
    path, calls, _ = campaign
    assert run(path) == 0
    first = path.read_bytes()
    assert run(path, seeds=(1, 2)) == 0
    assert [a[0] for a in calls] == [1, 2]
    assert path.read_bytes().startswith(first)
    records = fc.results(path)
    assert len({r['contract_sha256'] for r in records}) == 1
    assert records[1]['job'] == dict(seed=2, classes=None)


def test_explicit_default_field_count_is_same_contract(campaign):
    path, calls, _ = campaign
    run(path)
    assert run(path, fields=fc.t.fz.N_FIELDS) == 0
    assert len(calls) == 1


@pytest.mark.parametrize('change', [dict(geometry='full'), dict(density=2.5), dict(fields=12),
                                   dict(classes=['pal']), dict(force=['pal'])])
def test_changed_settings_refuse_resume_without_touching_evidence(campaign, change):
    path, calls, _ = campaign
    run(path)
    before = saved(path)
    with pytest.raises(ValueError, match='new round name'):
        run(path, **change)
    assert saved(path) == before
    assert len(calls) == 1


@pytest.mark.parametrize('field', ['revision', 'files', 'simulator', 'python'])
def test_changed_sources_or_runtime_refuse_resume(campaign, field):
    path, calls, source = campaign
    run(path)
    before = saved(path)
    source[field] = {'changed': 'value'} if isinstance(source[field], dict) else 'changed'
    with pytest.raises(ValueError, match='new round name'):
        run(path)
    assert saved(path) == before
    assert len(calls) == 1


def test_legacy_can_be_summarised_but_not_resumed(campaign, capsys):
    path, calls, _ = campaign
    path.write_text(json.dumps(dict(seed=1, result='pass', classes=[], first=None)) + '\n')
    fc.summary(path)
    assert '1 seeds' in capsys.readouterr().out
    before = path.read_bytes()
    with pytest.raises(ValueError, match='legacy results have no contract'):
        run(path)
    assert path.read_bytes() == before
    assert not path.with_suffix('.contract.json').exists()
    assert not calls


def test_same_key_with_different_seed_refuses_resume(campaign):
    path, calls, _ = campaign
    run(path)
    before = saved(path)
    with pytest.raises(ValueError, match='different inputs'):
        fc.run_many([(1, 2, None)], path, 1, 1000, 'round')
    assert saved(path) == before
    assert len(calls) == 1


def test_numeric_and_text_keys_refer_to_the_same_work_path(campaign):
    path, calls, _ = campaign
    run(path)
    assert fc.run_many([('1', 1, None)], path, 1, 1000, 'round') == 0
    assert len(calls) == 1


def test_keys_with_the_same_work_path_cannot_run_together(campaign):
    path, calls, _ = campaign
    with pytest.raises(ValueError, match='duplicate job keys'):
        fc.run_many([(1, 1, None), ('1', 2, None)], path, 2, 1000, 'round')
    assert not calls
    assert not path.exists()


def test_foreign_result_is_not_counted_as_completed(campaign):
    path, calls, _ = campaign
    run(path)
    result = fc.results(path)[0]
    result['contract_sha256'] = 'foreign'
    path.write_text(json.dumps(result) + '\n')
    before = saved(path)
    with pytest.raises(ValueError, match='provenance'):
        run(path)
    assert saved(path) == before
    assert len(calls) == 1


def test_duplicate_saved_key_refuses_resume(campaign):
    path, calls, _ = campaign
    run(path)
    path.write_bytes(path.read_bytes() * 2)
    before = saved(path)
    with pytest.raises(ValueError, match='duplicate result key'):
        run(path)
    assert saved(path) == before
    assert len(calls) == 1


def test_round_lock_prevents_two_coordinators(campaign):
    path, calls, _ = campaign
    with fc.round_lock(path):
        with pytest.raises(ValueError, match='already running'):
            run(path)
    assert not calls
    assert not path.with_suffix('.contract.json').exists()


def test_source_change_while_worker_runs_is_not_recorded(campaign, monkeypatch):
    path, _, source = campaign

    def worker(args):
        source['files']['rtl/block.v'] = 'changed during worker'
        return dict(seed=args[0], result='pass', classes=[], first=None)

    monkeypatch.setattr(fc, '_one', worker)
    with pytest.raises(ValueError, match='not recorded'):
        run(path)
    assert not path.exists()


def test_full_geometry_budget_uses_its_own_default_fields(campaign):
    path, calls, _ = campaign
    assert fc.run_many([(1, 1, None)], path, 1, fc.EST_FULL - 1, 'round', geometry='full', fields=4) == 1
    assert not calls
    assert fc.run_many([(1, 1, None)], path, 1, fc.EST_FULL + 1, 'round', geometry='full', fields=4) == 0
    assert calls[0][-1] == 4


@pytest.mark.parametrize('opts', [dict(density=float('nan')), dict(density=float('inf')),
                                dict(density=-1), dict(fields=0), dict(fields=-1),
                                dict(geometry='unknown'), dict(force=['unknown'])])
def test_invalid_contract_starts_no_worker(campaign, opts):
    path, calls, _ = campaign
    with pytest.raises(ValueError):
        run(path, **opts)
    assert not path.exists()
    assert not path.with_suffix('.contract.json').exists()
    assert not calls


def test_narrow_propagates_nondefault_settings(campaign, monkeypatch):
    _, _, _ = campaign
    seen = {}

    def generate(seed, classes, **options):
        seen['scenario'] = (seed, classes, options)
        return type('Scenario', (), {'classes_used': lambda self: ['pal', 'mode_switch']})()

    def run_many(*args):
        seen['run'] = args

    monkeypatch.setattr(fc.t.fz, 'generate', generate)
    monkeypatch.setattr(fc, 'run_many', run_many)
    monkeypatch.setattr(sys, 'argv', ['fuzz_campaign.py', 'narrow', '17', '--classes', 'pal,mode_switch',
                                    '--force', 'pal', '--geometry', 'full', '--fields', '8', '--density', '2.5',
                                    '--round', 'full-pal-17-v2'])
    fc.main()
    assert seen['scenario'] == (17, ['pal', 'mode_switch'],
                               dict(force=['pal'], geometry='full', density=2.5, n_fields=8))
    assert seen['run'][0] == [('all', 17, ['pal', 'mode_switch']), ('-mode_switch', 17, ['pal'])]
    assert seen['run'][1].name == 'full-pal-17-v2.jsonl'
    assert seen['run'][4] == 'full-pal-17-v2'
    assert seen['run'][5:] == (['pal'], 'full', 2.5, 8)
