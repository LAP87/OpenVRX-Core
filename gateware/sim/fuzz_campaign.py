"""Fuzz campaign through the picture chain (test_fuzz_chain.py), outside pytest.

  fuzz_campaign.py run ROUND SEEDS [--classes a,b] [--force c] [--jobs 10] [--budget 540]
      Runs the seeds of SEEDS (e.g. 0-99) that build/fuzz/ROUND.jsonl does not have yet,
      JOBS at a time, and stops starting new ones when BUDGET seconds are nearly used up.
      Each result is appended as one JSON line, so the next call carries on.
  fuzz_campaign.py summary ROUND
      Counts per result and per group (first deviation: block/kind), failing seeds.
  fuzz_campaign.py narrow SEED [--jobs 10] [--budget 540] [--keep a,b]
      Turns the seed's classes off one at a time (all at once in parallel) and reports
      which ones the failure needs; state in build/fuzz/narrow-SEED.jsonl.
"""
import argparse
import concurrent.futures as cf
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_fuzz_chain as t  # noqa: E402

EST = 140.0                       # seconds one seed takes (about)
EST_FULL = 450.0                  # the same in the full geometry


def results(path):
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().split('\n') if ln.strip()]


def _one(args):
    seed, classes, work, force, geometry, density, fields = args
    try:
        return t.run_seed(seed, classes, work=Path(work), force=force, geometry=geometry, density=density,
                          n_fields=fields)
    except Exception as err:      # a crash in the checks is a result too
        return dict(seed=seed, result='crash', groups=['bench/crash'], first=dict(block='bench', kind='crash', t=0,
                    detail=repr(err)[:500]), classes=[], enabled=None if classes is None else sorted(classes))


def run_many(jobs_list, out_path, jobs, budget, tag, force=(), geometry='scaled', density=1.0, fields=None):
    """jobs_list: [(key, seed, classes)]; runs those whose key is not in out_path yet."""
    done = {r.get('key', r['seed']) for r in results(out_path)}
    todo = [j for j in jobs_list if j[0] not in done]
    t0 = time.time()
    n = 0
    with cf.ProcessPoolExecutor(max_workers=jobs) as ex:
        running = {}
        while todo or running:
            est = (EST if geometry == 'scaled' else EST_FULL) * (fields or 10) / 10
            while todo and len(running) < jobs and time.time() - t0 + est < budget:
                key, seed, classes = todo.pop(0)
                work = HERE / 'build' / 'fuzz' / tag / f'{key}'
                running[ex.submit(_one, (seed, classes, str(work), tuple(force), geometry, density, fields))] = key
            if not running:
                break
            fin, _ = cf.wait(list(running), return_when=cf.FIRST_COMPLETED)
            for f in fin:
                key = running.pop(f)
                res = f.result()
                res['key'] = key
                with open(out_path, 'a') as fh:
                    fh.write(json.dumps(res) + '\n')
                n += 1
                first = res.get('first') or {}
                print(f"{key}: {res['result']} {res.get('seconds', '')}s {first.get('block', '')}/{first.get('kind', '')} "
                      f"{','.join(res.get('classes', []))}", flush=True)
    left = len([j for j in jobs_list if j[0] not in {r.get('key', r['seed']) for r in results(out_path)}])
    print(f'ran {n} in {time.time() - t0:.0f} s, {left} left', flush=True)
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
    ap.add_argument('--jobs', type=int, default=10)
    ap.add_argument('--budget', type=float, default=540.0)
    ap.add_argument('--keep', default='')
    ap.add_argument('--force', default='')
    ap.add_argument('--geometry', default='scaled')
    ap.add_argument('--density', type=float, default=1.0)
    ap.add_argument('--fields', type=int)
    a = ap.parse_args()
    out = HERE / 'build' / 'fuzz'
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == 'run':
        classes = a.classes.split(',') if a.classes else None
        jl = [(s, s, classes) for s in t.parse_seeds(a.seeds)]
        force = [c for c in a.force.split(',') if c]
        run_many(jl, out / f'{a.what}.jsonl', a.jobs, a.budget, a.what, force, a.geometry, a.density, a.fields)
    elif a.cmd == 'summary':
        summary(out / f'{a.what}.jsonl')
    else:
        seed = int(a.what)
        path = out / f'narrow-{seed}.jsonl'
        base = t.fz.generate(seed)
        used = base.classes_used()
        keep = set(a.keep.split(',')) - {''}
        jl = [('all', seed, None)] + [(f'-{c}', seed, sorted(set(t.fz.CLASSES) - {c})) for c in used if c not in keep]
        run_many(jl, path, a.jobs, a.budget, f'narrow-{seed}')
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
    main()
