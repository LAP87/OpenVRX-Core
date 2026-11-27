"""Model-only tests for Core #27: actual packed bytes and independent colour truth.

The initial quality target and the high-scale clipping failure remain explicit.
Passing implementation regressions does not claim all source scales meet it.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'model'))
import colour_demod_ref as cd
import cvbs_capture_ref as cv


@pytest.fixture(scope='module')
def clean_cases():
    return {lv: cd.run_frame(levels=lv, lines=360, noise=0, white_x8=31)
            for lv in [(23, 31, 62), (13, 25, 50)]}


def test_clean_bar_coverage_and_full_last_line(clean_cases):
    for lv, r in clean_cases.items():
        assert r['words'] >= 28080 and r['demod_samples'] == 2*r['words']
        assert r['first_lock_sample'] is not None and all(b['count'] >= 100 for b in r['bars'])
        # The last word's chroma comes from that line, not the previous line's final blue bar.
        assert abs(r['cb'][-1]-128) <= 10 and abs(r['cr'][-1]-128) <= 10
        assert any(v < 80 for v in r['cb']) and any(v > 200 for v in r['cb'])


def test_clipped_scale_does_not_get_a_false_quality_pass(clean_cases):
    high, low = clean_cases[(23, 31, 62)], clean_cases[(13, 25, 50)]
    assert high['clipping']['active_clipped'] > 0
    assert high['max_mean_vector_error'] > 16 and high['clean_target_pass'] is False
    assert low['clipping']['active_clipped'] == 0
    assert low['max_mean_vector_error'] <= 16 and low['max_mean_hue_error_deg'] <= 10
    assert low['clean_target_pass'] is True
    # Decoded hue is measured from the colour bytes, not borrowed from a loop-control register.
    assert low['hue_rms_deg'] != low['burst_phase_rms_deg']


def test_colour_preserves_original_luma_and_every_marker():
    samples, _ = cd.synth_colour(cd.colour_bars_luma, cd.colour_bars_chroma,
                                lines=360, levels=(13, 25, 50))
    original = cv.Capture(white_x8=31); original.run(samples)
    coloured = cd.expected_colour_entries(samples, levels=(13, 25, 50), white_x8=31)
    assert len(coloured) == len(original.entries) and len(coloured) > 100000
    for a, b in zip(original.entries, coloured):
        if a[0] == 'marker':
            assert a == b
        else:
            assert a[:4] == b[:4]
            assert (a[4] & 0xFF00FF00) == (b[4] & 0xFF00FF00)


def test_wrong_gain_and_comb_off_are_semantic_negatives(clean_cases):
    lv = (13, 25, 50)
    good = clean_cases[lv]
    wrong = cd.run_frame(levels=lv, lines=360, white_x8=31,
                         chroma_k_override=-cd.chroma_k(lv[2]-lv[1]))
    off = cd.run_frame(levels=lv, lines=360, white_x8=31, comb=False)
    assert wrong['words'] == good['words'] and off['words'] == good['words']
    assert wrong['max_mean_vector_error'] > 100 and not wrong['clean_target_pass']
    assert off['chroma_rms'] > good['chroma_rms']+10 and not off['clean_target_pass']


def test_missing_burst_cannot_correct_an_unknown_source_phase():
    lv = (13, 25, 50)
    good = cd.run_frame(levels=lv, lines=360, white_x8=31, phase_offset=30)
    free = cd.run_frame(levels=lv, lines=360, white_x8=31, phase_offset=30, with_burst=False)
    assert good['words'] > 0 and free['words'] > 0
    assert free['burst_lines'] == 0 and good['burst_lines'] > 20
    assert free['max_mean_hue_error_deg'] > 20
    assert good['max_mean_hue_error_deg'] < 10


def test_burst_amplitude_uses_sync_depth_and_gain_is_an_existing_table():
    for lv, want in [((23, 31, 62), 2.0), ((13, 25, 50), 3.0)]:
        stats = {}
        cd.synth_colour(cd.colour_bars_luma, cd.colour_bars_chroma, lines=2, levels=lv, stats=stats)
        assert stats['burst_amp'] == want and cd.gain_for_levels(lv) == 31
    with pytest.raises(ValueError, match='20 and 31'):
        cd.expected_colour_entries([31]*100, white_x8=18)


def test_empty_picture_has_no_numeric_quality_score():
    r = cd.run_frame(lines=20, levels=(23, 31, 62), white_x8=31)
    assert not r['words'] and r['hue_rms_deg'] is None and r['chroma_rms'] is None
    assert r['clean_target_pass'] is False
