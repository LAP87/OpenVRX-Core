"""The build-directory audit (build_dirs.py), the claims suite_trace.py records,
and the scheduling helpers of run_suite.py."""
import json

import build_dirs
import run_suite
import suite_trace


def test_claims_from_cwd_args_and_results_file(tmp_path):
    roots = (str(tmp_path / 'build'),)
    work = tmp_path / 'build' / 'tb_x'
    work.mkdir(parents=True)
    # custom run_sim: iverilog with cwd in the build directory
    assert suite_trace.claims_of(['iverilog', '-o', 'sim.vvp', '-Ptb.N=3', str(tmp_path / 'tb.v')], work,
                                 roots=roots) == {('dir', str(work))}
    # cocotb: vvp runs in the test directory, the build directory only shows in the arguments
    env = {'COCOTB_RESULTS_FILE': str(tmp_path / 'test_x.result.xml')}
    assert suite_trace.claims_of(['vvp', '-M', '/lib', str(work / 'sim.vvp')], tmp_path, env, roots=roots) == {
        ('dir', str(work)), ('file', str(tmp_path / 'test_x.result.xml'))}
    # nothing under a build root, no results file: no claim
    assert suite_trace.claims_of('yosys -p "synth" top.v', tmp_path, {}, roots=roots) == set()


def test_shared_directory_and_results_file_are_duplicates():
    claims = {'a.py::t1': {'dir:gateware/sim/build/tb_m2', 'file:gateware/sim/t.result.xml'},
              'a.py::t2': {'dir:gateware/sim/build/tb_m2', 'file:gateware/sim/u.result.xml'},
              'b.py::t[x]': {'dir:gateware/sim/build/tb_b_x', 'file:gateware/sim/t.result.xml'},
              'b.py::t[y]': {'dir:gateware/sim/build/tb_b_y'}}
    assert build_dirs.duplicates(claims) == {
        'dir:gateware/sim/build/tb_m2': ['a.py::t1', 'a.py::t2'],
        'file:gateware/sim/t.result.xml': ['a.py::t1', 'b.py::t[x]']}


def test_own_directories_pass_and_one_test_may_reuse_its_own():
    claims = {'a.py::t1': {'dir:gateware/sim/build/x'}, 'a.py::t2': {'dir:gateware/sim/build/y'},
              'a.py::t3': set()}
    assert build_dirs.duplicates(claims) == {}


def test_load_takes_the_newest_record_of_a_unit(tmp_path):
    old = {'unit': 'u', 'claims': {'u': ['dir:gateware/sim/build/old']}}
    new = {'unit': 'u', 'claims': {'u': ['dir:gateware/sim/build/new']}}
    other = {'unit': 'v', 'claims': {'v': ['dir:gateware/sim/build/old']}}
    (tmp_path / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (old, new, other)))
    assert build_dirs.load(tmp_path) == {'u': {'dir:gateware/sim/build/new'}, 'v': {'dir:gateware/sim/build/old'}}


def test_trace_outcome_words():
    assert suite_trace.outcome({'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}) == 'passed'
    assert suite_trace.outcome({'setup': 'passed', 'call': 'failed', 'teardown': 'passed'}) == 'failed'
    assert suite_trace.outcome({'setup': 'skipped', 'teardown': 'passed'}) == 'skipped'
    assert suite_trace.outcome({'setup': 'passed', 'call': 'xfailed', 'teardown': 'passed'}) == 'xfailed'
    assert suite_trace.outcome({'setup': 'passed', 'call': 'passed', 'teardown': 'failed'}) == 'error'
    assert suite_trace.outcome({'setup': 'passed'}) == 'error'


def test_units_one_process_per_simulation_test_one_per_python_file():
    nodes = ['gateware/model/test_a.py::t1', 'gateware/model/test_a.py::t2', 'gateware/sim/test_b.py::t[1]',
             'gateware/sim/test_b.py::t[2]', 'gateware/tools/test_c.py::t', 'mixer/test_d.py::t']
    assert run_suite.units_of(nodes) == [
        ('gateware/model/test_a.py', ['gateware/model/test_a.py::t1', 'gateware/model/test_a.py::t2']),
        ('gateware/sim/test_b.py::t[1]', ['gateware/sim/test_b.py::t[1]']),
        ('gateware/sim/test_b.py::t[2]', ['gateware/sim/test_b.py::t[2]']),
        ('gateware/tools/test_c.py::t', ['gateware/tools/test_c.py::t']),
        ('mixer/test_d.py', ['mixer/test_d.py::t'])]


def test_unit_ok_needs_exit_status_zero_and_no_failed_test():
    rec = {'nodes': ['a', 'b'], 'rc': 0, 'tests': {'a': {'outcome': 'passed'}, 'b': {'outcome': 'skipped'}}}
    assert run_suite.unit_ok(rec)
    assert not run_suite.unit_ok({**rec, 'rc': 1})
    assert not run_suite.unit_ok({'nodes': ['a'], 'rc': 0, 'tests': {'a': {'outcome': 'missing'}}})
    assert not run_suite.unit_ok({'nodes': ['a'], 'rc': 0, 'tests': {'a': {'outcome': 'xpassed'}}})
