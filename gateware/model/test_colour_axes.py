"""Independent numerical truth for the model-only colour experiment, Core #27.

BT.601-7 equations (1), (4), (5), not the decoder's palette or ROT/K derivation:
https://www.itu.int/dms_pubrec/itu-r/rec/bt/r-rec-bt.601-7-201103-i!!pdf-e.pdf
No third-party code is used.
"""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import colour_demod_ref as cd

RGB_BARS = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0),
            (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)]


def truth(rgb):
    r, g, b = rgb
    y = .299*r + .587*g + .114*b
    return round(16+219*y), round(128+224*(b-y)/1.772), round(128+224*(r-y)/1.402)


def test_luma_and_chroma_are_the_same_bt601_bars():
    for bar, rgb in enumerate(RGB_BARS):
        y, cb, cr = truth(rgb)
        x = bar*90+45
        assert cd.colour_bars_luma(30, x) == y
        assert cd.colour_bars_chroma(30, x) == (cb, cr)


@pytest.mark.parametrize('white_blank', [31, 25])
@pytest.mark.parametrize('delay', [2542, 2543])
def test_inverse_axes_against_numeric_sine_correlation(white_blank, delay):
    """Generate the two line waveforms, correlate numerically, and decode their sums.
    ROT/K is not used to generate I/Q truth. Both actual integer line delays are tested."""
    w = 2*math.pi*3579545/40000000
    for rgb in RGB_BARS:
        _, cb, cr = truth(rgb)
        u, v = cb-128, cr-128
        amplitude = .35*white_blank*math.hypot(u/111, v/111)
        phase = math.atan2(v, u)+math.pi
        isum = qsum = 0.0
        for n in range(8192):
            d = amplitude*(math.sin(w*n+phase)-math.sin(w*(n-delay)+phase))
            isum += d*math.cos(w*n)*127/128
            qsum += d*math.sin(w*n)*127/128
        dem = cd.ColourDemod(chroma_k=cd.chroma_k(white_blank))
        dem.line_start(0, True, 23, 31)
        dem.line_start(delay, True, 23, 31)
        got = dem.inverse_chroma(round(isum/8192*cd.CHROMA_TAPS),
                                 round(qsum/8192*cd.CHROMA_TAPS))
        assert abs(got[0]-cb) <= 2 and abs(got[1]-cr) <= 2, (rgb, got, (cb, cr))


@pytest.mark.parametrize('cb', [16, 54, 90, 128, 166, 240])
def test_chroma_replacement_clears_the_old_neutral_bit(cb):
    old = (235<<24)|(128<<16)|(16<<8)|128
    got = cd.replace_chroma(old, cb, 146)
    assert got == (235<<24)|(146<<16)|(16<<8)|cb
    if cb < 128:
        broken = (old & 0xFF00FFFF)|(146<<16)|cb
        assert broken != got       # original packing failure is a real negative control


def test_both_chroma_bytes_come_from_the_same_word_tick():
    pixels = [(16, 90, 240), (47, 16, 146)]
    assert cd.pack_words(pixels) == [(47<<24)|(146<<16)|(16<<8)|16]
