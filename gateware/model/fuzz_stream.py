"""Seeded disturbance generator for the whole picture chain (sim/test_fuzz_chain.py).

generate(seed) builds two BT.656 byte streams, channel A and channel B, of one camera:
the same fields and lines, each receiver with its own snow, B arriving a few
microseconds before or after A. On top of that it injects disturbances from CLASSES.

What the seed controls
  * whether each class is used (its own probability, CLASSES), and everything the class
    decides: channel, field, line, size. Each class draws from its own random stream,
    seeded with (seed, class name). Turning a class off (`classes=`) leaves the choices of
    every other class unchanged, which is what narrowing a finding down needs. Positions
    are drawn as fractions of a field, so they do not move when another class changes
    the geometry.
  * without any class: the camera's first line and byte, B's arrival offset against A
    (within +-3 us), the snow on every line of each receiver, the decoder start.

Geometry (geometry='scaled', the default; the RTL runs at the real clock rates, see
sim/test_fuzz_chain.py)
  NTSC  1716 bytes per line, 24 active lines per field standing for 243, 6 blanking
        lines, one more in every other field when interlaced (262/263 lines);
  PAL   1728 bytes per line, 29 active lines standing for 288, 7 blanking lines.
  N_FIELDS fields. Byte clock 37.0 ns on A (tb_mixer.v); the mixer and SDRAM clock 15.4 ns.
geometry='full': 243 or 288 active lines and 19 or 24 blanking lines (262/263, 312/313),
  N_FIELDS_FULL fields, the streams starting in the last fifth of the first one; LOW with PAL
  is allowed there.

The classes (name: what is injected)
  pal          PAL source (both channels)
  progressive  non-interlaced source: equal blanking in every field, F = 1 on both decoders
  field_len    active lines per field vary by one: 23-25 (242-244), 28-30 (286-288)
  field_cut    a field ends early on one or both channels: the rest of it is silent, or the
               next blanking comes at once (that channel is then early from there on)
  vbi_short    a field with 0-3 blanking lines: the camera's (both channels, the timing
               changes) or one decoder's (the last blanking lines carry V = 0)
  vbi_long     3-20 more blanking lines, camera or decoder as above
  f_stuck      F held at 0 or 1 on one or both decoders, from reset or from a field on
  f_wrong      F flipped in the codes of 1-3 lines
  xy_error     1-4 timing codes with 1, 2 or 3 bits flipped (corrected, bad, or wrong code)
  eav_missing  1-3 EAV codes replaced by blanking
  sav_missing  1-3 SAV codes replaced by blanking
  sav_double   an extra SAV in the horizontal blanking or in the active part of a line
  sav_late     SAV 1-200 bytes late, EAV on time (short active part, line length right)
  line_long    1-3 lines 1-300 bytes long (extra blanking)
  line_short   1-3 lines 1-250 bytes short
  line_drop    1-3 lines lost: both codes replaced by blanking (timing kept), or the line's
               bytes removed (that channel is a line early from there on)
  field_drop   a field missing on one channel: silent, or its bytes removed
  bit_error    bit flips in active bytes (any value, 00 and FF included)
  luma_click   luma samples set outside 16-235 (1-15, 236-254)
  noise_line   whole active parts of random bytes 1-254, one channel or both
  b_silent     B stops in the middle of a field for 1-60 lines and comes back in step
  b_offset     B 1-7 lines (plus a fraction) after or before A for the whole run
  b_swap       B's line timing jumps by twice its offset (plus a little), so that A and B
               change places in time; the line with the jump has the wrong length
  b_drift      B's byte clock 50-300 ppm off A's
  dec_reset    one decoder resets: no output (bytes 00) for 0.3-4 ms, status not valid
               (ext_bad 0) meanwhile, then no lock (ext_bad 1) for 0-2 ms, back in step
  ext_nolock   decoder status says no lock, 1-3 windows of 0.1-6 ms on A or B
  mode_switch  ll_mode (BUF/LOW) switched 1-2 times while video runs, sometimes LOW from
               reset; NTSC only (fb_backend.v takes PAL from a line count of 270, which
               the scaled fields never reach)
  b_edge       B's lines arrive 1024 + k mixer clocks (k = -3..3, plus a fraction of a clock)
               after or before A's: the edge of the pairing window. Never drawn at random;
               generate(force=('b_edge',)) uses it

The reference models are not changed by anything here: the streams go through
bt656.Receiver, line_mixer_ref.Mixer and fb_ref.FieldStore in sim/test_fuzz_chain.py.
"""
import random
from dataclasses import dataclass, field

import bt656

N_FIELDS = 10
T_A = 37.0                         # ns per byte, channel A
T_S = 15.4                         # mixer / SDRAM clock (ns)
T_PAIR_NS = 1024 * T_S
RST_NS = 500.0                     # tb_chain.v releases reset here; stream times count from it
START_NS = 600_000.0               # first byte of A after reset (the SDRAM is ready by then)
ACTIVE = bt656.ACTIVE_BYTES

GEOM = {
    'scaled': {'ntsc': dict(line=1716, lines=24, vbi=6, var=(23, 25)),
               'pal': dict(line=1728, lines=29, vbi=7, var=(28, 30))},
    # the real thing: 262/263 and 312/313 lines per field
    'full': {'ntsc': dict(line=1716, lines=243, vbi=19, var=(242, 244)),
             'pal': dict(line=1728, lines=288, vbi=24, var=(286, 288))},
}
N_FIELDS_FULL = 4

CLASSES = {                        # name: probability that a seed uses it
    'pal': 0.25, 'progressive': 0.15, 'field_len': 0.40, 'field_cut': 0.20,
    'vbi_short': 0.15, 'vbi_long': 0.15, 'f_stuck': 0.15, 'f_wrong': 0.20,
    'xy_error': 0.35, 'eav_missing': 0.25, 'sav_missing': 0.20, 'sav_double': 0.20,
    'sav_late': 0.20, 'line_long': 0.20, 'line_short': 0.20, 'line_drop': 0.20,
    'field_drop': 0.10, 'bit_error': 0.30, 'luma_click': 0.30, 'noise_line': 0.25,
    'b_silent': 0.25, 'b_offset': 0.15, 'b_swap': 0.15, 'b_drift': 0.20,
    'dec_reset': 0.15, 'ext_nolock': 0.20, 'mode_switch': 0.30,
    'b_edge': 0.0,                 # only when forced (generate(force=...)), so older seeds stay as they were
}
CH_A, CH_B, LL = 0, 1, 2           # control kinds (tb_chain.v ctl.hex)


def picture(k, n, x):
    """The camera: (Cb, Y, Cr) of sample x of active line n of field k (as sim/test_mixer.py)."""
    y = 16 + (k * 29 + n * 13 + x) % 220
    cb = 64 + (n * 7 + x // 2 + k * 40) % 128
    cr = 64 + (n * 11 + (x // 2) * 3 + k * 20) % 128
    return cb, y, cr


def active_bytes(k, n, amp, rng):
    """1440 active bytes of camera line (k, n) with snow of amplitude amp."""
    def s(v):
        return max(1, min(254, v + (rng.randint(-amp, amp) if amp else 0)))
    out = bytearray()
    for x in range(0, 720, 2):
        cb, y0, cr = picture(k, n, x)
        y1 = picture(k, n, x + 1)[1]
        out += bytes((s(cb), s(y0), s(cr), s(y1)))
    return out


@dataclass
class Line:
    """One line of a channel's stream: EAV, horizontal blanking, SAV, active part."""
    k: int                         # camera field
    i: int                         # line within the field, blanking lines first
    v: int                         # V bit (1: blanking)
    f: int                         # F bit
    n: int                         # active line number in the camera field (-1 for blanking)
    hb: int                        # horizontal blanking bytes between EAV and SAV
    act: bytearray = None          # 1440 active bytes (None: blanking)
    eav: bytes = None              # 4 bytes sent instead of the EAV
    sav: bytes = None              # 4 bytes sent instead of the SAV
    late: int = 0                  # SAV that many bytes late, EAV on time
    sav2: tuple = None             # ('h' | 'a', offset): an extra SAV in the blanking / active part
    drop: bool = False             # bytes removed
    shift: int = 0                 # bytes added (> 0) or removed (< 0) in this line's blanking
    notes: list = field(default_factory=list)


@dataclass
class Scenario:
    seed: int
    enabled: tuple                 # classes that were allowed
    used: dict                     # class -> list of what it injected (human readable)
    std: str
    interlaced: bool
    a: bytes
    b: bytes
    t_a: float
    t_b: float
    start_a: float                 # ns after reset, as tb_mixer.v
    start_b: float
    ll0: int                       # ll_mode at reset
    ctl: list                      # [(ns after reset, kind CH_A / CH_B / LL, value)]
    lines: dict                    # channel -> [Line] as sent, with .pos (first byte) set
    geometry: str
    camera: list                   # [(vbi, active lines)] per camera field
    silences: dict                 # channel -> [(first byte, bytes, fill)]
    end_ns: float = 0.0            # last byte of the longer stream, ns after reset
    ahead: bool = False            # a channel's stream lost a field's bytes (field_drop removed, field_cut
                                   # early): from there on it delivers camera fields before the camera has
                                   # them, which no decoder can; field ages mean little then

    def classes_used(self):
        return sorted(self.used)


def _rng(seed, name):
    return random.Random(f'{seed}:{name}')


def _xy_bits(rng, code):
    """Flip 1, 2 or 3 bits of a timing code byte."""
    nb = rng.choice((1, 1, 2, 2, 3))
    bits = rng.sample(range(8), nb)
    for b in bits:
        code ^= 1 << b
    return code, nb


def generate(seed, classes=None, n_fields=None, force=(), geometry='scaled', density=1.0):
    """Scenario for one seed. classes: the classes allowed (None: all); each allowed class is
    used with its probability in CLASSES, times density (capped at 1). force: classes used
    whatever their probability."""
    if n_fields is None:
        n_fields = N_FIELDS if geometry == 'scaled' else N_FIELDS_FULL
    enabled = tuple(sorted(set(CLASSES if classes is None else classes) | set(force)))
    unknown = set(enabled) - set(CLASSES)
    assert not unknown, f'unknown classes {unknown}'
    rngs = {c: _rng(seed, c) for c in CLASSES}
    on = {c for c in enabled if rngs[c].random() < min(1.0, CLASSES[c] * density) or c in force}
    if 'mode_switch' in on and 'pal' in on and geometry == 'scaled':
        on.discard('mode_switch')                        # see the docstring
    used = {c: [] for c in sorted(on)}
    base = _rng(seed, 'base')

    std = 'pal' if 'pal' in on else 'ntsc'
    g = GEOM[geometry][std]
    lb = g['line']
    hb0 = lb - ACTIVE - 8
    interlaced = 'progressive' not in on
    if 'pal' in on:
        used['pal'].append('PAL')
    if 'progressive' in on:
        used['progressive'].append('non-interlaced, F = 1')

    # ---- the camera: blanking and active lines per field (both channels)
    vbi = [g['vbi'] + ((k & 1) if interlaced else 0) for k in range(n_fields)]
    act = [g['lines']] * n_fields
    if 'field_len' in on:
        r = rngs['field_len']
        act = [r.randint(*g['var']) for _ in range(n_fields)]
        used['field_len'].append(f'active lines {act}')
    cam_vbi_note = {}
    for cname, lo, hi in (('vbi_short', 0, 3), ('vbi_long', 3, 20)):
        if cname in on:
            r = rngs[cname]
            k = r.randrange(1, n_fields)
            m = r.randint(lo, hi)
            where = r.choice(('camera', 'camera', 'a', 'b'))
            cam_vbi_note[cname] = (k, m, where)
            if where == 'camera':
                vbi[k] = m if cname == 'vbi_short' else vbi[k] + m
            used[cname].append(f'{where}: field {k} blanking {"=" if cname == "vbi_short" else "+"}{m}')

    # ---- per channel lines
    snow = {0: _rng(seed, 'snow_a'), 1: _rng(seed, 'snow_b')}
    g0 = base.randrange(vbi[0] + act[0])                  # first camera line of the streams
    if geometry != 'scaled':
        g0 = (vbi[0] + act[0]) * 4 // 5 + g0 // 5
    lines = {}
    for ch in (0, 1):
        ls = []
        for k in range(n_fields):
            for i in range(vbi[k] + act[k]):
                if k == 0 and i < g0:
                    continue
                v = 1 if i < vbi[k] else 0
                # F changes two lines into the blanking, as in BT.656 (F of the line's own field after that)
                f = (k & 1) if (i >= 2 or k == 0) else ((k - 1) & 1)
                if not interlaced:
                    f = 1
                n = i - vbi[k] if not v else -1
                amp = snow[ch].choice((0, 0, 3, 6, 25, 60))
                ls.append(Line(k, i, v, f, n, hb0, None if v else active_bytes(k, n, amp, snow[ch])))
        lines[ch] = ls

    def pick_line(r, chs, active_only=True, k=None):
        """A line (channel, index into lines[ch]) chosen from fractions: field, then line."""
        ch = r.choice(chs)
        kk = r.randrange(n_fields) if k is None else k
        u = r.random()
        cand = [j for j, ln in enumerate(lines[ch]) if ln.k == kk and (ln.v == 0 or not active_only)]
        if not cand:
            cand = [j for j, ln in enumerate(lines[ch]) if (ln.v == 0 or not active_only)]
        return ch, cand[min(len(cand) - 1, int(u * len(cand)))]

    def chans(r, both_weight=1):
        return r.choice([(0,), (1,)] + [(0, 1)] * both_weight)

    def name(ch):
        return 'AB'[ch]

    # decoder-level blanking changes: relabel V, timing kept
    for cname, (k, m, where) in cam_vbi_note.items():
        if where == 'camera':
            continue
        ch = 0 if where == 'a' else 1
        fl = [ln for ln in lines[ch] if ln.k == k]
        nv = sum(1 for ln in fl if ln.v)
        if cname == 'vbi_short':
            for ln in fl[min(m, nv):nv]:
                ln.v, ln.notes = 0, ln.notes + ['vbi_short']
                ln.n = -1
                ln.act = bytearray(bt656.blanking(ACTIVE))
        else:
            for ln in fl[nv:nv + m]:
                ln.v, ln.act, ln.notes = 1, None, ln.notes + ['vbi_long']

    # F stuck / wrong
    if 'f_stuck' in on:
        r = rngs['f_stuck']
        val = r.randrange(2)
        k0 = r.choice((0, 0, r.randrange(n_fields)))
        for ch in chans(r):
            for ln in lines[ch]:
                if ln.k >= k0:
                    ln.f = val
            used['f_stuck'].append(f'{name(ch)}: F = {val} from field {k0}')
    if 'f_wrong' in on:
        r = rngs['f_wrong']
        for _ in range(r.randint(1, 3)):
            ch, j = pick_line(r, (0, 1), active_only=r.random() < 0.8)
            ln = lines[ch][j]
            ln.f ^= 1
            ln.notes.append('f_wrong')
            used['f_wrong'].append(f'{name(ch)}: field {ln.k} line {ln.i}')

    # timing codes
    if 'xy_error' in on:
        r = rngs['xy_error']
        for _ in range(r.randint(1, 4)):
            ch, j = pick_line(r, (0, 1), active_only=r.random() < 0.7)
            ln = lines[ch][j]
            which = r.choice(('eav', 'sav'))
            code, nb = _xy_bits(r, bt656.xy(ln.f, ln.v, 1 if which == 'eav' else 0))
            setattr(ln, which, bytes((0xFF, 0, 0, code)))
            ln.notes.append(f'xy_error {which} {nb}')
            used['xy_error'].append(f'{name(ch)}: field {ln.k} line {ln.i} {which} {nb} bit(s) -> {code:02x} '
                                    f'{bt656.XY_TABLE[code][3]}')
    for cname, which in (('eav_missing', 'eav'), ('sav_missing', 'sav')):
        if cname in on:
            r = rngs[cname]
            for _ in range(r.randint(1, 3)):
                ch, j = pick_line(r, (0, 1), active_only=r.random() < 0.8)
                ln = lines[ch][j]
                setattr(ln, which, bytes(bt656.blanking(4)))
                ln.notes.append(cname)
                used[cname].append(f'{name(ch)}: field {ln.k} line {ln.i}')
    if 'sav_double' in on:
        r = rngs['sav_double']
        ch, j = pick_line(r, (0, 1))
        ln = lines[ch][j]
        where = r.choice(('h', 'a'))
        off = r.randrange(0, hb0 - 4) if where == 'h' else r.randrange(0, ACTIVE - 4)
        ln.sav2 = (where, off)
        ln.notes.append('sav_double')
        used['sav_double'].append(f'{name(ch)}: field {ln.k} line {ln.i} extra SAV in the {"blanking" if where == "h" else "active part"} at {off}')
    if 'sav_late' in on:
        r = rngs['sav_late']
        ch, j = pick_line(r, (0, 1))
        ln = lines[ch][j]
        ln.late = r.choice((1, 2, 3, 4, r.randint(5, 200)))
        ln.notes.append('sav_late')
        used['sav_late'].append(f'{name(ch)}: field {ln.k} line {ln.i} SAV {ln.late} bytes late')
    for cname, sign, hi in (('line_long', 1, 300), ('line_short', -1, 250)):
        if cname in on:
            r = rngs[cname]
            for _ in range(r.randint(1, 3)):
                ch, j = pick_line(r, (0, 1), active_only=r.random() < 0.8)
                ln = lines[ch][j]
                d = r.choice((1, 2, 3, r.randint(4, hi)))
                ln.shift += sign * d
                ln.notes.append(cname)
                used[cname].append(f'{name(ch)}: field {ln.k} line {ln.i} {sign * d:+d} bytes')

    # lines and fields lost
    if 'line_drop' in on:
        r = rngs['line_drop']
        for _ in range(r.randint(1, 3)):
            ch, j = pick_line(r, (0, 1))
            ln = lines[ch][j]
            if r.random() < 0.7:
                ln.eav = ln.sav = bytes(bt656.blanking(4))
                ln.notes.append('line_drop lost')
                used['line_drop'].append(f'{name(ch)}: field {ln.k} line {ln.i} codes lost')
            else:
                ln.drop = True
                ln.notes.append('line_drop removed')
                used['line_drop'].append(f'{name(ch)}: field {ln.k} line {ln.i} removed')
    silences = {0: [], 1: []}             # (line index, offset in line, bytes, fill), resolved after layout
    ahead = False
    if 'field_drop' in on:
        r = rngs['field_drop']
        ch = r.randrange(2)
        k = r.randrange(1, n_fields - 1)
        removed = r.random() < 0.3
        fl = [ln for ln in lines[ch] if ln.k == k]
        if removed:
            for ln in fl:
                ln.drop = True
        else:
            j = lines[ch].index(fl[0])
            silences[ch].append((j, 0, sum(lb for _ in fl), 'blank'))
        used['field_drop'].append(f'{name(ch)}: field {k} {"removed" if removed else "silent"}')
        ahead = ahead or removed
    if 'field_cut' in on:
        r = rngs['field_cut']
        k = r.randrange(1, n_fields - 1)
        for ch in chans(r, 2):
            fl = [ln for ln in lines[ch] if ln.k == k and not ln.v]
            if not fl:
                continue
            m = min(len(fl) - 1, max(2, int(r.random() * len(fl))))
            early = r.random() < 0.4
            if early:
                for ln in fl[m:]:
                    ln.drop = True
            else:
                j = lines[ch].index(fl[m])
                silences[ch].append((j, 0, (len(fl) - m) * lb, 'blank'))
            used['field_cut'].append(f'{name(ch)}: field {k} after {m} lines, {"next field at once" if early else "rest silent"}')
            ahead = ahead or early

    # content
    if 'bit_error' in on:
        r = rngs['bit_error']
        for _ in range(r.randint(1, 12)):
            ch, j = pick_line(r, (0, 1))
            ln = lines[ch][j]
            for _ in range(r.randint(1, 8)):
                p = r.randrange(ACTIVE)
                ln.act[p] ^= 1 << r.randrange(8)
            ln.notes.append('bit_error')
            used['bit_error'].append(f'{name(ch)}: field {ln.k} line {ln.i}')
    if 'luma_click' in on:
        r = rngs['luma_click']
        for _ in range(r.randint(1, 15)):
            ch, j = pick_line(r, (0, 1))
            ln = lines[ch][j]
            for _ in range(r.randint(1, 40)):
                ln.act[2 * r.randrange(720) + 1] = r.choice((r.randint(1, 15), r.randint(236, 254)))
            ln.notes.append('luma_click')
            used['luma_click'].append(f'{name(ch)}: field {ln.k} line {ln.i}')
    if 'noise_line' in on:
        r = rngs['noise_line']
        for _ in range(r.randint(1, 6)):
            chs = chans(r)
            ch, j = pick_line(r, chs[:1])
            ln0 = lines[ch][j]
            for c in chs:
                for ln in lines[c]:
                    if (ln.k, ln.i) == (ln0.k, ln0.i) and not ln.v:
                        ln.act = bytearray(r.randint(1, 254) for _ in range(ACTIVE))
                        ln.notes.append('noise_line')
            used['noise_line'].append(f'{"".join(name(c) for c in chs)}: field {ln0.k} line {ln0.i}')

    # ---- serialise
    fills = {'blank': None, 'zero': 0x00, 'grey': 0x80}

    def serialise(ch):
        out = bytearray()
        ls = []
        for ln in lines[ch]:
            if ln.drop:
                continue
            ln.pos = len(out)
            hb = max(0, ln.hb + ln.shift)
            e = ln.eav if ln.eav is not None else bytes((0xFF, 0, 0, bt656.xy(ln.f, ln.v, 1)))
            s = ln.sav if ln.sav is not None else bytes((0xFF, 0, 0, bt656.xy(ln.f, ln.v, 0)))
            a = ln.act if ln.act is not None else bytearray(bt656.blanking(ACTIVE))
            blank = bytearray(bt656.blanking(hb + ln.late))
            a = bytearray(a[:ACTIVE - ln.late]) if ln.late else bytearray(a)
            if ln.sav2:
                where, off = ln.sav2
                code = bytes((0xFF, 0, 0, bt656.xy(ln.f, ln.v, 0)))
                if where == 'h' and off + 4 <= len(blank):
                    blank[off:off + 4] = code
                elif where == 'a' and off + 4 <= len(a):
                    a[off:off + 4] = code
            out += e + blank + s + a
            ls.append(ln)
        out += bytes((0xFF, 0, 0, bt656.xy(1, 1, 1))) + bt656.blanking(64)      # closing EAV
        return out, ls

    data, sent = {}, {}
    for ch in (0, 1):
        data[ch], sent[ch] = serialise(ch)

    def line_at(ch, j):
        """The first line at or after lines[ch][j] that is sent."""
        for ln in lines[ch][j:]:
            if not ln.drop:
                return ln
        return sent[ch][-1]

    # B offset and swap, drift, starts
    r = base
    start_a = START_NS
    frac = r.uniform(-3000.0, 3000.0)
    line_ns = lb * T_A
    off_lines = 0
    if 'b_offset' in on:
        rr = rngs['b_offset']
        off_lines = rr.choice((-1, 1)) * rr.randint(1, 7)
        frac = rr.uniform(-0.45, 0.45) * line_ns
        used['b_offset'].append(f'B {off_lines:+d} lines {frac:+.0f} ns')
    if 'b_edge' in on:
        rr = rngs['b_edge']
        k = rr.randint(-3, 3)
        frac = rr.choice((-1, 1)) * ((1024 + k) * T_S + rr.uniform(0.0, T_S))
        off_lines = 0
        used['b_edge'].append(f'B {frac:+.1f} ns from A (1024 {k:+d} clocks and a fraction)')
    start_b = start_a + off_lines * line_ns + frac
    if start_b < 400_000.0:                               # keep both after the SDRAM is ready
        d = 400_000.0 - start_b
        start_a += d
        start_b += d
    t_b = T_A
    if 'b_drift' in on:
        rr = rngs['b_drift']
        ppm = rr.choice((-1, 1)) * rr.randint(50, 300)
        t_b = T_A * (1 + ppm * 1e-6)
        used['b_drift'].append(f'B clock {ppm:+d} ppm')

    if 'b_swap' in on:
        rr = rngs['b_swap']
        _, j = pick_line(rr, (1,))
        # B is frac ns after A (frac < 0: before): a jump of -2 frac and a little more flips the order
        u, s1 = rr.uniform(200.0, 3000.0), rr.choice((-1, 1))
        d_ns = -2 * frac - (u if frac >= 0 else -u)
        if abs(frac) < 200.0:
            d_ns = s1 * rr.uniform(500.0, 6000.0)
        nbytes = int(round(d_ns / t_b))
        ln = line_at(1, j)
        ln.shift += nbytes
        ln.notes.append('b_swap')
        used['b_swap'].append(f'B field {ln.k} line {ln.i}: {nbytes:+d} bytes ({d_ns:+.0f} ns; B was {frac:+.0f} ns from A)')
        data[1], sent[1] = serialise(1)

    # ---- silences and resets (time kept)
    ctl = []
    ext = {0: [], 1: []}                                  # [(on ns, off ns)] after reset

    def ns_of(ch, pos):
        return (start_a if ch == 0 else start_b) + pos * (T_A if ch == 0 else t_b)

    def pos_of(ch, t):
        return int((t - (start_a if ch == 0 else start_b)) / (T_A if ch == 0 else t_b))

    for ch in (0, 1):
        for j, off, nb, fill in silences[ch]:
            ln = lines[ch][j]
            if ln.drop:
                continue
            p0 = ln.pos + off
            _silence(data[ch], p0, nb, fills[fill])
    if 'b_silent' in on:
        rr = rngs['b_silent']
        _, j = pick_line(rr, (1,))
        ln = line_at(1, j)
        m = rr.choice((1, 2, 3, rr.randint(4, 12), rr.randint(13, 60)))
        p0 = ln.pos + rr.randrange(lb)
        fill = rr.choice(('blank', 'grey'))
        _silence(data[1], p0, m * lb, fills[fill])
        used['b_silent'].append(f'B silent ({fill}) from field {ln.k} line {ln.i} for {m} lines')
    if 'dec_reset' in on:
        rr = rngs['dec_reset']
        ch = rr.randrange(2)
        _, j = pick_line(rr, (ch,))
        ln = line_at(ch, j)
        dur = rr.uniform(300_000.0, 4_000_000.0)
        p0 = ln.pos + rr.randrange(lb)
        nb = int(dur / (T_A if ch == 0 else t_b))
        _silence(data[ch], p0, nb, 0x00)
        t_end = ns_of(ch, p0 + nb)
        nolock = rr.choice((0.0, rr.uniform(50_000.0, 2_000_000.0)))
        if nolock:
            ext[ch].append((t_end, t_end + nolock))
        used['dec_reset'].append(f'{name(ch)}: no output from field {ln.k} line {ln.i} for {dur / 1e6:.2f} ms, '
                                 f'then no lock for {nolock / 1e6:.2f} ms')
    end_ns = max(ns_of(0, len(data[0])), ns_of(1, len(data[1])))
    if 'ext_nolock' in on:
        rr = rngs['ext_nolock']
        for _ in range(rr.randint(1, 3)):
            ch = rr.randrange(2)
            t0 = start_a + rr.random() * (end_ns - start_a)
            ext[ch].append((t0, t0 + rr.uniform(100_000.0, 6_000_000.0)))
            used['ext_nolock'].append(f'{name(ch)}: no lock {t0 / 1e6:.2f}-{ext[ch][-1][1] / 1e6:.2f} ms')
    for ch in (0, 1):
        for t, v in _windows(ext[ch]):
            ctl.append((t, ch, v))
    ll0 = 0
    if 'mode_switch' in on:
        rr = rngs['mode_switch']
        ll0 = int(rr.random() < 0.25)
        mode = ll0
        ts = sorted(start_a + rr.uniform(0.2, 0.9) * (end_ns - start_a) for _ in range(rr.randint(1, 2)))
        for t in ts:
            mode ^= 1
            ctl.append((t, LL, mode))
        used['mode_switch'].append(f'LOW from reset: {ll0}; switches at {", ".join(f"{t / 1e6:.2f}" for t in ts)} ms')
    ctl.sort()

    # the decoders came up in the middle of the first line: drop its first bytes (times kept)
    starts = {0: start_a, 1: start_b}
    for ch, rr in ((0, base), (1, base)):
        skip = rr.randrange(lb)
        data[ch] = data[ch][skip:]
        starts[ch] += skip * (T_A if ch == 0 else t_b)
        for ln in sent[ch]:
            ln.pos -= skip
    start_a, start_b = starts[0], starts[1]

    return Scenario(seed=seed, enabled=enabled, used=used, std=std, interlaced=interlaced,
                    a=bytes(data[0]), b=bytes(data[1]), t_a=T_A, t_b=t_b, start_a=start_a, start_b=start_b,
                    ll0=ll0, ctl=ctl, lines=sent, geometry=geometry, camera=list(zip(vbi, act)), silences=silences,
                    end_ns=end_ns, ahead=ahead)


def _silence(buf, p0, nb, fill):
    """Overwrite nb bytes from p0 with filler without any timing code."""
    p1 = min(len(buf) - 68, p0 + nb)               # keep the closing EAV
    if p1 <= p0:
        return
    if fill is None:
        buf[p0:p1] = bt656.blanking(p1 - p0) if p0 % 2 == 0 else bt656.blanking(p1 - p0 + 1)[1:]
    else:
        buf[p0:p1] = bytes([fill]) * (p1 - p0)


def _windows(ws):
    """Level changes of the union of [on, off) windows: [(t, value)]."""
    merged = []
    for a, b in sorted(ws):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [e for a, b in merged for e in ((a, 1), (b, 0))]


def camera_line(sc, ch, pos):
    """The Line of channel ch that byte pos belongs to (None before the first)."""
    ls = sc.lines[ch]
    lo, hi = 0, len(ls) - 1
    if not ls or pos < ls[0].pos:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ls[mid].pos <= pos:
            lo = mid
        else:
            hi = mid - 1
    return ls[lo]
