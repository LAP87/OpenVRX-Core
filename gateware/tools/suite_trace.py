"""pytest plugin used by run_suite.py: records, per test, its outcome and every
build directory and cocotb results file its subprocesses use.

Loaded with `-p suite_trace` (gateware/tools on PYTHONPATH); writes JSON to the
path in OPENVRX_SUITE_TRACE after every test, so a killed process keeps what it
had finished. Claims are what build_dirs.py audits:

- the working directory of a subprocess, when it lies under a build root;
- a path argument under a build root (its parent when it is not a directory);
- the cocotb results file (COCOTB_RESULTS_FILE in the subprocess environment).

Build roots are gateware/build, gateware/sim/build and gateware/formal/build.
"""
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
ROOTS = tuple(str(REPO / 'gateware' / p) for p in ('build', 'sim/build', 'formal/build'))
COLLECT = '<collect>'


def under_roots(path, roots=ROOTS):
    path = os.path.normpath(path)
    return any(path == r or path.startswith(r + os.sep) for r in roots)


def rel(path):
    try:
        return Path(path).relative_to(REPO).as_posix()
    except ValueError:
        return Path(path).as_posix()


def claims_of(args, cwd=None, env=None, roots=ROOTS):
    """Build directories and results files one subprocess call uses (absolute paths)."""
    cwd = os.path.abspath(cwd if cwd is not None else os.getcwd())
    if isinstance(args, (str, bytes, os.PathLike)):
        args = shlex.split(os.fsdecode(args)) if isinstance(args, (str, bytes)) else [args]
    out = set()
    if under_roots(cwd, roots):
        out.add(('dir', cwd))
    for a in args:
        a = os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a)
        for tok in {a, a.split('=', 1)[-1]}:
            if not tok or tok.startswith('-'):
                continue
            p = os.path.normpath(os.path.join(cwd, tok))
            if under_roots(p, roots):
                out.add(('dir', p if os.path.isdir(p) else os.path.dirname(p)))
    results = (env or {}).get('COCOTB_RESULTS_FILE')
    if results:
        out.add(('file', os.path.abspath(results)))
    return out


class Trace:
    def __init__(self, path):
        self.path = path
        self.current = COLLECT
        self.claims = {}
        self.reports = {}

    def record(self, args, cwd, env):
        for kind, p in claims_of(args, cwd, env):
            self.claims.setdefault(self.current, set()).add(f'{kind}:{rel(p)}')

    def report(self, rep):
        r = self.reports.setdefault(rep.nodeid, {'phases': {}, 'duration': 0.0})
        r['duration'] += rep.duration
        outcome = rep.outcome
        if hasattr(rep, 'wasxfail'):
            outcome = 'xfailed' if rep.skipped else 'xpassed'
        r['phases'][rep.when] = outcome

    def dump(self):
        if not self.path:
            return
        data = {'claims': {k: sorted(v) for k, v in self.claims.items()},
                'tests': {k: {'outcome': outcome(v['phases']), 'duration': round(v['duration'], 3)}
                          for k, v in self.reports.items()},
                'written': time.time()}
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)


def outcome(phases):
    """One word per test from its setup/call/teardown reports."""
    if phases.get('setup') == 'failed' or phases.get('teardown') == 'failed':
        return 'error'
    for p in ('setup', 'call'):
        if phases.get(p) in ('failed', 'skipped', 'xfailed', 'xpassed'):
            return phases[p]
    return 'passed' if phases.get('call') == 'passed' else 'error'


TRACE = Trace(os.environ.get('OPENVRX_SUITE_TRACE'))
_Popen = subprocess.Popen


class _TracedPopen(_Popen):
    def __init__(self, args, *a, **kw):
        try:
            TRACE.record(args, kw.get('cwd'), kw.get('env', os.environ))
        except Exception:                       # tracing must never change a test's result
            pass
        super().__init__(args, *a, **kw)


subprocess.Popen = _TracedPopen


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    TRACE.current = item.nodeid
    yield
    TRACE.current = COLLECT
    TRACE.dump()


def pytest_runtest_logreport(report):
    TRACE.report(report)


def pytest_sessionfinish(session, exitstatus):
    TRACE.dump()
