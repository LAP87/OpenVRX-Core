import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import bt656  # noqa: E402

VALID = {bt656.xy(f, v, h): (f, v, h) for f in (0, 1) for v in (0, 1) for h in (0, 1)}


def test_xy_codes_match_bt656_table():
    # standard values: SAV/EAV in active and blanking, both fields
    assert bt656.xy(0, 0, 0) == 0x80 and bt656.xy(0, 0, 1) == 0x9D
    assert bt656.xy(0, 1, 0) == 0xAB and bt656.xy(0, 1, 1) == 0xB6
    assert bt656.xy(1, 0, 0) == 0xC7 and bt656.xy(1, 0, 1) == 0xDA
    assert bt656.xy(1, 1, 0) == 0xEC and bt656.xy(1, 1, 1) == 0xF1


def test_single_bit_errors_are_corrected_double_bit_errors_detected():
    for code, fvh in VALID.items():
        assert bt656.XY_TABLE[code] == (*fvh, 'ok')
        for i in range(8):
            assert bt656.XY_TABLE[code ^ (1 << i)] == (*fvh, 'corrected')
        for i in range(8):
            for j in range(i + 1, 8):
                assert bt656.XY_TABLE[code ^ (1 << i) ^ (1 << j)][3] == 'bad'


@pytest.mark.parametrize('std,active_lines,length,f0_lines', [('ntsc', 487, 1716, 244), ('pal', 576, 1728, 288)])
def test_full_frame_round_trip(std, active_lines, length, f0_lines):
    luma = lambda line, x: 16 + (line * 7 + x * 3) % 200
    data = bt656.frame_bytes(std, luma) + bt656.line_bytes(std, 1)  # trailing EAV closes the last line
    recs = bt656.Receiver().feed(data)
    assert len(recs) == active_lines
    assert all(r.active_count == bt656.ACTIVE_BYTES for r in recs)
    assert all(r.length == length for r in recs)
    assert sum(r.field == 0 for r in recs) == f0_lines
    assert [r.line_in_field for r in recs if r.field == 0] == list(range(f0_lines))
    # first active line of field 0 is line 20 (NTSC) / 23 (PAL)
    first = 20 if std == 'ntsc' else 23
    assert recs[0].luma == [luma(first, x) for x in range(720)]
    assert all(r.xy_corrected == 0 and r.xy_bad == 0 for r in recs)


def test_corrupted_timing_code_is_corrected_and_counted():
    data = bytearray(bt656.line_bytes('pal', 100) + bt656.line_bytes('pal', 101) + bt656.line_bytes('pal', 102))
    sav = data.index(bytes([0xFF, 0, 0]), 4) + 3  # SAV of line 100
    data[sav] ^= 0x04
    recs = bt656.Receiver().feed(bytes(data))
    assert [r.xy_corrected for r in recs] == [1, 0]
    assert all(r.active_count == 1440 for r in recs)


def test_truncated_line_is_visible_in_length_and_count():
    l1, l2, l3 = (bytearray(bt656.line_bytes('ntsc', n)) for n in (100, 101, 102))
    del l2[-300:-200]  # drop 100 bytes of active video
    recs = bt656.Receiver().feed(bytes(l1 + l2 + l3))
    assert [r.active_count for r in recs] == [1440, 1340]
    assert [r.length for r in recs] == [1716, 1616]


def test_hf_energy_rises_with_noise():
    rng = random.Random(0)
    clean = bytes(b for x in range(720) for b in (0x80, 60 + x // 8))
    noisy = bytes(b for x in range(720) for b in (0x80, max(1, min(254, 60 + x // 8 + rng.randint(-40, 40)))))
    data = bt656.line_bytes('pal', 100, clean) + bt656.line_bytes('pal', 101, noisy) + bt656.line_bytes('pal', 102)
    a, b = bt656.Receiver().feed(data)
    assert b.hf_energy > 10 * a.hf_energy


def test_reserved_codes_rejected_in_video():
    with pytest.raises(AssertionError):
        bt656.line_bytes('pal', 100, bytes([0x80, 0xFF] * 720))


def test_write_hex(tmp_path):
    p = tmp_path / 'v.hex'
    bt656.write_hex(p, b'\x00\xff\x10')
    assert p.read_text() == '00\nff\n10\n'


def _field_lines(n, f=0, break_sav=None, break_eav=None):
    """n active lines of one field (after one blanking line); optionally break a code."""
    bad = next(b for b, v in bt656.XY_TABLE.items() if v[3] == 'bad' and b not in (0, 255))
    out = bytearray()
    for i in range(-1, n):
        v = 1 if i < 0 else 0
        eav, sav = bt656.xy(f, v, 1), bt656.xy(f, v, 0)
        if i == break_sav:
            sav = bad
        if i == break_eav:
            eav = bad
        act = bt656.blanking(1440) if v else bytes(b for x in range(720) for b in (0x80, 16 + (i * 7 + x) % 200))
        out += bytes([0xFF, 0, 0, eav]) + bt656.blanking(1716 - 1448) + bytes([0xFF, 0, 0, sav]) + act
    out += bytes([0xFF, 0, 0, bt656.xy(f, 1, 1)]) + bt656.blanking(1716 - 1448)
    return bytes(out)


def test_lost_sav_keeps_line_numbers():
    recs = bt656.Receiver().feed(_field_lines(6, break_sav=2))
    assert [r.line_in_field for r in recs] == [0, 1, 3, 4, 5]
    assert recs[2].luma[0] == 16 + 3 * 7          # line 3 really is image line 3


def test_lost_eav_keeps_line_numbers():
    # the EAV that would end line 1 (it starts line 2) is broken: line 1 is not recorded
    recs = bt656.Receiver().feed(_field_lines(6, break_eav=2))
    assert [r.line_in_field for r in recs] == [0, 2, 3, 4, 5]
    assert recs[1].xy_bad == 1
