"""Properties of model/iq_demod_ref.py, the feasibility model for receiver boundary C (task 67): what
the IQ bit depth and the 6-bit output do to a plain FM demodulator's luma SNR and sync detection.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_iq_demod.py
"""
import sys
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GW / 'model'))
import iq_demod_ref as iq  # noqa: E402

LINES = 60


@pytest.mark.parametrize('bits', [4, 7])
def test_snr_rises_with_cn(bits):
    """More carrier over noise never gives a worse picture, for either bit depth."""
    snrs = [iq.run_case(cn, bits, lines=LINES)[0] for cn in (3, 8, 12, 20, 30)]
    assert all(b > a for a, b in zip(snrs, snrs[1:])), snrs


def test_seven_bits_lift_the_ceiling():
    """At 30 dB C/N the 4-bit path sits on its quantisation floor; 7 bits are at least 8 dB above it,
    and the sync edge is found in nearly every line from 20 dB C/N."""
    snr4, _ = iq.run_case(30, 4, lines=LINES)
    snr7, hit7 = iq.run_case(30, 7, lines=LINES)
    _, hit7_20 = iq.run_case(20, 7, lines=LINES)
    assert snr7 - snr4 >= 8.0, (snr4, snr7)
    assert snr4 < 25.0, snr4
    assert hit7 >= 0.98 and hit7_20 >= 0.95, (hit7, hit7_20)


def test_six_bit_output_is_not_the_bottleneck():
    """Quantising the 4-bit path's video to C5VRX's 6-bit output scale costs under 1 dB at 20 dB C/N:
    the loss of the composite path (task 64) is in the IQ, not in the DAC."""
    snr4, _ = iq.run_case(20, 4, lines=LINES)
    snr6, _ = iq.run_case(20, 4, lines=LINES, out6=True)
    assert snr4 - snr6 < 1.0, (snr4, snr6)


def test_negative_control_two_bits():
    """The measure bites: two bits per axis at 30 dB C/N give a picture far below the 4-bit one."""
    snr2, hit2 = iq.run_case(30, 2, lines=LINES)
    snr4, _ = iq.run_case(30, 4, lines=LINES)
    assert snr4 - snr2 >= 6.0, (snr2, snr4)


def test_negative_control_wrong_deviation():
    """A demodulator scaled for the wrong deviation reads the levels wrong: the SNR against the clean
    video collapses even with 7 bits and a strong carrier."""
    clean, starts, info = iq.composite_ire(iq.cv.bars, LINES)
    video = iq.lowpass(clean, 4.2e6)
    z = iq.lowpass(iq.fm_modulate(video, 2.8), 6e6, taps=95)
    z = iq.quantise_iq(z, 7)
    right = iq.lowpass(iq.fm_demodulate(z, 2.8), 4.2e6)
    wrong = iq.lowpass(iq.fm_demodulate(z, 5.6), 4.2e6)
    assert iq.luma_snr_db(right, video, info) - iq.luma_snr_db(wrong, video, info) >= 10.0
