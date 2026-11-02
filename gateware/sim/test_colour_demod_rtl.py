"""rtl/cvbs_capture.v with COLOUR=1 (rtl/colour_demod.v) against model/colour_demod_ref.py: the
same 6-bit composite samples at 40 MS/s must give the same mixer entries, bit for bit, now with
the chroma bytes filled (task 65). Also checks the generated LUT includes against the model and
that COLOUR=0 keeps the old 8'h80 bytes, so existing builds are untouched.

Run:  .venv/bin/python -m pytest -q gateware/sim/test_colour_demod_rtl.py
Skips the RTL runs when Icarus Verilog is not installed (as test_fb_display_default.py does);
the LUT/constant checks always run.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import colour_demod_ref as cd  # noqa: E402
import cvbs_capture_ref as cv  # noqa: E402


def iverilog_env():
    env = os.environ.copy()
    bundled = PROJECT / '.tools' / 'iverilog' / 'bin'
    if bundled.exists():
        env['PATH'] = f'{bundled}{os.pathsep}' + env.get('PATH', '')
    return env


def have_iverilog():
    env = iverilog_env()
    return shutil.which('iverilog', path=env.get('PATH')) and shutil.which('vvp', path=env.get('PATH'))


# The RTL has gain tables for WHITE_X8 20 (standard) and 31 (C5VRX) only, so the test levels are
# chosen to land on those: C5VRX's measured 23/31/62 (white-blank 31, blank-sync 8 -> 31) and a
# standard set 8/22/57 (35/14 -> 20). The Vibe draft used 4/22/62 (-> 18), which no RTL table
# serves, so the RTL silently took the 20 table and the comparison could never match.
LV_C5 = (23, 31, 62)
LV_STD = (8, 22, 57)


def wx8(levels):
    return round(8 * (levels[2] - levels[1]) / (levels[1] - levels[0]))


def kdef(levels):
    return "12'h%03X" % (cd.chroma_k(levels[2] - levels[1]) & 0xFFF)


def run(samples, colour=1, comb=True, white_x8=cd.cv.WHITE_X8_STD, chroma_k_def=None, tag='run'):
    """Entries the RTL emits for the samples, decoded like the model's tuples."""
    work = HERE / 'build' / 'colour_demod' / tag
    work.mkdir(parents=True, exist_ok=True)
    env = iverilog_env()
    hexfile = work / 'samples.hex'
    outfile = work / 'entries.txt'
    cv.write_hex(hexfile, samples)
    defines = [f'-DCVBS_COLOUR={colour}', '-DCVBS_COMB=%d' % (1 if comb else 0)]
    if white_x8 != cv.WHITE_X8_STD:
        defines.append(f'-DCVBS_WHITE_X8={white_x8}')
    if chroma_k_def is not None:
        defines.append(f'-DCVBS_CHROMA_K={chroma_k_def}')
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), *defines, '-o', 'sim.vvp',
                    '-s', 'tb_colour_demod', str(HERE / 'tb_colour_demod.v'),
                    str(GW / 'rtl' / 'cvbs_capture.v'), str(GW / 'rtl' / 'colour_demod.v')],
                   cwd=work, env=env, check=True)
    res = subprocess.run(['vvp', '-n', 'sim.vvp', f'+hex={hexfile}', f'+out={outfile}',
                          f'+n={len(samples)}'], cwd=work, env=env, check=True,
                         capture_output=True, text=True)
    assert re.search(r'RESULT samples=\d+ entries=\d+', res.stdout), res.stdout[-500:]
    out = []
    for line in outfile.read_text().split():
        v = int(line, 16)
        field = (v >> 51) & 1
        ln = (v >> 41) & 0x3FF
        if (v >> 52) & 1:
            out.append(('marker', field, ln, (v >> 21) & 0xFFFFF, (v >> 17) & 0xF, (v >> 1) & 0xFFF))
        else:
            out.append(('word', field, ln, (v >> 32) & 0x1FF, v & 0xFFFFFFFF))
    return out


def first_difference(got, exp):
    for i, (g, e) in enumerate(zip(got, exp)):
        if g != e:
            return f'entry {i}: rtl {g}, model {e}'
    if len(got) != len(exp):
        return f'{len(got)} entries from the rtl, {len(exp)} from the model'
    return None


def colour_samples(lines=30, **kw):
    kw.setdefault('levels', LV_C5)
    return cd.synth_colour(cv.bars, cd.colour_bars_chroma, lines=lines, first_line=1, **kw)[0]


def test_lut_includes_match_model():
    """rtl/colour_luts_{cos,sin,inv}.vh are the model's tables (regenerate with
    colour_demod_ref.write_lut_vh)."""
    for name, text in cd.lut_vh().items():
        assert (GW / 'rtl' / name).read_text() == text, name
    assert cd.ROT_C8 == -8 and cd.ROT_S8 == -127            # the ROT constants in colour_demod.v
    assert cd.FSC_INC == 384350718 and cd.LOOP_GAIN == 1694976 and cd.INC_CLAMP == 2000000
    assert cd.chroma_k(40) == -1025 and cd.chroma_k(31) == -1322


def test_model_entry_stream_fills_chroma():
    """expected_colour_entries keeps the capture's own entries and only changes the word's bytes
    [23:16] and [7:0] (Cr/Cb); the Y bytes ([31:24], [15:8]) and all markers are identical to the
    plain capture (the word's own two Y bytes differ only where the comb partner differs between
    the two runs, which it does not: both use comb=True)."""
    s = colour_samples(lines=30)
    ent = cd.expected_colour_entries(s, levels=LV_C5)
    plain = cv.expected_entries(s, white_x8=wx8(LV_C5))
    assert len(ent) == len(plain)
    n_filled = 0
    for a, b in zip(plain, ent):
        if a[0] == 'word':
            assert ((a[4] >> 24) & 0xFF, (a[4] >> 8) & 0xFF) == \
                   ((b[4] >> 24) & 0xFF, (b[4] >> 8) & 0xFF)        # Y1/Y0 unchanged
            assert (a[4] >> 16 & 0xFF) == 0x80 and (a[4] & 0xFF) == 0x80
            if (b[4] >> 16 & 0xFF, b[4] & 0xFF) != (0x80, 0x80):
                n_filled += 1
        else:
            assert a == b                                          # markers identical
    assert n_filled > 1000, n_filled


@pytest.mark.skipif(not have_iverilog(), reason='Icarus Verilog is not installed')
def test_colour_frame_matches_model():
    """A clean colour-bars stretch: every word (Y1/Cr/Y0/Cb) and marker as the model, bit for
    bit (the 2-3 clock pipeline delay does not change the entry order)."""
    for lv, tag in ((LV_C5, 'clean_c5'), (LV_STD, 'clean_std')):
        s = colour_samples(lines=30, levels=lv)
        exp = cd.expected_colour_entries(s, levels=lv)
        got = run(s, colour=1, white_x8=wx8(lv), chroma_k_def=kdef(lv), tag=tag)
        diff = first_difference(got, exp)
        assert diff is None, (tag, diff)
    words = [e for e in got if e[0] == 'word']
    assert any(((e[4] >> 16) & 0xFF) not in (0, 0x80, 255) or (e[4] & 0xFF) not in (0, 0x80, 255)
               for e in words)          # real chroma, not the placeholder


@pytest.mark.skipif(not have_iverilog(), reason='Icarus Verilog is not installed')
def test_noise_frame_matches_model():
    """Noise of one code and a burst phase ramp of 2 deg/line: the same entries as the model
    (exercises the burst loop and the boxcar under non-ideal phase)."""
    s = colour_samples(lines=30, noise=1.0, seed=3, phase_ramp=2.0)
    exp = cd.expected_colour_entries(s, levels=LV_C5)
    got = run(s, colour=1, white_x8=wx8(LV_C5), chroma_k_def=kdef(LV_C5), tag='noise')
    diff = first_difference(got, exp)
    assert diff is None, diff


@pytest.mark.skipif(not have_iverilog(), reason='Icarus Verilog is not installed')
def test_colour_zero_keeps_placeholder_bytes():
    """COLOUR=0 emits exactly the luma-only entries of the model's plain capture (8'h80 chroma
    bytes): existing builds are bit-identical."""
    s = colour_samples(lines=30)
    exp = cv.expected_entries(s, white_x8=wx8(LV_C5))
    got = run(s, colour=0, white_x8=wx8(LV_C5), tag='luma')
    diff = first_difference(got, exp)
    assert diff is None, diff
    assert all((e[4] >> 16 & 0xFF) == 0x80 and (e[4] & 0xFF) == 0x80
               for e in got if e[0] == 'word')


@pytest.mark.skipif(not have_iverilog(), reason='Icarus Verilog is not installed')
def test_comb_off_is_the_negative_control():
    """With the 1H comb off (COMB=0) the RTL matches the model's comb-off entries: luma leaks
    into the chroma bytes (they move with the picture), which is the negative control."""
    s = colour_samples(lines=30)
    exp = cd.expected_colour_entries(s, comb=False, levels=LV_C5)
    got = run(s, colour=1, comb=False, white_x8=wx8(LV_C5), chroma_k_def=kdef(LV_C5), tag='nocombs')
    diff = first_difference(got, exp)
    assert diff is None, diff
    plain = cv.expected_entries(s, comb=False, white_x8=wx8(LV_C5))
    got_luma = run(s, colour=0, comb=False, white_x8=wx8(LV_C5), tag='nocombl')
    assert first_difference(got_luma, plain) is None
    # the comb-off chroma tracks the luma: on the white bar the Cb byte is far from 128
    words = [e for e in got if e[0] == 'word']
    white = [e for e in words if (e[4] >> 24) & 0xFF > 200][:50]
    assert white and any(abs((e[4] & 0xFF) - 128) > 20 for e in white)
