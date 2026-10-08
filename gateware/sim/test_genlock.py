"""Cycle-level contract tests for genlock_timing.v using the native Icarus simulator.

The bench is deliberately independent of fb_backend and SDRAM. Python drives only
rst, lock, trig and h_alt, then checks the public timing outputs from every pixel
clock. No internal DUT state is observed.
"""
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
RTL = GW / 'rtl' / 'genlock_timing.v'

DEFAULT = dict(H_ACTIVE=4, H_FP=1, H_SYNC=1, H_BP=2, H_FP_ALT=3,
               V_ACTIVE=8, V_FP=2, V_SYNC=2, V_BP=4,
               H_POL=1, V_POL=1, MAX_WAIT=8, JUMP_AFTER=3, HOLD=32)
LOCKED = dict(H_ACTIVE=4, H_FP=1, H_SYNC=1, H_BP=2, H_FP_ALT=1,
              V_ACTIVE=24, V_FP=3, V_SYNC=3, V_BP=18,
              H_POL=1, V_POL=1, MAX_WAIT=8, JUMP_AFTER=3, HOLD=32)
FULL_LOCKED = {**LOCKED, 'V_ACTIVE': 720, 'V_FP': 5, 'V_SYNC': 5, 'V_BP': 20}
OLD_JUMP = """vc <= (vc < V_SYNC_START) ? V_SYNC_START :
                      (vc == V_SYNC_END - 1) ? V_TOTAL - 1 : vc + 12'd1;"""
NO_RECOVERY = "recover <= cut; cut <= 1'b0;"


def encode(rst=0, lock=0, trig=0, h_alt=0):
    return (bool(rst) << 3) | (bool(lock) << 2) | (bool(trig) << 1) | bool(h_alt)


def vectors_for(n, *, lock=0, h_alt=0):
    return [encode(rst=i < 2, lock=lock, h_alt=h_alt) for i in range(n)]


def run_sim(tmp_path, vectors, params=DEFAULT, mutate=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = tmp_path / ('run_' + str(len(list(tmp_path.iterdir()))))
    work.mkdir(parents=True)
    (work / 'vectors.hex').write_text(''.join(f'{v:x}\n' for v in vectors))
    source = RTL.read_text()
    if mutate == 'old_jump':
        assert source.count(OLD_JUMP) == 1, 'cannot install old jump negative control'
        source = source.replace(OLD_JUMP, "vc <= V_TOTAL - 1;")
    elif mutate == 'no_recovery':
        assert source.count(NO_RECOVERY) == 1, 'cannot disable recovery for negative control'
        source = source.replace(NO_RECOVERY, "recover <= 1'b0; cut <= 1'b0;")
    assert mutate in (None, 'old_jump', 'no_recovery')
    (work / 'genlock_timing.v').write_text(source)

    env = dict(os.environ)
    bundled = PROJECT / '.tools' / 'iverilog' / 'bin'
    if bundled.exists():
        env['PATH'] = str(bundled) + os.pathsep + env['PATH']
    values = {**params, 'N_CYCLES': len(vectors)}
    subprocess.run(
        ['iverilog', '-g2012', '-s', 'tb_genlock', '-o', 'sim.vvp',
         *[f'-Ptb_genlock.{k}={v}' for k, v in values.items()],
         str(work / 'genlock_timing.v'), str(HERE / 'tb_genlock.v')],
        cwd=work, env=env, check=True, capture_output=True, text=True)
    subprocess.run(
        ['vvp', '-n', 'sim.vvp', f'+VECTORS={work / "vectors.hex"}', f'+TRACE={work / "trace.txt"}'],
        cwd=work, env=env, check=True, capture_output=True, text=True)
    rows = []
    def value(token):
        return int(token) if token.isdigit() else None

    for line in (work / 'trace.txt').read_text().splitlines():
        cycle, frame_start, y, x, vsync, de, triggered = line.split()
        row = dict(cycle=int(cycle), frame_start=value(frame_start), y=value(y), x=value(x),
                   vsync=value(vsync), de=value(de), triggered=value(triggered))
        rows.append(row)
    assert len(rows) == len(vectors), f'{len(rows)} outputs for {len(vectors)} input clocks'
    return rows


def valid_from(vectors):
    reset_cycles = [i for i, v in enumerate(vectors) if v & 8]
    return (max(reset_cycles) + 1) if reset_cycles else 0


def frame_starts(rows, vectors):
    first = valid_from(vectors)
    return [r['cycle'] for r in rows if r['cycle'] >= first and r['frame_start']]


def assert_vsync_contract(rows, vectors, params):
    """Every complete frame has one full-width vsync pulse and intact active/sync rows."""
    v_sync_start = params['V_ACTIVE'] + params['V_FP']
    v_sync_end = v_sync_start + params['V_SYNC']
    starts = frame_starts(rows, vectors)
    assert len(starts) >= 4, f'too few complete frames: {starts}'
    failures = []
    for a, b in zip(starts, starts[1:]):
        frame = rows[a:b]
        active_line = [r for r in frame if r['y'] == 0 and r['x'] is not None]
        h_total = max((r['x'] for r in active_line), default=-1) + 1
        if h_total <= 0:
            failures.append((a, 'missing active line 0'))
            continue
        alt_at_wrap = vectors[a - 1] & 1
        expected_h = (params['H_ACTIVE'] + (params['H_FP_ALT'] if alt_at_wrap else params['H_FP']) +
                      params['H_SYNC'] + params['H_BP'])
        if h_total != expected_h:
            failures.append((a, f'horizontal total {h_total}, input-selected total {expected_h}'))
        active = [i for i, r in enumerate(frame) if r['vsync'] == params['V_POL']]
        runs = []
        for i in active:
            if not runs or i != runs[-1][-1] + 1:
                runs.append([i])
            else:
                runs[-1].append(i)
        if len(runs) != 1 or len(runs[0]) != params['V_SYNC'] * h_total:
            failures.append((a, len(runs), [len(r) for r in runs]))
            continue
        pulse = [frame[i] for i in runs[0]]
        if ({r['y'] for r in pulse} != set(range(v_sync_start, v_sync_end)) or
                any(r['x'] >= h_total or r['de'] for r in pulse)):
            failures.append((a, 'bad pulse geometry'))
        if frame[0]['x'] != 0 or frame[0]['y'] != 0:
            failures.append((a, 'frame start is not at (0, 0)'))
    assert not failures, f'vsync contract failures: {failures[:8]}'


def expected_free_run(vectors, params):
    """Mathematical free-run raster model, with h_alt sampled at each frame wrap."""
    hc = vc = alt = started = 0
    out = []
    v_sync_start = params['V_ACTIVE'] + params['V_FP']
    v_sync_end = v_sync_start + params['V_SYNC']
    v_total = v_sync_end + params['V_BP']
    for inp in vectors:
        rst, lock, trig, h_alt = ((inp >> 3) & 1, (inp >> 2) & 1,
                                  (inp >> 1) & 1, inp & 1)
        fp = params['H_FP_ALT'] if alt else params['H_FP']
        h_total = params['H_ACTIVE'] + fp + params['H_SYNC'] + params['H_BP']
        line_end = hc == h_total - 1
        out.append(dict(frame_start=int(hc == 0 and vc == 0), x=hc, y=vc,
                        vsync=(params['V_POL'] if v_sync_start <= vc < v_sync_end else 1 - params['V_POL']),
                        de=int(hc < params['H_ACTIVE'] and vc < params['V_ACTIVE']),
                        triggered=started))
        if rst:
            hc = vc = alt = started = 0
        elif line_end:
            hc = 0
            if vc == v_total - 1:
                vc = 0
                alt = h_alt
                started = 0
            else:
                vc += 1
        else:
            hc += 1
    return out


@pytest.mark.parametrize('vertical', [
    dict(V_ACTIVE=8, V_FP=2, V_SYNC=2, V_BP=4),
    dict(V_ACTIVE=720, V_FP=5, V_SYNC=5, V_BP=20),
])
def test_free_run_matches_raster_model(tmp_path, vertical):
    """Both a short raster and 750-line 720p geometry follow the pixel model exactly."""
    params = {**DEFAULT, **vertical}
    v_total = sum(vertical.values())
    h_max = params['H_ACTIVE'] + params['H_FP_ALT'] + params['H_SYNC'] + params['H_BP']
    count = 2 + 3 * v_total * h_max + 4
    vectors = []
    for i in range(count):
        alt = int((i // (v_total * h_max // 2 + 1)) % 2 == 1)
        # Free-run ignores triggers. The changing h_alt is latched only at a frame wrap.
        vectors.append(encode(rst=i < 2, lock=0, trig=int(i % 97 == 13), h_alt=alt))
    rows = run_sim(tmp_path, vectors, params)
    model = expected_free_run(vectors, params)
    first = valid_from(vectors)
    for i in range(first, len(rows)):
        got = {k: rows[i][k] for k in model[i]}
        want = model[i]
        assert got == want, f'cycle {i}: output {got}, raster model {want}'
    assert len(frame_starts(rows, vectors)) >= 3


def moved_source(params):
    """Reproduce a stable source that moves phase after eight fields, then stays periodic."""
    h_total = params['H_ACTIVE'] + params['H_FP'] + params['H_SYNC'] + params['H_BP']
    v_total = params['V_ACTIVE'] + params['V_FP'] + params['V_SYNC'] + params['V_BP']
    period = h_total * v_total
    shift = 31 * h_total
    first = (v_total - 1) * h_total + 2
    triggers = [first + k * period + (shift if k >= 8 else 0) for k in range(20)]
    count = triggers[-1] + 3 * period
    ts = set(triggers)
    vectors = [encode(rst=i < 2, lock=1, trig=i in ts) for i in range(count)]
    return vectors, triggers, h_total, v_total


def phase_delays(rows, vectors, triggers):
    starts = frame_starts(rows, vectors)
    return [next((s - t for s in starts if s >= t), None) for t in triggers]


def first_three_early_trigger_indices(rows, vectors, triggers, params):
    v_sync_start = params['V_ACTIVE'] + params['V_FP']
    early = []
    for i, cycle in enumerate(triggers):
        y = rows[cycle]['y']
        early.append(y is not None and y < v_sync_start)
    for i in range(2, len(early)):
        if early[i - 2:i + 1] == [True, True, True]:
            return i
    return None


@pytest.mark.parametrize('params', [LOCKED, FULL_LOCKED], ids=['small', '720p'])
def test_periodic_source_move_keeps_full_vsync_and_recovers(tmp_path, params):
    """A stable source moves by 31 lines; sync remains whole and starts rejoin its phase."""
    vectors, triggers, h_total, v_total = moved_source(params)
    rows = run_sim(tmp_path, vectors, params)
    assert_vsync_contract(rows, vectors, params)

    delays = phase_delays(rows, vectors, triggers)
    starts = frame_starts(rows, vectors)
    frame_lengths = [b - a for a, b in zip(starts, starts[1:])]
    short = [i for i, n in enumerate(frame_lengths) if n < (v_total - 1) * h_total]
    # The cut and its one recovery frame are the only adjacent short intervals.
    assert len(short) == 2 and short[1] == short[0] + 1, frame_lengths
    recovery = rows[starts[short[1]]:starts[short[1] + 1]]
    line_starts = [r['y'] for r in recovery if r['x'] == 0]
    sync_end = params['V_ACTIVE'] + params['V_FP'] + params['V_SYNC']
    assert line_starts[:sync_end] == list(range(sync_end)), line_starts
    assert len(line_starts) >= sync_end + 1, line_starts
    assert line_starts[-1] == v_total - 1, line_starts
    last_porch = [r for r in recovery if r['y'] == v_total - 1]
    assert [r['x'] for r in last_porch] == list(range(h_total)), last_porch
    assert all(not r['de'] and r['vsync'] != params['V_POL'] for r in last_porch), last_porch

    third_early = first_three_early_trigger_indices(rows, vectors, triggers, params)
    assert third_early is not None and third_early + 2 < len(triggers), delays
    # The first periodic trigger can be one or two lines before frame start. By the second
    # following trigger, frame start must be no more than one horizontal line behind it.
    assert 0 <= delays[third_early + 2] <= h_total, delays


def test_jump_on_last_front_porch_pixel_does_not_repeat_sync(tmp_path):
    """The third early trigger on the last front-porch pixel must leave a full sync pulse."""
    params = LOCKED
    h_total = params['H_ACTIVE'] + params['H_FP'] + params['H_SYNC'] + params['H_BP']
    v_sync_start = params['V_ACTIVE'] + params['V_FP']
    count = 2 + 4 * (params['V_ACTIVE'] + params['V_FP'] + params['V_SYNC'] + params['V_BP']) * h_total
    baseline = vectors_for(count, lock=1)
    base_rows = run_sim(tmp_path / 'base', baseline, params)
    target = next(r['cycle'] for r in base_rows if r['y'] == v_sync_start - 1 and r['x'] == h_total - 1)
    vectors = list(baseline)
    early = [r['cycle'] for r in base_rows if r['y'] in (1, 2) and r['x'] == 2][:2]
    assert len(early) == 2 and target > early[-1]
    for cycle in (*early, target):
        vectors[cycle] |= 2
    rows = run_sim(tmp_path / 'edge', vectors, params)
    assert_vsync_contract(rows, vectors, params)


def test_lock_and_h_alt_changes_keep_frame_geometry(tmp_path):
    """Changing lock and the porch selector changes frame widths only at a wrap."""
    params = {**LOCKED, 'H_FP_ALT': 3}
    h_total = params['H_ACTIVE'] + params['H_FP'] + params['H_SYNC'] + params['H_BP']
    v_total = params['V_ACTIVE'] + params['V_FP'] + params['V_SYNC'] + params['V_BP']
    count = 2 + 8 * v_total * (h_total + 2)
    period = v_total * h_total
    vectors = []
    for i in range(count):
        lock = int(2 * v_total * h_total <= i < 6 * v_total * (h_total + 2))
        trig = int(lock and i >= 2 * v_total * h_total and (i - 2 * v_total * h_total) % period == 0)
        h_alt = int(i >= 3 * v_total * h_total and (i // (v_total * h_total)) % 2 == 1)
        vectors.append(encode(rst=i < 2, lock=lock, trig=trig, h_alt=h_alt))
    rows = run_sim(tmp_path, vectors, params)
    assert_vsync_contract(rows, vectors, params)


def test_old_last_line_jump_is_caught_by_vsync_count(tmp_path):
    """Negative control: restore the old jump straight to V_TOTAL-1 rule."""
    params = LOCKED
    vectors, _, _, _ = moved_source(params)
    rows = run_sim(tmp_path, vectors, params, mutate='old_jump')
    with pytest.raises(AssertionError, match='vsync contract failures'):
        assert_vsync_contract(rows, vectors, params)


@pytest.mark.parametrize('params', [LOCKED, FULL_LOCKED], ids=['small', '720p'])
def test_disabling_recovery_is_caught_by_phase_contract(tmp_path, params):
    """Negative control: without recovery, phase has not rejoined by the second trigger."""
    vectors, triggers, h_total, _ = moved_source(params)
    rows = run_sim(tmp_path, vectors, params, mutate='no_recovery')
    delays = phase_delays(rows, vectors, triggers)
    third_early = first_three_early_trigger_indices(rows, vectors, triggers, params)
    assert third_early is not None and third_early + 2 < len(triggers), delays
    assert delays[third_early + 2] is not None and delays[third_early + 2] > h_total, \
        f'negative control escaped: {delays}'
