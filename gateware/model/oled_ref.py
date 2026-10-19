"""Reference for the picture ssd1306_text.v draws: the 4 x 128 page bytes of the 128 x 32 OLED
from four text rows, with a row pair drawn double size.

Single size: 21 cells of 6 pixels per row, a 5x7 glyph (model/font5x7.py) in the first 5 columns,
one page (8 pixel rows) per text row. Double size (puck_ui text_big, one bit per row pair 0-1 and
2-3): the pair is one row of 10 cells of 12 pixels; each glyph column is drawn twice, each glyph
row twice: the top page holds glyph rows 0-3, the bottom page rows 4-6 and two blank lines. The
characters are those of the pair's top row; the bottom row's text is not drawn. 10 cells cover
120 pixels, the last 8 stay dark.

decode() is the inverse for the tests (the screen reconstructed from the I2C writes), png() writes
the picture for the design notes (pure Python, no library).

    python gateware/model/oled_ref.py out.png "F4 5800  @" "" "A:LOCK  75 B:NOSIG --" "MIX BUF TV      SAVED" --big 0
"""
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import font5x7  # noqa: E402

UNKNOWN = '~'


def _stretch(nibble):
    """4 glyph rows -> 8 pixel rows (each row twice)."""
    return sum(0b11 << (2 * y) for y in range(4) if nibble >> y & 1)


def _squeeze(byte):
    """Inverse of _stretch; None when the rows do not come in pairs."""
    if any((byte >> (2 * y) & 3) in (1, 2) for y in range(4)):
        return None
    return sum(1 << y for y in range(4) if byte >> (2 * y) & 1)


def page_bytes(rows, big=(False, False)):
    """4 lists of 128 column bytes (bit 0 = top) for rows (4 strings, padded or cut to 21
    characters) with big[k] = row pair k drawn double size."""
    rows = [(r + ' ' * 21)[:21] for r in rows]
    out = []
    for page in range(4):
        pair, top = page >> 1, page & 1 == 0
        line = [0] * 128
        if big[pair]:
            text = rows[2 * pair]
            for cell in range(10):
                cols = font5x7.columns(text[cell])
                for k in range(5):
                    g = cols[k]
                    b = _stretch(g & 0xF) if top else _stretch(g >> 4 & 0x7)
                    line[12 * cell + 2 * k] = line[12 * cell + 2 * k + 1] = b
        else:
            for cell in range(21):
                cols = font5x7.columns(rows[page][cell])
                for k in range(5):
                    line[6 * cell + k] = cols[k]
        out.append(line)
    return out


def decode_small(line):
    return font5x7.render_text(line)


def decode_big(top, bottom):
    """The 10 characters of a double-size pair, UNKNOWN where the columns match no glyph or are
    not doubled; None when the pixels in the gaps (or beyond 120) are lit."""
    lookup = {tuple(font5x7.columns(c)): c for c in font5x7.GLYPHS}
    if any(top[x] or bottom[x] for x in range(120, 128)):
        return None
    out = ''
    for cell in range(10):
        cols = []
        for k in range(5):
            x = 12 * cell + 2 * k
            if top[x] != top[x + 1] or bottom[x] != bottom[x + 1] or bottom[x] & 0xC0:
                return None
            lo, hi = _squeeze(top[x]), _squeeze(bottom[x] & 0x3F)
            if lo is None or hi is None:
                return None
            cols.append(lo | hi << 4)
        if any(top[12 * cell + 10 + d] or bottom[12 * cell + 10 + d] for d in range(2)):
            return None
        out += lookup.get(tuple(cols), UNKNOWN)
    return out


def decode(ram):
    """The 4 text rows of a screen from its page bytes: a row pair whose single-size reading has an
    unknown glyph is read double size (10 characters in the top row, the bottom row blank).
    Returns (rows, big)."""
    rows, big = [], []
    for pair in range(2):
        small = [decode_small(ram[2 * pair + i]) for i in range(2)]
        if UNKNOWN in small[0] + small[1]:
            text = decode_big(ram[2 * pair], ram[2 * pair + 1])
            if text is not None and UNKNOWN not in text:
                rows += [text + ' ' * 11, ' ' * 21]
                big.append(True)
                continue
        rows += small
        big.append(False)
    return rows, tuple(big)


def pixels(rows, big=(False, False)):
    """32 lists of 128 bits."""
    pages = page_bytes(rows, big)
    return [[pages[y >> 3][x] >> (y & 7) & 1 for x in range(128)] for y in range(32)]


def png(path, rows, big=(False, False), scale=4, on=(230, 240, 255), off=(8, 10, 14)):
    """The screen as a PNG, every OLED pixel a scale x scale block with a one pixel dark seam."""
    bits = pixels(rows, big)
    w, h = 128 * scale, 32 * scale
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            lit = bits[y // scale][x // scale] and (x % scale) != scale - 1 and (y % scale) != scale - 1
            raw += bytes(on if lit else off)

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


if __name__ == '__main__':
    args = sys.argv[1:]
    big = (False, False)
    if '--big' in args:
        i = args.index('--big')
        big = tuple(str(k) in args[i + 1].split(',') for k in range(2))
        del args[i:i + 2]
    png(args[0], args[1:5], big)
    print(args[0])
