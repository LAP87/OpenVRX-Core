"""Run the Core test suite in parallel: one pytest process per simulation test.

    .venv/bin/python gateware/tools/run_suite.py [-j 10] [--quick | --full] [--resume] [--budget S] [paths ...]

--full (the default) runs everything collected. --quick runs only the tests named in
gateware/tools/quick_tests.txt: a list chosen by measured time to finish within about five
minutes with ten processes (before every commit; the full suite before every merge). A name in
the list that is no longer collected stops the run (exit 2). --pick-quick S writes a new list
from durations.json in OUT: the fastest test of every file first, then the fastest of the rest,
as long as the expected wall time with -j processes stays within S seconds.

Tests under gateware/sim and gateware/tools get a process each; the pure Python
tests (gateware/model, mixer, tests/latency) get one process per file. Every
process has its own --basetemp, and suite_trace.py records which build
directories and cocotb results files each test used; at the end build_dirs.py
fails the run when two tests used the same one.

Output in OUT (default gateware/sim/build/suite; gateware/sim/build/quick with --quick, so that
a quick run leaves the last full run's results and durations alone): logs/ (one log per process),
results.jsonl (one record per finished process), status.json (progress),
report.txt, durations.json (used to start the longest tests first next time).

--resume keeps the processes that passed in OUT and runs the rest; it refuses
when sources or the collected test selection changed, or cached completed
records lack their requested outcomes. Refused resumes leave OUT unchanged.
--budget S starts no process
that is not expected to finish within S seconds of the start (expected: its
duration in durations.json, else --guess); what is left is reported and a later
--resume runs it.

Exit status: 0 all passed and no shared build directory, 1 a test did not pass
or a directory is shared, 2 collection failed, 3 tests left (budget).
"""
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dirs  # noqa: E402

TOOLS = Path(__file__).resolve().parent
GW = TOOLS.parent
REPO = GW.parent
PATHS = ['tests/latency', 'mixer', 'gateware/model', 'gateware/sim', 'gateware/tools']
PER_TEST = ('gateware/sim/', 'gateware/tools/')
SOURCES = ['gateware/rtl', 'gateware/sim', 'gateware/model', 'gateware/tools', 'gateware/top',
           'gateware/boards', 'gateware/formal', 'gateware/vectors', 'gateware/build.sh',
           'gateware/BRINGUP.md', 'mixer', 'tests']   # BRINGUP.md: sim/test_probe.py reads its example
SKIP_DIRS = {'build', '__pycache__', '.pytest_cache'}
SKIP_FILES = {'*.result.xml'}            # cocotb's per-test xUnit output, written into gateware/sim
                                         # (git-ignored); the tests regenerate it every run
QUICK_LIST = TOOLS / 'quick_tests.txt'
STARTUP = 2.0          # seconds of pytest start-up per process, on top of the tests' own durations


def read_quick(path=QUICK_LIST):
    """Test names of the quick list (lines that are not empty and not # comments)."""
    return [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]


def makespan(unit_times, jobs):
    """Wall time of the units on `jobs` workers, longest first (as main() schedules them)."""
    workers = [0.0] * max(1, jobs)
    for t in sorted(unit_times, reverse=True):
        workers[workers.index(min(workers))] += t
    return max(workers)


def unit_time(nodes, durations):
    return sum(durations[n] for n in nodes) + STARTUP


def pick_quick(nodes, durations, seconds, jobs):
    """Tests for the quick list: of the collected `nodes` with a measured duration, the fastest of
    every file first, then the rest by duration, each kept only while the expected wall time of
    the whole selection stays within `seconds`."""
    timed = sorted((n for n in nodes if n in durations), key=lambda n: (durations[n], n))
    first, seen = [], set()
    for n in timed:
        f = n.split('::', 1)[0]
        if f not in seen:
            seen.add(f)
            first.append(n)
    chosen = []
    for n in first + [n for n in timed if n not in set(first)]:
        trial = chosen + [n]
        if makespan([unit_time(ns, durations) for _, ns in units_of(trial)], jobs) <= seconds:
            chosen = trial
    order = {n: i for i, n in enumerate(nodes)}
    return sorted(chosen, key=lambda n: order[n])


def fingerprint():
    """SHA-256 over the files the suite reads (build output excluded)."""
    h = hashlib.sha256()
    files = []
    for s in SOURCES:
        p = REPO / s
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            for f in p.rglob('*'):
                if f.is_file() and not SKIP_DIRS & set(f.relative_to(REPO).parts):
                    if not any(fnmatch.fnmatch(f.name, pat) for pat in SKIP_FILES):
                        files.append(f)
    for f in sorted(files):
        h.update(f.relative_to(REPO).as_posix().encode() + b'\0' + f.read_bytes() + b'\0')
    return h.hexdigest()


def collect(paths, keyword=None):
    cmd = [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider', *paths]
    if keyword:
        cmd += ['-k', keyword]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    nodes = [l.strip() for l in r.stdout.splitlines() if '::' in l and not l.startswith(' ')]
    if r.returncode not in (0, 5):
        sys.stdout.write(r.stdout[-4000:] + r.stderr[-4000:])
        return None
    return nodes


def units_of(nodes):
    """[(unit id, [nodes])]: a node of its own under PER_TEST, else one unit per file."""
    units, files = [], {}
    for n in nodes:
        f = n.split('::', 1)[0]
        if f.startswith(PER_TEST):
            units.append((n, [n]))
        else:
            if f not in files:
                files[f] = []
                units.append((f, files[f]))
            files[f].append(n)
    return units


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


class Job:
    def __init__(self, index, unit, nodes, out, timeout):
        self.index, self.unit, self.nodes = index, unit, nodes
        self.log = out / 'logs' / f'{index:04d}.log'
        self.trace = out / 'trace' / f'{index:04d}.json'
        self.tmp = Path(tempfile.mkdtemp(prefix=f'openvrx-suite-{index:04d}-'))
        self.timeout = timeout
        env = dict(os.environ)
        env['PYTHONPATH'] = str(TOOLS) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        env['OPENVRX_SUITE_TRACE'] = str(self.trace)
        cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'suite_trace',
               f'--basetemp={self.tmp / "t"}', *nodes]
        self.fh = open(self.log, 'w')
        self.fh.write(' '.join(cmd) + '\n\n')
        self.fh.flush()
        self.start = time.monotonic()
        self.proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=self.fh, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        self.timed_out = False

    def poll(self):
        if self.proc.poll() is None and self.timeout and time.monotonic() - self.start > self.timeout:
            self.timed_out = True
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        return self.proc.poll()

    def kill(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()

    def record(self):
        self.fh.close()
        wall = round(time.monotonic() - self.start, 2)
        trace = json.loads(self.trace.read_text()) if self.trace.exists() else {}
        tests = trace.get('tests', {})
        for n in self.nodes:
            if n not in tests:
                tests[n] = {'outcome': 'timeout' if self.timed_out else 'missing', 'duration': wall}
        ok = all(tests[n]['outcome'] in ('passed', 'skipped', 'xfailed') for n in self.nodes)
        if ok and self.proc.returncode == 0:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return {'unit': self.unit, 'nodes': self.nodes, 'rc': self.proc.returncode, 'wall': wall,
                'log': str(self.log.relative_to(REPO)) if self.log.is_relative_to(REPO) else str(self.log),
                'tests': {n: tests[n] for n in self.nodes}, 'claims': trace.get('claims', {})}


ACCEPTED = ('passed', 'skipped', 'xfailed')


def coverage_errors(rec, expected):
    """Check identities independently of whether the recorded tests passed."""
    errors = []
    expected = set(expected)
    recorded = rec.get('nodes')
    tests = rec.get('tests')
    if not isinstance(recorded, list) or not all(isinstance(n, str) for n in recorded):
        errors.append('invalid cached nodes')
    elif len(recorded) != len(set(recorded)) or set(recorded) != expected:
        errors.append('cached nodes differ from requested nodes')
    if not isinstance(tests, dict):
        return errors + ['invalid cached tests']
    for n in sorted(expected - tests.keys()):
        errors.append(f'missing outcome: {n}')
    for n in sorted(tests.keys() - expected):
        errors.append(f'unrequested outcome: {n}')
    for n, t in tests.items():
        if not isinstance(t, dict) or not isinstance(t.get('outcome'), str):
            errors.append(f'invalid outcome: {n}')
    return errors


def unit_ok(rec):
    nodes = rec.get('nodes', [])
    return (bool(nodes) and not coverage_errors(rec, nodes) and rec['rc'] == 0
            and all(t['outcome'] in ACCEPTED for t in rec['tests'].values()))


def resume_done(records, units):
    """Refuse inconsistent evidence before scheduling or rewriting output."""
    expected = dict(units)
    newest = {r['unit']: r for r in records}
    done = {}
    for u, r in newest.items():
        if u not in expected:
            raise ValueError(f'unrequested cached unit: {u}')
        errors = coverage_errors(r, expected[u])
        if errors:
            raise ValueError(f'{u}: ' + '; '.join(errors))
        if unit_ok(r):
            done[u] = r
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('paths', nargs='*', default=PATHS)
    ap.add_argument('-j', '--jobs', type=int, default=10)
    ap.add_argument('-k', dest='keyword')
    ap.add_argument('--out', type=Path,
                    help='default gateware/sim/build/suite, with --quick gateware/sim/build/quick')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--budget', type=float, default=0, help='seconds; 0: no limit')
    ap.add_argument('--guess', type=float, default=120, help='expected seconds for a unit never timed')
    ap.add_argument('--timeout', type=float, default=3600, help='seconds per process; 0: none')
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument('--quick', action='store_true', help='only the tests in quick_tests.txt')
    sel.add_argument('--full', action='store_true', help='every collected test (the default)')
    sel.add_argument('--pick-quick', type=float, metavar='S',
                     help='write quick_tests.txt from OUT/durations.json for a wall time of S seconds, run nothing')
    ap.add_argument('--quick-list', type=Path, default=QUICK_LIST, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    out = (a.out or GW / 'sim' / 'build' / ('quick' if a.quick else 'suite')).resolve()
    t0 = time.monotonic()

    nodes = collect(a.paths, a.keyword)
    if nodes is None:
        print('collection failed')
        return 2
    if a.pick_quick:
        dfile = out / 'durations.json'
        if not dfile.exists():
            print(f'--pick-quick needs {dfile} from a full run')
            return 2
        durations = json.loads(dfile.read_text())
        chosen = pick_quick(nodes, durations, a.pick_quick, a.jobs)
        wall = makespan([unit_time(ns, durations) for _, ns in units_of(chosen)], a.jobs)
        files = {n.split('::', 1)[0] for n in nodes}
        covered = {n.split('::', 1)[0] for n in chosen}
        head = [f'# Quick suite for run_suite.py --quick, chosen by --pick-quick {a.pick_quick:g} -j {a.jobs} on '
                f'{time.strftime("%Y-%m-%d")}',
                f'# from {dfile.relative_to(REPO) if dfile.is_relative_to(REPO) else dfile.name}: {len(chosen)} of '
                f'{len(nodes)} tests, {len(covered)} of {len(files)} files, expected {wall:.0f} s.',
                '# The fastest test of every file first, then the fastest of the rest, while the expected wall',
                '# time stays within the limit. Not in the list: ' + (', '.join(sorted(files - covered)) or 'none') + '.',
                '# Regenerate after a full run: .venv/bin/python gateware/tools/run_suite.py --pick-quick 300']
        a.quick_list.write_text('\n'.join(head + chosen) + '\n')
        print(f'{len(chosen)} of {len(nodes)} tests ({len(covered)} of {len(files)} files), '
              f'expected {wall:.0f} s with -j {a.jobs}: {a.quick_list}')
        return 0
    if a.quick:
        listed = read_quick(a.quick_list)
        known = set(nodes)
        missing = [n for n in listed if n not in known]
        if missing:
            print(f'--quick: {len(missing)} tests in {a.quick_list.name} are not collected, e.g. {missing[0]}; '
                  'regenerate the list with --pick-quick after a full run')
            return 2
        listed_set = set(listed)
        nodes = [n for n in nodes if n in listed_set]
    units = units_of(nodes)
    fp = fingerprint()
    run_file, results_file = out / 'run.json', out / 'results.jsonl'
    durations_file = out / 'durations.json'
    durations = json.loads(durations_file.read_text()) if durations_file.exists() else {}
    done = {}
    if a.resume and run_file.exists():
        prev = json.loads(run_file.read_text())
        if prev['fingerprint'] != fp:
            print(f'--resume refused: sources changed since the run in {out} '
                  f'({prev["fingerprint"][:12]} -> {fp[:12]})')
            return 2
        # New manifests bind collected identities; legacy manifests require the
        # same request text as well as complete records for current units.
        same_selection = (set(prev['nodes']) == set(nodes) if 'nodes' in prev else
                          prev.get('paths') == a.paths and prev.get('keyword') == a.keyword)
        if not same_selection:
            print('--resume refused: test selection changed; use a new output directory')
            return 2
        try:
            done = resume_done(read_jsonl(results_file), units)
        except (ValueError, KeyError, TypeError) as exc:
            print(f'--resume refused: {exc}')
            return 2
        results_file.write_text(''.join(json.dumps(r) + '\n' for r in done.values()))
    else:
        for d in ('logs', 'trace'):
            shutil.rmtree(out / d, ignore_errors=True)
        results_file.unlink(missing_ok=True)
    for d in ('logs', 'trace'):
        (out / d).mkdir(parents=True, exist_ok=True)
    run_file.write_text(json.dumps({'fingerprint': fp, 'paths': a.paths, 'keyword': a.keyword, 'nodes': nodes}, indent=1))

    expected = {u: sum(durations.get(n, a.guess) for n in ns) for u, ns in units}
    todo = sorted((u for u in units if u[0] not in done), key=lambda u: -expected[u[0]])
    total = len(units)
    print(f'{len(nodes)} tests in {total} processes, {len(done)} already passed, '
          f'{len(todo)} to run, {a.jobs} at a time; sources {fp[:12]}', flush=True)

    running, finished = [], dict(done)
    next_index = 1 + max([int(Path(r['log']).stem) for r in done.values()] + [0])
    stop = False

    def status():
        st = {'total': total, 'finished': len(finished), 'running': [j.unit for j in running],
              'left': len(todo), 'failed': [u for u, r in finished.items() if not unit_ok(r)],
              'elapsed': round(time.monotonic() - t0, 1)}
        (out / 'status.json').write_text(json.dumps(st, indent=1))

    def on_term(sig, frame):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, on_term)

    try:
        while (todo or running) and not stop:
            while todo and len(running) < a.jobs:
                left = a.budget - (time.monotonic() - t0) if a.budget else None
                pick = next((u for u in todo if left is None or expected[u[0]] <= left), None)
                if pick is None:
                    break
                todo.remove(pick)
                running.append(Job(next_index, pick[0], pick[1], out, a.timeout))
                next_index += 1
            if not running:
                break
            time.sleep(0.5)
            for j in [j for j in running if j.poll() is not None]:
                running.remove(j)
                rec = j.record()
                finished[j.unit] = rec
                with open(results_file, 'a') as f:
                    f.write(json.dumps(rec) + '\n')
                for n, t in rec['tests'].items():
                    if t['outcome'] in ('passed', 'failed', 'xfailed'):
                        durations[n] = t['duration'] if len(rec['nodes']) > 1 else rec['wall']
                word = 'ok  ' if unit_ok(rec) else 'FAIL'
                print(f'[{len(finished):3d}/{total}] {word} {rec["wall"]:7.1f}s {j.unit}', flush=True)
                status()
    finally:
        for j in running:
            j.kill()
        durations_file.write_text(json.dumps(durations, indent=1, sort_keys=True))
        status()

    return finish(out, finished, todo + [(j.unit, j.nodes) for j in running], nodes, t0)


def finish(out, finished, left, nodes, t0):
    counts, bad = {}, []
    expected = dict(units_of(nodes))
    pending = dict(left)
    if len(pending) != len(left):
        bad.append(('pending', 'duplicate pending units', 'scheduler'))
    for u, ns in pending.items():
        if u not in expected or len(ns) != len(set(ns)) or set(ns) != set(expected[u]):
            bad.append((u, 'invalid pending nodes', 'scheduler'))
    for u, ns in expected.items():
        if u not in finished and u not in pending:
            bad.append((u, 'missing completed or pending unit', 'scheduler'))
    for u, rec in finished.items():
        errors = coverage_errors(rec, expected.get(u, []))
        if u not in expected or rec.get('unit') != u or u in pending:
            errors.append('unrequested or inconsistent completed unit')
        for why in errors:
            bad.append((u, why, rec.get('log', 'unknown')))
    for rec in finished.values():
        for n, t in rec['tests'].items():
            counts[t['outcome']] = counts.get(t['outcome'], 0) + 1
            if t['outcome'] not in ('passed', 'skipped', 'xfailed'):
                bad.append((n, t['outcome'], rec['log']))
        if rec['rc'] != 0:
            bad.append((rec['unit'], f'exit status {rec["rc"]}', rec['log']))
    lines = [f'{len(nodes)} tests: ' + ', '.join(f'{v} {k}' for k, v in sorted(counts.items())),
             f'wall time {time.monotonic() - t0:.0f} s (this invocation)']
    for n, why, log in bad:
        lines.append(f'  {why.upper():8s} {n}  ({log})')
    n_left = sum(len(ns) for _, ns in left)
    if n_left:
        lines.append(f'{n_left} tests in {len(left)} processes not run; rerun with --resume')
    slow = sorted(finished.values(), key=lambda r: -r['wall'])[:10]
    lines.append('slowest: ' + ', '.join(f'{r["unit"].split("/")[-1]} {r["wall"]:.0f}s' for r in slow))
    text = '\n'.join(lines) + '\n'
    with open(out / 'report.txt', 'w') as f:
        f.write(text)
        dup = build_dirs.report(build_dirs.load(out), file=f) if (out / 'results.jsonl').exists() else {}
    sys.stdout.write(text)
    if (out / 'results.jsonl').exists():
        build_dirs.report(build_dirs.load(out))
    if bad or dup:
        return 1
    return 3 if n_left else 0


if __name__ == '__main__':
    sys.exit(main())
