"""The integer mixer rule (line_mixer_ref) must make the same choices as the
float prototype mixer/line_mixer.py for the same per-line noise values."""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / 'mixer'))
import line_mixer  # noqa: E402  (the float prototype)
import line_mixer_ref as ref  # noqa: E402


def frames_with_noise(noise):
    """Frames whose line_noise() is exactly `noise` (width 2: [0, e])."""
    f = np.zeros(noise.shape + (2,), np.float32)
    f[..., 1] = noise
    return f


def test_integer_rule_matches_prototype():
    rng = np.random.default_rng(7)
    # mix of similar and very different values so blend, stay and switch all occur
    base = rng.integers(0, 20000, size=(30, 40))
    na = base + rng.integers(-3000, 3000, size=base.shape)
    nb = base + rng.integers(-3000, 3000, size=base.shape)
    na[5:8], nb[12:14] = na[5:8] * 4, nb[12:14] * 4          # bursts of snow
    na, nb = np.clip(na, 0, None), np.clip(nb, 0, None)
    na[0, :3] = nb[0, :3] = 0                                # both zero -> blend
    _, choice = line_mixer.mix(frames_with_noise(na), frames_with_noise(nb),
                               blend_margin=38 / 256, switch_margin=0.25)
    cur, got = 0, np.empty_like(choice)
    for f in range(na.shape[0]):
        for y in range(na.shape[1]):
            use, cur = ref.decide_pair(int(na[f, y]), int(nb[f, y]), cur)
            got[f, y] = {ref.USE_A: 0, ref.USE_B: 1, ref.USE_BLEND: 2}[use]
    assert (got == choice).all(), np.argwhere(got != choice)[:5]
    assert {0, 1, 2} <= set(np.unique(got).tolist())


def test_bad_line_loses():
    assert ref.decide_pair(10, 99999, 1, bad_a=False, bad_b=True) == (ref.USE_A, 0)
    assert ref.decide_pair(10, 99999, 0, bad_a=True, bad_b=False) == (ref.USE_B, 1)
    assert ref.decide_pair(10, 99999, 1, bad_a=True, bad_b=True) == (ref.USE_B, 1)
