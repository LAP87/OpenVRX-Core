"""rtl/tmds_link.v: DVI and HDMI (AVI InfoFrame) symbol streams, decoded in Python.

The decoder follows HDMI 1.4 independently of the RTL: symbols are classified by table (control,
TERC4, guard bands, else video), periods are recognised from their preambles, video symbols are
TMDS-decoded (test_video.TmdsRef / tmds_decode), packet bits are gathered from the TERC4 nibbles,
and the BCH parity is checked as a reflected CRC-8 with G(x) = x^8 + x^7 + x^6 + 1 computed by
polynomial division on bit-reversed data (the RTL uses a shift register). Checked per frame: the
video is the input, delayed; each active line has the 8-clock video preamble and 2-clock guard
band; exactly one data island follows each vsync, with header 82h 02h 0Dh, valid parity, a zero
checksum, RGB, 16:9, full range and the VIC of the timing (4, or 19 while hz50 was high).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(HERE))
from test_video import CTRL, TmdsRef, tmds_decode  # noqa: E402

TERC4 = [0b1010011100, 0b1001100011, 0b1011100100, 0b1011100010, 0b0101110001, 0b0100011110,
         0b0110001110, 0b0100111100, 0b1011001100, 0b0100111001, 0b0110011100, 0b1011000110,
         0b1010001110, 0b1001110001, 0b0101100011, 0b1011000011]          # HDMI 1.4 table 5-18
TERC4_INV = {c: d for d, c in enumerate(TERC4)}
CTRL_INV = {c: d for d, c in CTRL.items()}
GB_V02, GB_V1, GB_I = 0b1011001100, 0b0100110011, 0b0100110011
DELAY = 11                                      # HDMI: 10 clocks of lead-in plus the encoder's register
SRC = (GW / 'rtl' / 'tmds_link.v').read_text()


def run(name, alter=None, **params):
    work = HERE / 'build' / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    src = SRC
    for old, new in (alter or []):
        assert src.count(old) == 1, old
        src = src.replace(old, new)
    (work / 'tmds_link.v').write_text(src)
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_hdmi', *[f'-Ptb_hdmi.{k}={v}' for k, v in params.items()],
                    str(work / 'tmds_link.v'), str(GW / 'rtl' / 'tmds_encoder.v'), str(HERE / 'tb_hdmi.v')],
                   cwd=work, env=env, check=True)
    subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True)
    rows = []
    for ln in (work / 'sym.txt').read_text().splitlines():
        de, hs, vs, hz, pat, s0, s1, s2 = ln.split()
        rows.append((int(de), int(hs), int(vs), int(hz), int(pat, 16), int(s0), int(s1), int(s2)))
    return rows


def crc8_reflected(bits):
    """BCH parity of the bits (bit 0 sent first): a CRC with G(x) = x^8 + x^7 + x^6 + 1 on the
    reversed bit order, by polynomial long division; returns the parity byte as sent (bit 0 first)."""
    g = 0b111000001
    n = len(bits)
    poly = 0
    for b in bits:                              # the first bit sent is the highest power
        poly = (poly << 1) | b
    poly <<= 8
    for i in range(n + 7, 7, -1):
        if poly >> i & 1:
            poly ^= g << (i - 8)
    rem = poly & 0xFF                           # remainder, x^7 .. x^0
    return int(f'{rem:08b}'[::-1], 2)           # x^7 is sent first: reversed into bit 0 first


def classify(s0, s1, s2):
    return (CTRL_INV.get(s0), CTRL_INV.get(s1), CTRL_INV.get(s2))


def decode_hdmi(rows):
    """Walk the symbol stream. Returns (video pixels in order, islands, faults)."""
    faults, video, islands = [], [], []
    syms = [(r[5], r[6], r[7]) for r in rows]
    i, n = 0, len(syms)
    while i < n:
        s0, s1, s2 = syms[i]
        c = classify(s0, s1, s2)
        if c[1] == 1 and c[2] == 0 and None not in c:          # video preamble
            j = i
            while j < n and classify(*syms[j])[1:] == (1, 0) and None not in classify(*syms[j]):
                j += 1
            if j - i != 8:
                faults.append(f'video preamble of {j - i} clocks at {i}')
            if syms[j:j + 2] != [(GB_V02, GB_V1, GB_V02)] * 2:
                faults.append(f'no video guard band at {j}: {syms[j:j + 2]}')
            k = j + 2
            while k < n and None in classify(*syms[k]) and syms[k] not in [(GB_V02, GB_V1, GB_V02)]:
                b, g, r = (tmds_decode(syms[k][ch]) for ch in range(3))
                video.append((k, r << 16 | g << 8 | b))
                k += 1
            i = k
        elif c[1] == 1 and c[2] == 1 and None not in c:        # data island preamble
            j = i
            while j < n and classify(*syms[j])[1:] == (1, 1) and None not in classify(*syms[j]):
                j += 1
            if j - i != 8:
                faults.append(f'island preamble of {j - i} clocks at {i}')
            isl = dict(at=j, faults=[])
            gb = syms[j:j + 2], syms[j + 34:j + 36]
            for part in gb:
                for s0g, s1g, s2g in part:
                    if (s1g, s2g) != (GB_I, GB_I) or TERC4_INV.get(s0g, -1) >> 2 != 3:
                        isl['faults'].append(f'bad island guard band at {j}')
            hdr, sub = [], [[] for _ in range(4)]
            for p in range(32):
                d = [TERC4_INV.get(syms[j + 2 + p][ch]) for ch in range(3)]
                if None in d:
                    isl['faults'].append(f'not TERC4 at packet clock {p}')
                    break
                if (d[0] >> 3 & 1) != (p != 0):
                    isl['faults'].append(f'bit 3 of channel 0 is {d[0] >> 3 & 1} at packet clock {p}')
                hdr.append(d[0] >> 2 & 1)
                for k in range(4):
                    sub[k] += [d[1] >> k & 1, d[2] >> k & 1]
            isl.update(hdr=hdr, sub=sub)
            islands.append(isl)
            i = j + 36
        else:
            i += 1
    return video, islands, faults


def bits_to_bytes(bits):
    return [sum(bits[8 * i + k] << k for k in range(8)) for i in range(len(bits) // 8)]


def check_island(isl, want_vic, full=True):
    """Faults of one data island's AVI InfoFrame."""
    f = list(isl['faults'])
    if f:
        return f
    hdr, sub = isl['hdr'], isl['sub']
    if crc8_reflected(hdr[:24]) != bits_to_bytes(hdr[24:32])[0]:
        f.append('header parity')
    for k in range(4):
        if crc8_reflected(sub[k][:56]) != bits_to_bytes(sub[k][56:64])[0]:
            f.append(f'subpacket {k} parity')
    hb = bits_to_bytes(hdr[:24])
    pb = [b for k in range(4) for b in bits_to_bytes(sub[k][:56])]
    if hb != [0x82, 0x02, 0x0D]:
        f.append(f'header {hb}')
    if (sum(hb) + sum(pb[:14])) % 256 != 0:
        f.append(f'checksum: sum {(sum(hb) + sum(pb[:14])) % 256}')
    if pb[1] >> 5 & 3 != 0:
        f.append('not RGB')
    if pb[2] >> 4 & 3 != 2:
        f.append('not 16:9')
    if pb[3] >> 2 & 3 != (2 if full else 1):
        f.append(f'quantization range {pb[3] >> 2 & 3}')
    if pb[4] & 0x7F != want_vic:
        f.append(f'VIC {pb[4] & 0x7F}, timing wants {want_vic}')
    if pb[5] & 0xF:
        f.append('pixel repetition')
    return f


def lim(c):
    """The limited-range copy of a component (tmds_link.v): (c * 219 + 128) / 255 + 16, rounded."""
    return ((c * 219 + 128) * 257 >> 16) + 16


def check_hdmi(rows, full=True):
    """All faults of an HDMI stream against its inputs."""
    video, islands, faults = decode_hdmi(rows)
    scale = (lambda p: p) if full else (lambda p: sum(lim(p >> s & 255) << s for s in (0, 8, 16)))
    want_video = [(i + DELAY, r[4]) for i, r in enumerate(rows) if r[0]]
    want_video = [(i, scale(p)) for i, p in want_video if i < len(rows)]
    if [p for _, p in video] != [p for _, p in want_video][:len(video)] or len(video) < len(want_video) - 1:
        faults.append(f'video: {len(video)} pixels decoded, {len(want_video)} sent, first difference at '
                      f'{next((k for k, (a, b) in enumerate(zip(video, want_video)) if a[1] != b[1]), None)}')
    if [i for i, _ in video] != [i for i, _ in want_video][:len(video)]:
        faults.append('video not delayed by 11 clocks')
    vs_rises = [i for i in range(1, len(rows)) if rows[i][2] and not rows[i - 1][2]]
    if len(islands) != len([v for v in vs_rises if v + DELAY + 45 < len(rows)]):
        faults.append(f'{len(islands)} data islands for {len(vs_rises)} vsync pulses')
    for isl, v in zip(islands, vs_rises):
        faults += check_island(isl, 19 if rows[v][3] else 4, full)
    # control symbols outside the periods: channel 0 carries the delayed sync
    for i in range(DELAY, len(rows)):
        c = CTRL_INV.get(rows[i][5])
        if c is not None and c != (rows[i - DELAY][2] << 1 | rows[i - DELAY][1]):
            faults.append(f'sync on channel 0 at {i}')
            break
    return faults, video, islands


def test_hdmi_stream_decodes():
    rows = run('tb_hdmi')
    faults, video, islands = check_hdmi(rows)
    assert not faults, faults[:5]
    assert len(islands) >= 3 and len(video) >= 3 * 400
    vics = {check_island(isl, 4) == [] for isl in islands}
    assert vics == {True, False}, 'both VIC 4 and VIC 19 frames were sent'


def test_hdmi_limited_range_flag():
    """RGB_FULL = 0: every pixel is scaled to 16..235, so the stream says what the InfoFrame's
    limited-range flag says (a sink that ignores the flag reads it right; 720p's default is
    limited)."""
    rows = run('tb_hdmi_limited', RGB_FULL=0)
    faults, video, _ = check_hdmi(rows, full=False)
    assert not faults, faults[:5]
    assert all(16 <= p >> s & 255 <= 235 for _, p in video for s in (0, 8, 16))


def test_dvi_is_unchanged():
    """HDMI = 0: plain DVI, the symbols of tmds_encoder.v for the inputs one clock earlier; no
    guard band, no TERC4 symbol outside video."""
    rows = run('tb_hdmi_dvi', HDMI=0)
    ref = [TmdsRef(), TmdsRef(), TmdsRef()]
    for i in range(1, len(rows)):
        de, hs, vs, _, pat, *_ = rows[i - 1]
        want = (ref[0].encode(de, pat & 255, vs << 1 | hs), ref[1].encode(de, pat >> 8 & 255, 0),
                ref[2].encode(de, pat >> 16, 0))
        assert rows[i][5:8] == want, (i, rows[i][5:8], want)


@pytest.mark.parametrize('fault, alter, expect', [
    ('wrong_vic', [("hz50_l ? 8'd19 : 8'd4", "hz50_l ? 8'd19 : 8'd5")], 'VIC 5'),
    ('wrong_checksum', [("8'h00 - (8'h82", "8'h01 - (8'h82")], 'checksum'),
    ('wrong_parity', [("? 8'h83 : 8'h00", "? 8'h87 : 8'h00")], 'parity'),
    ('no_guard_band', [("wire      v_gb  = lead == 4'd1 || lead == 4'd2;", "wire      v_gb  = 1'b0;")], 'guard band'),
])
def test_hdmi_check_is_tested(fault, alter, expect):
    """Negative controls: a wrong VIC, checksum or parity polynomial, and no video guard band,
    each in a copy of tmds_link.v, must be found by the decoder."""
    faults, _, _ = check_hdmi(run(f'tb_hdmi_{fault}', alter=alter))
    assert any(expect in f for f in faults), faults[:5]
