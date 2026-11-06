"""Quantised PLL checks against geometry and unwrapped real-valued equations."""
import math

import numpy as np
import pytest

from fm_pll_ref import FMPLL, TURN, HALF, MASK, phase_table, wrap_error
import iq_demod_ref as iq


def test_quadrants_and_wrap():
    table = phase_table(4)
    assert [table[p] for p in [(1, 0), (0, 1), (-1, 0), (0, -1)]] == [0, TURN//4, HALF, -TURN//4]
    assert wrap_error(TURN+17) == 17
    assert wrap_error(HALF) == -HALF
    assert wrap_error(-HALF-1) == HALF-1


def test_zero_vector_coasts_with_integer_state():
    pll = FMPLL(4)
    pll.frequency = 12345
    for _ in range(100):
        previous = pll.phase
        assert pll.step(0, 0) == 12345
        assert pll.phase == (previous+12345) & MASK
        assert pll.last_weight_q8 == 0
        assert all(type(v) is int for v in [pll.phase, pll.frequency, pll.power_q8])


def rounding_bound():
    """Absolute impulse sum of the three rounding disturbances, including tail."""
    kp, ki = 3/8, 1/32
    alpha = kp+ki
    A = np.array([[1-alpha, 1], [-ki, 1]])
    C = np.array([-alpha, 1])
    B = np.array([[alpha, 1, 1], [ki, 1, 0]])
    gains = np.array([alpha, 1, 1])
    state = B.copy()
    for _ in range(256):
        gains += np.abs(C@state)
        state = A@state
    trace, det = 2-alpha, 1-kp
    r = math.sqrt(trace*trace-4*det)
    l1, l2 = (trace+r)/2, (trace-r)/2
    tail = (np.abs(C@(A-l2*np.eye(2))@B)*l1**256/(1-l1)
            + np.abs(C@(A-l1*np.eye(2))@B)*l2**256/(1-l2))/r
    assert np.max(tail) < 1e-8
    return float((gains+tail)@np.array([.5, 1, 1]))


@pytest.mark.parametrize('direction', [-1, 1])
def test_ramp_mean_frequency_and_derived_roundoff_bound(direction):
    increment = direction*TURN//128
    pll = FMPLL(8, gated=False)
    phase = frequency = 0.0
    outputs, rounding_errors = [], []
    for n in range(1024):
        angle = n*increment*2*math.pi/TURN
        i, q = round(100*math.cos(angle)), round(100*math.sin(angle))
        measured = math.atan2(q, i)*TURN/(2*math.pi)
        measured += round((n*increment-measured)/TURN)*TURN
        error = measured-phase
        frequency += error/32
        reference = frequency+3*error/8
        phase += reference
        actual = pll.step(i, q)
        outputs.append(actual)
        rounding_errors.append(abs(actual-reference))
    # Eight complete periods after settling: frequency bias, not sample ripple.
    assert abs(sum(outputs[-512:])/512-increment) <= 1
    assert max(rounding_errors[-512:]) < rounding_bound() < 7


def test_amplitude_gate_and_cap():
    pll = FMPLL(4)
    for _ in range(1024):
        pll.step(6, 0)
    pll.step(1, 0)
    assert 0 < pll.last_weight_q8 < 256//16
    pll.step(7, 7)
    assert pll.last_weight_q8 == 512


def test_wrong_sign_loses_video_quality_and_sync():
    clean, starts, info = iq.composite_ire(iq.cv.bars, 60)
    video = iq.lowpass(clean, 4.2e6)
    z = iq.lowpass(iq.fm_modulate(video, 2.8), 6e6, taps=95)
    z = iq.lowpass(iq.add_noise(z, 12, 12e6, np.random.default_rng(1)), 6e6, taps=95)
    z = iq.quantise_iq(z, 4)
    right = iq.lowpass(iq.fm_demodulate_pll(z, 4, 2.8), 4.2e6)
    wrong = iq.lowpass(iq.fm_demodulate_pll(z, 4, 2.8, loop_sign=-1), 4.2e6)
    # Wrong feedback must damage the original picture metrics, not just state.
    assert iq.luma_snr_db(right, video, info)-iq.luma_snr_db(wrong, video, info) > 6
    assert iq.sync_hit_rate(wrong, starts) < iq.sync_hit_rate(right, starts)
