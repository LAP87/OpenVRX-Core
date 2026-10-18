"""rssi_adc.v against sim/ads1115_model.v, round by round against model/rssi_ref.py, on one I2C
bus with tvp_ctrl and ssd1306_text wired as in M6 (sim/tb_rssi_adc.v).

Scenario (one line of SCHED per round): uncalibrated readings; a calibration over three rounds;
receiver A falls below 20 % for three rounds and warns; B falls too and neither warns; A
recovers and B warns; no ADC (no acknowledge: no valid reading, no warning); 20 % exactly is
not low, one code below is; a calibration with too small a span leaves the channels
uncalibrated; ranges loaded from saved settings; inputs below ground and above full scale.
Every round's raw values, ranges, calibration flags, percentages, low and warn flags must
equal the model's. No two masters may run a transaction in the same clock, and the OLED,
tvp_ctrl and the ADC must all have used the bus.

Negative controls: reading the conversion register before the conversion ends (CONV_US 500)
gives the previous channel's code; a copy that warns without looking at the other channel
warns when both are low; one that does not wait for the other masters collides with them;
N_LOW = 1 warns two rounds early. Each must disagree with the model or show collisions.

Run: .venv/bin/python -m pytest -q gateware/sim/test_rssi_adc.py"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import rssi_ref as ref  # noqa: E402

V = 1_000_000                                       # microvolts per volt
# (uV A, uV B, absent, cal, load (min_a, max_a, min_b, max_b) or None)
SCHED = [
    (1.0 * V, 1.1 * V, 0, 0, None),                 # 0, 1 uncalibrated
    (1.0 * V, 1.1 * V, 0, 0, None),
    (0.5 * V, 0.6 * V, 0, 1, None),                 # 2..4 calibration: A 0.5..1.5 V, B 0.6..1.6 V
    (1.5 * V, 1.6 * V, 0, 1, None),
    (1.0 * V, 1.0 * V, 0, 1, None),
    (1.2 * V, 1.3 * V, 0, 0, None),                 # 5 calibrated
    (0.6 * V, 1.4 * V, 0, 0, None),                 # 6..8 A at 10 %: low and warning in the third round
    (0.6 * V, 1.4 * V, 0, 0, None),
    (0.6 * V, 1.4 * V, 0, 0, None),
    (0.6 * V, 0.62 * V, 0, 0, None),                # 9..11 B falls to 2 %: A (10 %) is no longer 10 points below, no
    (0.6 * V, 0.62 * V, 0, 0, None),
    (0.6 * V, 0.62 * V, 0, 0, None),
    (1.4 * V, 0.62 * V, 0, 0, None),                # 12 A recovers: B warns
    (1.4 * V, 0.62 * V, 1, 0, None),                # 13 no ADC: nothing valid, no warning
    (0.7 * V, 1.4 * V, 0, 0, None),                 # 14..16 20 % exactly: not low
    (0.7 * V, 1.4 * V, 0, 0, None),
    (0.7 * V, 1.4 * V, 0, 0, None),
    (699_920, 1.4 * V, 0, 0, None),                 # 17..19 one code below 20 %: low in the third round
    (699_920, 1.4 * V, 0, 0, None),
    (699_920, 1.4 * V, 0, 0, None),
    (1.0 * V, 1.0 * V, 0, 1, None),                 # 20 calibration with one reading: span 0
    (0.6 * V, 1.4 * V, 0, 0, None),                 # 21..23 uncalibrated again: no warning
    (0.6 * V, 1.4 * V, 0, 0, None),
    (0.6 * V, 1.4 * V, 0, 0, None),
    (0.6 * V, 1.4 * V, 0, 0, (4000, 12000, 4800, 12800)),   # 24..26 saved ranges: A warns again
    (0.6 * V, 1.4 * V, 0, 0, None),
    (0.6 * V, 1.4 * V, 0, 0, None),
    (-0.1 * V, 4.2 * V, 0, 0, None),                # 27 below ground (0) and above full scale (7FFFh)
    (0.69 * V, 0.81 * V, 0, 0, None),               # 28..30 A 19 %, B 21 %: A low, but two points are no margin
    (0.69 * V, 0.81 * V, 0, 0, None),               #        (MARGIN_PCT = 10): nobody warns (Core #21)
    (0.69 * V, 0.81 * V, 0, 0, None),
]


def model(sched, n_low=ref.N_LOW, absent_ok=True):
    m = ref.Rssi(n_low=n_low)
    out = []
    for uva, uvb, absent, cal, ld in sched:
        m.set_cal(bool(cal))
        if ld:
            m.load(*ld)
        codes = (None, None) if absent else (ref.code(uva), ref.code(uvb))
        s = m.round(codes)
        out.append((*s['raw'], *s['valid'], s['mn'][0], s['mx'][0], s['mn'][1], s['mx'][1], *s['cal_ok'],
                    *s['pct'], *s['low'], *s['warn']))
    return out


MUTANTS = {
    'warns_without_the_other': [
        ("warn <= {nb == N_LOW && na != N_LOW && cal_ok[0] && valid[0] && ({1'b0, p_a} >= {1'b0, p_b} + MARGIN_PCT),", "warn <= {nb == N_LOW,"),
        ("                         na == N_LOW && nb != N_LOW && cal_ok[1] && valid[1] && ({1'b0, p_b} >= {1'b0, p_a} + MARGIN_PCT)};", "                         na == N_LOW};"),
    ],
    'ignores_other_masters': [("if (free_cnt == 2'd2 && !other_active && !busy) begin", "if (!busy) begin")],
    'n_low_1': [("    parameter N_LOW = 3,", "    parameter N_LOW = 1,")],
    'no_margin': [("    parameter MARGIN_PCT = 10,", "    parameter MARGIN_PCT = 0,")],
}


def run(name, params=None, mutant=None, sched=SCHED):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src = (GW / 'rtl' / 'rssi_adc.v').read_text()
    for old, new in MUTANTS.get(mutant, []):
        assert src.count(old) == 1, (mutant, old)
        src = src.replace(old, new)
    (work / 'rssi_adc.v').write_text(src)
    lines = []
    for uva, uvb, absent, cal, ld in sched:
        lmin = ld or (0, 0, 0, 0)
        lines.append(f'{int(uva)} {int(uvb)} {absent} {cal} {1 if ld else 0} {" ".join(map(str, lmin))}')
    (work / 'sched.txt').write_text('\n'.join(lines) + '\n')
    rtl = [GW / 'rtl' / n for n in ('i2c_master.v', 'tvp_ctrl.v', 'ssd1306_text.v')]
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_rssi_adc', f'-I{GW / "rtl"}',
                    *[f'-Ptb_rssi_adc.{k}={v}' for k, v in (params or {}).items()],
                    *map(str, rtl), str(work / 'rssi_adc.v'), str(HERE / 'ads1115_model.v'), str(HERE / 'tb_rssi_adc.v')],
                   cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    rounds, coll, act = [], None, None
    for line in (work / 'out.txt').read_text().splitlines():
        p = line.split()
        if p[0] == 'R':
            rounds.append(tuple(int(x) for x in p[1:]))
        elif p[0] == 'COLL':
            coll = int(p[1])
        elif p[0] == 'ACT':
            act = tuple(int(x) for x in p[1:])
    return rounds, coll, act


def test_model_scenario_says_what_it_claims():
    rows = model(SCHED)
    warn = [(r[14], r[15]) for r in rows]
    low = [(r[12], r[13]) for r in rows]
    assert [w for w in warn[:6]] == [(0, 0)] * 6 and rows[5][8:10] == (1, 1)
    assert warn[6:9] == [(0, 0), (0, 0), (1, 0)], 'A warns in its third low round'
    assert warn[9:12] == [(0, 0), (0, 0), (0, 0)] and low[11] == (1, 1), 'B two points below A: no margin, then both low'
    assert warn[12] == (0, 1) and rows[13][2:4] == (0, 0) and warn[13] == (0, 0)
    assert rows[14][10] == 20 and low[14:17] == [(0, 0)] * 3
    assert rows[17][10] == 19 and low[17:20] == [(0, 0), (0, 0), (1, 0)]
    assert rows[21][8:10] == (0, 0) and warn[21:24] == [(0, 0)] * 3, 'a failed calibration: no warnings'
    assert rows[24][8:10] == (1, 1) and warn[24:27] == [(0, 0), (0, 0), (1, 0)]
    assert rows[27][:2] == (0, 32767)
    assert low[28:31] == [(1, 0)] * 3 and warn[28:31] == [(0, 0)] * 3, 'A 19 %, B 21 %: low, but no warning without a margin of 10'


def test_rssi_adc_matches_model():
    got, coll, act = run('tb_rssi_adc')
    want = model(SCHED)
    assert len(got) == len(want)
    for i, (g, w) in enumerate(zip(got, want)):
        assert g == w, f'round {i}: rtl {g}\nmodel {w}'
    assert coll == 0, f'{coll} clocks with two masters on the bus'
    frames, init_done, conversions = act
    assert frames > 0 and init_done == 1, 'the OLED and tvp_ctrl used the bus too'
    assert conversions == 2 * sum(1 for s in SCHED if not s[2])


@pytest.mark.parametrize('case', ['conversion_not_awaited', 'warns_without_the_other', 'ignores_other_masters',
                                  'n_low_1', 'no_margin'])
def test_rssi_adc_negative_control(case):
    if case == 'conversion_not_awaited':
        got, coll, _ = run('tb_rssi_adc_early', params={'CONV_US': 500})
    else:
        got, coll, _ = run(f'tb_rssi_adc_{case}', mutant=case)
    want = model(SCHED)
    if case == 'ignores_other_masters':
        assert coll > 0
        return
    assert got != want and coll == 0
    if case == 'warns_without_the_other':
        assert got[11][14:16] == (1, 1) and want[11][14:16] == (0, 0)
    if case == 'no_margin':
        assert got[30][14:16] == (1, 0) and want[30][14:16] == (0, 0), 'without the margin A warns at 19 % against 21 %'
    if case == 'n_low_1':
        assert got == model(SCHED, n_low=1), 'the copy is the model with N_LOW = 1'
