"""Findings of the second adversarial review (hub docs/reviews/2026-10-14/ADVERSARIAL_REVIEW_2.md),
kept as tests that state what should hold. All three are fixed on this branch, so the strict xfail
markers are removed and the tests pass:

  RS-2  Core #21  the RSSI warning needs a margin between the receivers (MARGIN_PCT, model/rssi_ref.py)
  SC-1  Core #22  SCAN keeps the starting channel on a tie (model/chan_scan_ref.py)
  HD-1  Core #23  RGB_FULL = 0 scales the pixels to 16..235, as its InfoFrame says (rtl/tmds_link.v)

Fixed in the review: RS-1 (sim/test_mixer.py::test_weak_receiver_takes_over_from_a_broken_one) and
FL-1 (sim/test_flash_store.py::test_interrupted_erase_loads_only_written_records). VI-1 (Core #24),
the formal gap for VINTERP = 1, is closed by formal/linebuf_vi_props.v and the B record of
sim/margin_checks.vh, with no test here: nothing failed.
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


def test_hdmi_limited_flag_means_limited_pixels():
    """tmds_link.v with RGB_FULL = 0 says "limited range" in every AVI InfoFrame; the pixels it then
    sends must lie in 16..235. sim/tb_hdmi.v feeds a full-range pattern."""
    import test_hdmi
    rows = test_hdmi.run('tb_review_hdmi_limited', RGB_FULL=0)
    video, islands, faults = test_hdmi.decode_hdmi(rows)
    assert not faults and islands and len(video) > 1000
    outside = [p for _, p in video if any(not 16 <= (p >> s & 255) <= 235 for s in (0, 8, 16))]
    assert not outside, f'{len(outside)} of {len(video)} pixels outside 16..235'
