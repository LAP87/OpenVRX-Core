import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import line_mixer as lm  # noqa: E402

H, W, N = 120, 160, 40


def scene(n=N, seed=0):
    """Smooth moving content: low horizontal-difference energy when clean."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W]
    frames = []
    for t in range(n):
        f = 90 + 60 * np.sin((xx + 3 * t) / 25.0) + 40 * np.cos((yy - 2 * t) / 30.0)
        f += 30 * (((xx - 4 * t) % 160) < 20)  # a moving bar with edges
        frames.append(f + rng.normal(0, 1, f.shape))
    return np.stack(frames).astype(np.float32)


def corrupt(frames, frac, seed):
    """Replace random bursts of lines with heavy 'snow' (independent per receiver)."""
    rng = np.random.default_rng(seed)
    out, mask = frames.copy(), np.zeros(frames.shape[:2], bool)
    for f in range(frames.shape[0]):
        y = 0
        while y < H:
            if rng.random() < frac / 8:
                L = rng.integers(3, 12)
                out[f, y:y + L] = rng.uniform(0, 255, (min(L, H - y), W))
                mask[f, y:y + L] = True
                y += L
            y += 1
    return out, mask


def test_mixer_picks_clean_lines_and_beats_both_inputs():
    truth = scene()
    a, ma = corrupt(truth, 0.25, 1)
    b, mb = corrupt(truth, 0.25, 2)
    mixed, choice = lm.mix(a, b)
    only_a_bad = ma & ~mb
    only_b_bad = mb & ~ma
    assert (choice[only_a_bad] == 1).mean() > 0.95
    assert (choice[only_b_bad] == 0).mean() > 0.95
    err = lambda x: float(np.abs(x - truth).mean())
    assert err(mixed) < 0.5 * min(err(a), err(b))


def test_clean_inputs_are_blended_not_flickering():
    truth = scene()
    a = truth + np.random.default_rng(3).normal(0, 1, truth.shape)
    b = truth + np.random.default_rng(4).normal(0, 1, truth.shape)
    _, choice = lm.mix(a.astype(np.float32), b.astype(np.float32))
    assert (choice == 2).mean() > 0.9


def test_frame_offset_and_shift_are_recovered():
    truth = scene(60)
    # brightness events so the time series has structure
    truth[10:13] += 40
    truth[35:37] -= 40
    b = np.roll(truth, 5, axis=0)  # b lags a by 5 frames
    b = np.roll(b, (2, -3), axis=(1, 2))  # and is shifted 2 lines down, 3 px left
    assert lm.estimate_frame_offset(truth[5:], b[5:]) == 5
    dx, dy = lm.estimate_shift(truth[20], np.roll(truth[20], (2, -3), axis=(0, 1)))
    assert dx == pytest.approx(3, abs=0.5) and dy == pytest.approx(-2, abs=0.5)


def test_cli_end_to_end(tmp_path):
    truth = scene()
    a, _ = corrupt(truth, 0.25, 5)
    b, _ = corrupt(truth, 0.25, 6)
    pa, pb = tmp_path / 'a.mkv', tmp_path / 'b.mkv'
    lm.write_video(pa, a, 30)
    lm.write_video(pb, b, 30)
    out, stats = tmp_path / 'm.mkv', tmp_path / 's.csv'
    assert lm.main([str(pa), str(pb), '--out', str(out), '--stats', str(stats)]) == 0
    mixed = lm.read_gray(out)
    assert mixed.shape == truth.shape
    assert float(np.abs(mixed - truth).mean()) < float(np.abs(a - truth).mean())
    assert stats.read_text().startswith('frame,noise_a')


def test_align_is_robust_to_snow():
    truth = scene()
    a, _ = corrupt(truth, 0.25, 7)
    b, _ = corrupt(np.roll(truth, (2, -3), axis=(1, 2)), 0.25, 8)
    _, _, k, (dx, dy) = lm.align(a, b)
    assert k == 0
    assert dx == pytest.approx(3, abs=0.5) and dy == pytest.approx(-2, abs=0.5)
