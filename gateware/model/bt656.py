"""Golden reference model for ITU-R BT.656 (8-bit, 4:2:2, embedded sync).

Language-neutral reference for the planned FPGA `bt656_rx` + `line_metrics`
modules (design/GATEWARE_PLAN.md): the HDL must produce the same per-line
records as `Receiver` for the same byte stream. `write_hex` dumps streams for
$readmemh-style testbenches.

Timing reference code: FF 00 00 XY, with XY = 1 F V H P3 P2 P1 P0 and
P3 = V^H, P2 = F^H, P1 = F^V, P0 = F^V^H. H=1 is EAV (end of active video),
H=0 is SAV. Active video is 1440 bytes (720 Cb Y Cr Y ... samples); 0x00 and
0xFF never occur in video data, so FF 00 00 is unambiguous.
"""
from dataclasses import dataclass, field

STANDARDS = {
    # total bytes per line, number of lines, (F, V) per 1-based line number
    'ntsc': {'line_bytes': 1716, 'lines': 525},
    'pal': {'line_bytes': 1728, 'lines': 625},
}
ACTIVE_BYTES = 1440


def field_and_vblank(standard, line):
    """(F, V) for a 1-based line number per BT.656 line tables."""
    if standard == 'ntsc':
        f = 0 if 4 <= line <= 265 else 1
        v = 1 if (1 <= line <= 19) or (264 <= line <= 282) else 0
    else:
        f = 0 if line <= 312 else 1
        v = 1 if line <= 22 or 311 <= line <= 335 or line >= 624 else 0
    return f, v


def xy(f, v, h):
    p3, p2, p1, p0 = v ^ h, f ^ h, f ^ v, f ^ v ^ h
    return 0x80 | f << 6 | v << 5 | h << 4 | p3 << 3 | p2 << 2 | p1 << 1 | p0


# Map every possible XY byte to (f, v, h, status): 'ok', 'corrected' (one bit
# flipped) or 'bad' (not within one bit of a valid code).
_VALID = {xy(f, v, h): (f, v, h) for f in (0, 1) for v in (0, 1) for h in (0, 1)}
XY_TABLE = {}
for _b in range(256):
    if _b in _VALID:
        XY_TABLE[_b] = (*_VALID[_b], 'ok')
        continue
    near = [code for code in _VALID if bin(code ^ _b).count('1') == 1]
    XY_TABLE[_b] = (*_VALID[near[0]], 'corrected') if len(near) == 1 else (None, None, None, 'bad')


def blanking(n):
    """Horizontal blanking filler: 80 10 80 10 ... (Cb/Cr = 0x80, Y = 0x10)."""
    return bytes(0x80 if i % 2 == 0 else 0x10 for i in range(n))


def line_bytes(standard, line, active=None):
    """One full line: EAV, blanking, SAV, 1440 active bytes."""
    f, v = field_and_vblank(standard, line)
    total = STANDARDS[standard]['line_bytes']
    if active is None or v:
        active = blanking(ACTIVE_BYTES)
    assert len(active) == ACTIVE_BYTES
    assert 0x00 not in active and 0xFF not in active, 'reserved codes in video data'
    hblank = total - ACTIVE_BYTES - 8
    return (bytes([0xFF, 0, 0, xy(f, v, 1)]) + blanking(hblank)
            + bytes([0xFF, 0, 0, xy(f, v, 0)]) + bytes(active))


def frame_bytes(standard, luma_fn=lambda line, x: 0x10 + (x * 219 // 720)):
    """A full frame; luma_fn(line, x) gives Y for sample x (0..719) of a line."""
    out = bytearray()
    for line in range(1, STANDARDS[standard]['lines'] + 1):
        act = bytearray()
        for x in range(720):
            act += bytes([0x80, max(1, min(254, luma_fn(line, x)))])  # Cb/Cr = 0x80, Y
        out += line_bytes(standard, line, bytes(act))
    return bytes(out)


@dataclass
class LineRecord:
    """What `bt656_rx` + `line_metrics` must report for each active line."""
    field: int
    line_in_field: int          # active line number within the field, counted on SAVs (see Receiver)
    length: int                 # bytes from the EAV before this line to the EAV ending it (0 if unknown)
    active_count: int           # bytes between SAV and EAV
    xy_corrected: int           # timing codes fixed by the protection bits
    xy_bad: int                 # timing codes that could not be decoded
    hf_energy: int              # sum |Y[n] - Y[n-1]| over the active luma samples
    luma: list = field(default_factory=list, repr=False)
    active: bytes = field(default=b'', repr=False)   # the line's active bytes (Cb Y Cr Y ...)


class Receiver:
    """Byte-at-a-time decoder, mirroring what synchronous logic would do."""

    def __init__(self):
        self.state = 0              # matched bytes of FF 00 00
        self.pos = 0                # bytes since the last EAV
        self.seen_eav = False
        self.in_active = False
        self.line_field = 0         # F bit of the SAV that started the current line
        self.active = bytearray()
        # Line numbers count line *starts*, not received lines, so a line lost to a broken
        # timing code does not shift the rest of the field: an active SAV starts a line, and
        # an EAV with no SAV since the previous EAV means that line's SAV was lost (counted
        # if the previous EAV said the line was active). Numbering restarts at 0 when the
        # field bit of a line start differs from the previous one.
        self.line_no = 0            # number of the line whose SAV was seen last
        self.ev_field = None        # field / number of the last line start
        self.ev_line = 0
        self.sav_since_eav = False
        self.last_eav_fv = None     # (F, V) of the last EAV
        self.xy_corrected = self.xy_bad = 0
        self.records = []

    def _record(self, f):
        luma = list(self.active[1::2])
        hf = sum(abs(a - b) for a, b in zip(luma[1:], luma[:-1]))
        rec = LineRecord(f, self.line_no, self.pos if self.seen_eav else 0, len(self.active),
                         self.xy_corrected, self.xy_bad, hf, luma, bytes(self.active))
        self.xy_corrected = self.xy_bad = 0
        return rec

    def _line_start(self, f):
        n = 0 if (self.ev_field is None or f != self.ev_field) else self.ev_line + 1
        self.ev_field, self.ev_line = f, n
        return n

    def push(self, byte):
        self.pos += 1
        if self.state == 3:
            self.state = 0
            f, v, h, status = XY_TABLE[byte]
            if status == 'corrected':
                self.xy_corrected += 1
            elif status == 'bad':
                self.xy_bad += 1
                self.in_active = False      # cannot trust this line any more
                return
            if self.in_active:
                del self.active[-3:]        # FF 00 00 was collected before it was recognised
            if h == 1:                      # EAV closes the line that began at the previous EAV
                if self.in_active:
                    # the line's field is the F bit of its own SAV: the EAV that ends a
                    # line already belongs to the next line and may carry the next field
                    self.records.append(self._record(self.line_field))
                elif not self.sav_since_eav and self.last_eav_fv is not None and self.last_eav_fv[1] == 0:
                    self._line_start(self.last_eav_fv[0])      # that line's SAV was lost
                self.sav_since_eav = False
                self.last_eav_fv = (f, v)
                self.in_active = False
                self.seen_eav = True
                self.pos = 0
            else:       # SAV
                self.in_active = not v
                self.active = bytearray()
                self.line_field = f
                self.sav_since_eav = True
                if not v:
                    self.line_no = self._line_start(f)
            return
        if self.state == 0 and byte == 0xFF:
            self.state = 1
        elif self.state in (1, 2) and byte == 0x00:
            self.state += 1
        else:
            self.state = 1 if byte == 0xFF else 0
        if self.in_active:
            self.active.append(byte)

    def feed(self, data):
        for b in data:
            self.push(b)
        return self.records


def write_hex(path, data):
    """One byte per line in hex, for Verilog $readmemh / VHDL textio testbenches."""
    with open(path, 'w') as fh:
        fh.write('\n'.join(f'{b:02x}' for b in data) + '\n')
