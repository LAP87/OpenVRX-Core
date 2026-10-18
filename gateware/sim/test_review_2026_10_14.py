"""Open findings of the second adversarial review (hub docs/reviews/2026-10-14/ADVERSARIAL_REVIEW_2.md),
as strict xfail tests: each states what should hold and fails today. A fix makes its test pass,
which a strict xfail reports as a failure, so the marker has to be removed with the fix.

  RS-2  Core #21  the RSSI warning has no margin between the two receivers
  SC-1  Core #22  SCAN: on a tie of clean channels the earlier table entry wins (fixed: the start keeps a tie)
  HD-1  Core #23  HDMI: RGB_FULL = 0 changes the InfoFrame's flag, not the pixels

Fixed in the review: RS-1 (sim/test_mixer.py::test_weak_receiver_takes_over_from_a_broken_one) and
FL-1 (sim/test_flash_store.py::test_interrupted_erase_loads_only_written_records). VI-1 (Core #24)
is a gap in the formal proof, with nothing that fails.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
sys.path.insert(0, str(GW / 'model'))
sys.path.insert(0, str(HERE))
import chan_scan_ref  # noqa: E402
import rssi_ref  # noqa: E402


@pytest.mark.xfail(strict=True, reason='Core #21 (RS-2): no margin between the receivers')
def test_rssi_warning_needs_a_margin():
    """Both receivers calibrated over the same range; A reads 19 %, B 21 %. Two points near the
    floor say nothing about which picture is better: A must not warn (today it warns from the
    third reading on, and the mixer then takes B in every pair)."""
    m = rssi_ref.Rssi()
    m.load(0, 1000, 0, 1000)
    warns = [m.round((190, 210))['warn'] for _ in range(10)]
    assert all(w == (0, 0) for w in warns), warns


def test_scan_keeps_the_starting_channel_on_a_tie():
    """Started from F4 (index 27): F4 and A1 (index 0) both lock with noise 0. The scan should keep
    F4, the channel the pilot was on; today it keeps A1."""
    obs = [(False, 0, False, 0)] * 48
    obs[27] = obs[0] = (True, 0, True, 0)
    assert chan_scan_ref.scan(obs, 27) == (27, True)


@pytest.mark.xfail(strict=True, reason='Core #23 (HD-1): RGB_FULL = 0 changes only the flag')
def test_hdmi_limited_flag_means_limited_pixels():
    """tmds_link.v with RGB_FULL = 0 says "limited range" in every AVI InfoFrame; the pixels it then
    sends must lie in 16..235. sim/tb_hdmi.v feeds a full-range pattern."""
    import test_hdmi
    rows = test_hdmi.run('tb_review_hdmi_limited', RGB_FULL=0)
    video, islands, faults = test_hdmi.decode_hdmi(rows)
    assert not faults and islands and len(video) > 1000
    outside = [p for _, p in video if any(not 16 <= (p >> s & 255) <= 235 for s in (0, 8, 16))]
    assert not outside, f'{len(outside)} of {len(video)} pixels outside 16..235'
