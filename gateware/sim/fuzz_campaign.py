"""Fuzz campaign through the picture chain (test_fuzz_chain.py), outside pytest.

  fuzz_campaign.py run ROUND SEEDS [--classes a,b] [--force c] [--jobs 1] [--budget 540]
      Runs the seeds of SEEDS (e.g. 0-99) that build/fuzz/ROUND.jsonl does not have yet,
      JOBS at a time, and stops starting new ones when BUDGET seconds are nearly used up.
      Each result is appended as one JSON line. Resume requires the same source
      hashes and settings in ROUND.contract.json; use a new name after a change.
      Legacy JSONL can be summarised, but cannot be resumed without provenance.
  fuzz_campaign.py summary ROUND
      Counts per result and per group (first deviation: block/kind), failing seeds.
  fuzz_campaign.py narrow SEED [--jobs 1] [--budget 540] [--keep a,b] [--round NAME]
      Turns the seed's classes off one at a time and reports which ones the failure
      needs; state in build/fuzz/narrow-SEED.jsonl, or NAME.jsonl with --round.
      Forced classes stay enabled. Geometry, density and fields also apply to narrow.

The round lock protects its evidence. Use the shared build.lock around this command
to exclude other heavy simulation or build jobs on this host.
"""
import argparse
import concurrent.futures as cf
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_fuzz_chain as t  # noqa: E402

EST = 140.0                       # seconds one seed takes (about)
EST_FULL = 450.0                  # the same in the full geometry


def source_snapshot():
    """Inputs used by the chain test, plus the simulator and Python identity."""
    paths = [t.GW / 'rtl' / name for name in t.RTL]
    paths += sorted((t.GW / 'rtl').glob('*.vh'))
    paths += sorted((t.GW / 'model').glob('*.py'))
    paths += [HERE / name for name in ('fuzz_campaign.py', 'test_fuzz_chain.py', 'tb_chain.v', 'margin_checks.vh', 'sdram_model.v')]
    files = {p.relative_to(t.PROJECT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=t.PROJECT,
                              capture_output=True, text=True, timeout=5)
    tools = {}
    for name in ('iverilog', 'vvp'):
        local = t.PROJECT / '.tools' / 'iverilog' / 'bin' / name
        found = local if local.is_file() else shutil.which(name)
        tools[name] = hashlib.sha256(Path(found).read_bytes()).hexdigest() if found else None
    return dict(revision=revision.stdout.strip() if revision.returncode == 0 else None,
                files=files, simulator=tools, python=sys.version)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def classes_value(classes):
    if classes is None:
        return None
    value = sorted(set(classes))
    unknown = set(value) - set(t.fz.CLASSES)
    if unknown:
        raise ValueError(f'unknown classes: {sorted(unknown)}')
    return value


def contract_for(jobs_list, force, geometry, density, fields, recovery_fields=0):
    if geometry not in ('scaled', 'full'):
        raise ValueError('geometry must be scaled or full')
    if not math.isfinite(density) or density < 0:
        raise ValueError('density must be finite and nonnegative')
    if fields is not None and (not isinstance(fields, int) or fields < 1):
        raise ValueError('fields must be a positive integer')
    if type(recovery_fields) is not int or recovery_fields < 0:
        raise ValueError('recovery_fields must be a nonnegative integer')
    class_sets = sorted({json.dumps(classes_value(c)) for _, _, c in jobs_list})
    return dict(schema=2, geometry=geometry, density=float(density),
                recovery_fields=recovery_fields, recovery_kind='synchronized-clean-fields' if recovery_fields else None,
                fields=fields if fields is not None else (t.fz.N_FIELDS if geometry == 'scaled' else t.fz.N_FIELDS_FULL),
                class_sets=[json.loads(c) for c in class_sets], force=classes_value(force),
                source=source_snapshot())


@contextmanager
def round_lock(path):
    """Do not let two coordinators append to the same round."""
    with path.with_suffix('.lock').open('a') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f'{path.name} is already running') from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def prepare_round(path, contract, jobs_list):
    """Validate all saved evidence before changing a manifest or starting a worker."""
    manifest = path.with_suffix('.contract.json')
    records = results(path)
    if records and not manifest.exists():
        raise ValueError(f'{path.name}: legacy results have no contract; use a new round name')
    wanted = dict(contract=contract, sha256=digest(contract))
    if manifest.exists() and json.loads(manifest.read_text()) != wanted:
        raise ValueError(f'{path.name}: sources or settings changed; use a new round name')
    expected = {str(k): (s, classes_value(c)) for k, s, c in jobs_list}
    done = set()
    for r in records:
        if not isinstance(r, dict) or ('key' not in r and 'seed' not in r):
            raise ValueError(f'{path.name}: result has no job key')
        k = str(r['key'] if 'key' in r else r['seed'])
        if r.get('contract_sha256') != wanted['sha256']:
            raise ValueError(f'{path.name}: result has missing or different provenance; use a new round name')
        if k in done:
            raise ValueError(f'{path.name}: duplicate result key {k!r}')
        if k in expected and r.get('job') != dict(seed=expected[k][0], classes=expected[k][1]):
            raise ValueError(f'{path.name}: key {k!r} has different inputs; use a new round name')
        done.add(k)
    if not manifest.exists():
        temp = manifest.with_suffix(f'.tmp-{os.getpid()}')
        try:
            temp.write_text(json.dumps(wanted, indent=2, sort_keys=True) + '\n')
            os.replace(temp, manifest)
        finally:
            temp.unlink(missing_ok=True)
    return done


def results(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().split('\n') if ln.strip()]


def _one(args):
    seed, classes, work, force, geometry, density, fields, recovery_fields = args
    try:
        return t.run_seed(seed, classes, work=Path(work), force=force, geometry=geometry, density=density,
                          n_fields=fields, recovery_fields=recovery_fields, keep=bool(recovery_fields))
    except Exception as err:      # a crash in the checks is a result too
        return dict(seed=seed, result='crash', groups=['bench/crash'], first=dict(block='bench', kind='crash', t=0,
                    detail=repr(err)[:500]), classes=[], enabled=None if classes is None else sorted(classes))


def run_many(jobs_list, out_path, jobs, budget, tag, force=(), geometry='scaled', density=1.0, fields=None,
             recovery_fields=0):
    """Resume only a round with identical settings, inputs and per-key seed definitions."""
    if jobs < 1 or not math.isfinite(budget) or budget < 0:
        raise ValueError('jobs must be positive and budget finite and nonnegative')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', tag):
        raise ValueError('round name must contain only letters, digits, underscores and hyphens')
    if len({str(k) for k, _, _ in jobs_list}) != len(jobs_list):
        raise ValueError('duplicate job keys')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', str(k)) for k, _, _ in jobs_list):
        raise ValueError('invalid job key')
    contract = contract_for(jobs_list, force, geometry, density, fields, recovery_fields)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with round_lock(out_path):
        done = prepare_round(out_path, contract, jobs_list)
        return _run_pending(jobs_list, out_path, done, jobs, budget, tag, contract)


def _run_pending(jobs_list, out_path, done, jobs, budget, tag, contract):
    todo = [j for j in jobs_list if str(j[0]) not in done]
    geometry, density, fields = (contract[k] for k in ('geometry', 'density', 'fields'))
    force = contract['force']
    default_fields = t.fz.N_FIELDS if geometry == 'scaled' else t.fz.N_FIELDS_FULL
    recovery_fields = contract['recovery_fields']
    est = (EST if geometry == 'scaled' else EST_FULL) * (fields + recovery_fields) / default_fields
    t0 = time.monotonic()
    n = 0
    with cf.ProcessPoolExecutor(max_workers=jobs) as ex:
        running = {}
        while todo or running:
            while todo and len(running) < jobs and time.monotonic() - t0 + est < budget:
                if source_snapshot() != contract['source']:
                    raise ValueError('sources changed during the round; use a new round name')
                key, seed, classes = todo.pop(0)
                work = HERE / 'build' / 'fuzz' / tag / f'{key}'
                running[ex.submit(_one, (seed, classes, str(work), tuple(force), geometry, density, fields, recovery_fields))] = (key, seed, classes)
            if not running:
                break
            fin, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
            for f in fin:
                key, seed, classes = running.pop(f)
                res = f.result()
                if source_snapshot() != contract['source']:
                    raise ValueError('sources changed while a worker ran; its result is not recorded')
                res['key'] = key
                res['contract_sha256'] = digest(contract)
                res['job'] = dict(seed=seed, classes=classes_value(classes))
                res.update(geometry=geometry, density=density, n_fields=fields, force=force,
                           recovery_fields=recovery_fields)
                with open(out_path, 'a') as fh:
                    fh.write(json.dumps(res) + '\n')
                n += 1
                first = res.get('first') or {}
                print(f"{key}: {res['result']} {res.get('seconds', '')}s {first.get('block', '')}/{first.get('kind', '')} "
                      f"{','.join(res.get('classes', []))}", flush=True)
                done.add(str(key))
    left = sum(str(j[0]) not in done for j in jobs_list)
    print(f'ran {n} in {time.monotonic() - t0:.0f} s, {left} left', flush=True)
    return left


def summary(path):
    rs = results(path)
    print(f'{path.name}: {len(rs)} seeds', Counter(r['result'] for r in rs))
    groups = defaultdict(list)
    for r in rs:
        if r['result'] in ('fail', 'crash'):
            f = r['first']
            groups[f"{f['block']}/{f['kind']}"].append(r['seed'])
    for g, seeds in sorted(groups.items(), key=lambda x: -len(x[1])):
        print(f'  {g}: {len(seeds)}  {seeds[:30]}')
    known = defaultdict(list)
    for r in rs:
        for k in r.get('known', []):
            known[k['issue']].append(r['seed'])
    for issue, seeds in known.items():
        print(f'  known, {issue}: {len(set(seeds))}  {sorted(set(seeds))[:30]}')
    edges = [r['seed'] for r in rs if r['result'] == 'edge' or (r.get('edges') and r['result'] == 'fail')]
    print(f'  mixer edge cases: {len(edges)}  {edges[:30]}')
    cls = Counter(c for r in rs for c in r.get('classes', []))
    bad = Counter(c for r in rs if r['result'] == 'fail' for c in r.get('classes', []))
    print('  classes (seeds using it, of them failing):',
          ', '.join(f'{c} {cls[c]}/{bad[c]}' for c in sorted(cls)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('run', 'summary', 'narrow'))
    ap.add_argument('what')
    ap.add_argument('seeds', nargs='?')
    ap.add_argument('--classes')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--budget', type=float, default=540.0)
    ap.add_argument('--keep', default='')
    ap.add_argument('--force', default='')
    ap.add_argument('--geometry', choices=('scaled', 'full'), default='scaled')
    ap.add_argument('--density', type=float, default=1.0)
    ap.add_argument('--fields', type=int)
    ap.add_argument('--recovery-fields', type=int, default=0,
                    help='append clean synchronized fields while preserving the generated prefix')
    ap.add_argument('--round', dest='round_name', help='a new evidence name for narrow after changing inputs')
    a = ap.parse_args()
    out = HERE / 'build' / 'fuzz'
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == 'run':
        classes = a.classes.split(',') if a.classes else None
        jl = [(s, s, classes) for s in t.parse_seeds(a.seeds)]
        force = [c for c in a.force.split(',') if c]
        run_many(jl, out / f'{a.what}.jsonl', a.jobs, a.budget, a.what, force, a.geometry, a.density, a.fields, a.recovery_fields)
    elif a.cmd == 'summary':
        summary(out / f'{a.what}.jsonl')
    else:
        seed = int(a.what)
        tag = a.round_name or f'narrow-{seed}'
        path = out / f'{tag}.jsonl'
        contract_for([(seed, seed, None)], a.force.split(',') if a.force else (), a.geometry, a.density, a.fields, a.recovery_fields)
        classes = a.classes.split(',') if a.classes else None
        force = a.force.split(',') if a.force else ()
        base = t.fz.generate(seed, classes, force=force, geometry=a.geometry, density=a.density, n_fields=a.fields)
        used = base.classes_used()
        keep = (set(a.keep.split(',')) - {''}) | set(force)
        allowed = set(t.fz.CLASSES if classes is None else classes)
        jl = [('all', seed, classes)] + [(f'-{c}', seed, sorted(allowed - {c})) for c in used if c not in keep]
        run_many(jl, path, a.jobs, a.budget, tag, force, a.geometry, a.density, a.fields, a.recovery_fields)
        rs = {r['key']: r for r in results(path)}
        ref = rs.get('all')
        if ref:
            g0 = ref['first'] and f"{ref['first']['block']}/{ref['first']['kind']}"
            print(f'seed {seed}: {ref["result"]} {g0}, classes {used}')
            for c in used:
                r = rs.get(f'-{c}')
                if r:
                    g = r['first'] and f"{r['first']['block']}/{r['first']['kind']}"
                    still = g0 in r.get('groups', [])
                    print(f'  without {c}: {r["result"]} {g} {r.get("groups")}  -> {"not needed" if still else "NEEDED"}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as err:
        sys.exit(str(err))
