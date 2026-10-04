import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import analyze_latency as al  # noqa: E402

LED = (40, 40, 20, 20)
SCREEN_A = (200, 100, 40, 30)
SCREEN_B = (300, 200, 40, 30)


def make_video(path, fps_container, n_frames, delays_frames, rise_frames=2, seed=1):
    """LED square blinks with random period; each screen square follows after its delay
    with a linear rise over rise_frames (like a slow LCD) plus sensor noise."""
    rng = random.Random(seed)
    led = np.zeros(n_frames)
    t = 10
    while t < n_frames - 40:
        on = rng.randint(30, 50)
        led[t:t + on] = 1
        t += on + rng.randint(30, 60)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps_container, (400, 260))
    nrng = np.random.default_rng(seed)
    for i in range(n_frames):
        img = np.full((260, 400, 3), 30, np.uint8)
        x, y, w, h = LED
        img[y:y + h, x:x + w] = 30 + 200 * led[i]
        for roi, d in zip((SCREEN_A, SCREEN_B), delays_frames):
            past = [led[i - d - k] if i - d - k >= 0 else 0 for k in range(rise_frames)]
            level = float(np.mean(past))
            x, y, w, h = roi
            img[y:y + h, x:x + w] = 40 + 180 * level
        img = np.clip(img.astype(int) + nrng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
        writer.write(img)
    writer.release()


def test_known_delays_recovered(tmp_path, capsys):
    video = tmp_path / 'synthetic.avi'
    # 240 fps capture: 6 frames = 25 ms, 12 frames = 50 ms
    make_video(video, 240, 1600, (6, 12))
    csv_path = tmp_path / 'out.csv'
    rc = al.main([str(video), '--led', '40,40,20,20', '--screen', 'a=200,100,40,30',
                  '--screen', 'b=300,200,40,30', '--csv', str(csv_path)])
    out = capsys.readouterr().out
    assert rc == 0
    rows = [l.split(',') for l in csv_path.read_text().splitlines()[1:]]
    med = {n: float(np.median([float(r[3]) for r in rows if r[0] == n])) for n in ('a', 'b')}
    # the 2-frame linear rise shifts the 50 % crossing by about half a frame
    assert med['a'] == pytest.approx(25 + 2.08, abs=4.2)
    assert med['b'] == pytest.approx(50 + 2.08, abs=4.2)
    assert 'n=' in out


def test_capture_fps_override_for_slow_motion_files(tmp_path, capsys):
    video = tmp_path / 'slowmo.avi'
    make_video(video, 30, 1200, (6, 6))  # recorded at 240, stored as 30 fps
    rc = al.main([str(video), '--capture-fps', '240', '--led', '40,40,20,20', '--screen', 'a=200,100,40,30'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'using --capture-fps 240' in out
    median = float(out.split('median=')[1].split(' ms')[0])
    assert median == pytest.approx(25 + 2.08, abs=1.0)  # not 8x too large


def test_rising_edges_ignores_noise_and_flat_signal():
    flat = np.full(500, 100.0) + np.random.default_rng(0).normal(0, 1, 500)
    assert al.rising_edges(flat)[0] == []
    square = np.tile(np.r_[np.zeros(20), np.full(20, 200.0)], 10)
    edges, _ = al.rising_edges(square + np.random.default_rng(1).normal(0, 3, square.size))
    assert len(edges) == 10


def test_pairing_uses_lag_window_not_next_edge():
    # true lag 6 frames: the edge at 16 belongs to LED 10, nothing belongs to LED 100
    pairs = al.pair_delays([10.0, 100.0], [5.0, 16.0, 400.0], frame_ms=4.0, lag=6, tolerance=2)
    assert [round(d, 1) for *_, d in pairs] == [24.0]


def test_delay_longer_than_blink_period_is_measured_correctly(tmp_path, capsys):
    # reproduces the review case: 500 ms real delay, blinks every ~250-450 ms
    video = tmp_path / 'slow.avi'
    make_video(video, 240, 3000, (120, 120))
    rc = al.main([str(video), '--led', '40,40,20,20', '--screen', 'a=200,100,40,30'])
    out = capsys.readouterr().out
    assert rc == 0
    median = float(out.split('median=')[1].split(' ms')[0])
    assert median == pytest.approx(500 + 2.08, abs=1.0)


def test_unnamed_screens_are_kept_apart(tmp_path, capsys):
    video = tmp_path / 'two.avi'
    make_video(video, 240, 1600, (6, 12))
    rc = al.main([str(video), '--led', '40,40,20,20', '--screen', '200,100,40,30', '--screen', '300,200,40,30'])
    out = capsys.readouterr().out
    assert rc == 0
    s1 = float(out.split('screen1: n=')[1].split('median=')[1].split(' ms')[0])
    s2 = float(out.split('screen2: n=')[1].split('median=')[1].split(' ms')[0])
    assert s1 == pytest.approx(27.1, abs=1.0) and s2 == pytest.approx(52.1, abs=1.0)


def test_duplicate_screen_names_rejected(tmp_path):
    video = tmp_path / 'v.avi'
    make_video(video, 240, 60, (1, 1))
    with pytest.raises(SystemExit):
        al.main([str(video), '--led', '40,40,20,20', '--screen', 'x=200,100,40,30', '--screen', 'x=300,200,40,30'])


def test_periodic_blinking_is_flagged_as_ambiguous():
    period = 40
    led = np.tile(np.r_[np.zeros(period // 2), np.full(period // 2, 200.0)], 30)
    screen = np.roll(led, 50)  # delay longer than a period: cannot be told apart
    lag, peak, runner_up = al.estimate_lag(led, screen, 200)
    assert peak - runner_up < 0.15


def test_region_outside_frame_is_rejected(tmp_path):
    video = tmp_path / 'v.avi'
    make_video(video, 240, 60, (1, 1))
    with pytest.raises(SystemExit, match='outside'):
        al.main([str(video), '--led', '390,250,20,20', '--screen', '200,100,40,30'])
