"""noise_stats.v inside mixer2: luma samples outside 16..235, per line and per window,
against luma_outside() in model/bt656.py.

Channel A gets the vector with injected spikes (vectors/ntsc_spikes, written by
model/make_vectors.py), channel B pal_faults (snow and a truncated line). Every
line's count and every window sum must match the model. Windows are 8 lines here.

Negative controls: the same run with a copy of noise_stats.v that takes 15..236 as
in range, or counts the chroma bytes instead of the luma bytes, must not match.

Run: .venv/bin/python -m pytest -q gateware/sim/test_noise_stats.py"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
VECTORS = GW / 'vectors'
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402

LOG_N = 3
RTL = ('bt656_rx.v', 'word_packer.v', 'async_fifo.v', 'dual_clock_ram.v', 'chan_capture.v', 'mix_chan.v',
       'line_mixer.v', 'snow_stats.v', 'mixer2.v')
MUTANTS = {
    'range_15_236': ("(y < 8'd16) || (y > 8'd235)", "(y < 8'd15) || (y > 8'd236)"),
    'chroma': ("outside(data[15:8])} + {1'b0, outside(data[31:24])",
               "outside(data[7:0])} + {1'b0, outside(data[23:16])"),
}
RESTART_OLD = ("line_count <= (tag == cnt_tag) ? cnt : 10'd0;", "line_count <= cnt;")


def vector(name):
    return bytes(int(x, 16) for x in (VECTORS / f'{name}.hex').read_text().split())


def expected(name):
    """(field, line, count) per line, as model/make_vectors.py wrote them."""
    return [(r['field'], r['line_in_field'], r['luma_outside'])
            for r in json.loads((VECTORS / f'{name}.expected.json').read_text())]


def windows(lines):
    n = 1 << LOG_N
    c = [x[2] for x in lines]
    return [sum(c[i:i + n]) for i in range(0, len(c) - n + 1, n)]


def run(mutant=None, a_name='ntsc_spikes', b_name='pal_faults', alter=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_noise_stats_{mutant or "rtl"}_{a_name}{"_alt" if alter else ""}'
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'noise_stats.v').read_text()
    if mutant:
        old, new = MUTANTS[mutant]
        assert src.count(old) == 1, f'{mutant}: the text to alter is not in noise_stats.v once'
        src = src.replace(old, new)
    if alter:
        assert src.count(alter[0]) == 1
        src = src.replace(*alter)
    (work / 'noise_stats.v').write_text(src)
    a, b = vector(a_name), vector(b_name)
    bt656.write_hex(work / 'a.hex', a)
    bt656.write_hex(work / 'b.hex', b)
    params = dict(N_A=len(a), N_B=len(b), LOG_N=LOG_N)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_noise_stats',
                    *[f'-Ptb_noise_stats.{k}={v}' for k, v in params.items()],
                    *[str(GW / 'rtl' / n) for n in RTL], str(work / 'noise_stats.v'), str(HERE / 'tb_noise_stats.v')],
                   cwd=work, env=env, check=True)
    log = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert 'END' in log, log[-2000:]
    get = lambda tag: [tuple(int(x) for x in m) for m in re.findall(rf'^{tag} (\d+) (\d+) (\d+)$', log, re.M)]  # noqa: E731
    return dict(la=get('LA'), lb=get('LB'),
                wa=[int(x) for x in re.findall(r'^WA (\d+)$', log, re.M)],
                wb=[int(x) for x in re.findall(r'^WB (\d+)$', log, re.M)])


def test_vector_has_what_it_claims():
    """The spikes vector carries the boundary values, chroma outside the range and clean lines,
    and its expected counts are the model's."""
    recs = bt656.Receiver().feed(vector('ntsc_spikes'))
    assert len(recs) == 37 and [r.line_in_field for r in recs] == list(range(37))
    luma = [y for r in recs for y in r.luma]
    chroma = [c for r in recs for c in r.active[0::2]]
    assert {1, 15, 236, 254} <= set(luma) and {16, 235} <= set(luma)
    assert any(c < 16 or c > 235 for c in chroma)
    counts = [bt656.luma_outside(r.active) for r in recs]
    assert counts == [c for _, _, c in expected('ntsc_spikes')]
    assert counts.count(0) >= 7 and max(counts) >= 40
    assert counts != [bt656.luma_outside(r.active, 15, 236) for r in recs]


def test_noise_stats_matches_model():
    r = run()
    ea, eb = expected('ntsc_spikes'), expected('pal_faults')
    assert r['la'] == ea, (r['la'], ea)
    assert r['lb'] == eb, (r['lb'], eb)
    assert r['wa'] == windows(ea) and len(r['wa']) == 4, (r['wa'], windows(ea))
    assert r['wb'] == windows(eb) and len(r['wb']) == 1, (r['wb'], windows(eb))
    assert sum(c for _, _, c in eb) > 0, 'the snow line of pal_faults has luma outside the range'


def test_line_started_again_counts_its_own_bytes():
    """An extra SAV 1435 bytes into a line's active part starts a line with one active byte and
    no whole word. Its count is 0, as luma_outside() gives; noise_stats.v gave it the spikes of
    the line before, whose marker never came, because it reset its count only on word 0 (found
    by sim/test_fuzz_chain.py, round r2, seed 166)."""
    e = expected('ntsc_restart')
    assert any(r.active_count == 1 for r in bt656.Receiver().feed(vector('ntsc_restart')))
    r = run(a_name='ntsc_restart')
    assert r['la'] == e, (r['la'], e)


def test_line_started_again_check_is_tested():
    """Negative control: the count taken at the marker whatever line its words came from."""
    r = run(a_name='ntsc_restart', alter=RESTART_OLD)
    assert len(r['la']) == len(expected('ntsc_restart')) and r['la'] != expected('ntsc_restart')


@pytest.mark.parametrize('mutant', sorted(MUTANTS))
def test_noise_stats_negative_control(mutant):
    r = run(mutant)
    assert len(r['la']) == len(expected('ntsc_spikes')), 'the altered copy still runs'
    assert r['la'] != expected('ntsc_spikes')
