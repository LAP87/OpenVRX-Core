"""Golden rows and damage controls for nominal IQ-to-Capture scoring."""
import math

import numpy as np
import pytest

import iq_capture_ref as adapter
import iq_demod_ref as iq


def row(field=0, line=20, bad=0, length=1716):
    pixels = [value for value in [16,47,78,109,140,171,202,233] for _ in range(90)]
    words = [('word',field,line,i,(pixels[2*i+1]<<24) | (128<<16) | (pixels[2*i]<<8) | 128)
             for i in range(360)]
    return words+[('marker',field,line,7*31,bad,length)]


def test_code_scale_matches_existing_requantizer():
    values = np.array([-1000,-100,-40,-1,0,1,50,100,200,1000],float)
    expected = np.rint(22+.22*iq.requantise_6bit(values)).astype(np.uint8)
    np.testing.assert_array_equal(adapter.video_codes(values),expected)
    assert expected[0] == 0 and expected[-1] == 63


def test_binary_entry_golden_and_no_overwrite(tmp_path):
    path = tmp_path/'entry.bin'
    adapter.write_entries(path,[('word',0,20,0,0x10801080)])
    assert path.read_bytes() == bytes.fromhex('00001400000000008010801000000000')
    with pytest.raises(FileExistsError):
        adapter.write_entries(path,[])


def test_two_perfect_rows_have_exact_pixels_and_fields():
    result = adapter.score_entries(row()+row(field=1))
    assert result['valid_rows'] == result['complete_rows'] == 2
    assert result['valid_rows_by_field'] == {0:1,1:1}
    assert result['pixels'] == 1440 and result['pixel_rmse'] == 0
    assert result['malformed_rows'] == result['chroma_errors'] == 0


def test_single_pixel_error_is_not_mean_removed():
    entries = row()
    first = entries[0]
    entries[0] = first[:4]+(first[4]^(1<<8),)
    result = adapter.score_entries(entries)
    assert result['squared_error'] == 1
    assert result['pixel_rmse'] == math.sqrt(1/720)


def test_chroma_damage_is_visible_even_when_luma_matches():
    entries = row()
    first = entries[0]
    entries[0] = first[:4]+(first[4]^1,)
    result = adapter.score_entries(entries)
    assert result['pixel_rmse'] == 0 and result['chroma_errors'] == 1


@pytest.mark.parametrize('damage',['missing','reordered'])
def test_bad_word_sequence_is_not_a_complete_row(damage):
    entries = row()
    if damage == 'missing':
        del entries[70]
    else:
        entries[70],entries[71] = entries[71],entries[70]
    result = adapter.score_entries(entries)
    assert result['malformed_rows'] == 1 and result['complete_rows'] == result['pixels'] == 0


@pytest.mark.parametrize('bad,length',[(1,1716),(0,1690)])
def test_pixels_cannot_replace_marker_validity(bad,length):
    result = adapter.score_entries(row(bad=bad,length=length))
    assert result['complete_rows'] == 1 and result['pixel_rmse'] == 0
    assert result['valid_rows'] == 0


def test_unclosed_trailing_words_do_not_count_as_a_row():
    result = adapter.score_entries(row()[:17])
    assert result['trailing_words'] == 17
    assert result['markers'] == result['complete_rows'] == result['pixels'] == 0
    assert result['pixel_rmse'] is None
