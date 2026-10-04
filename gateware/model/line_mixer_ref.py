"""Bit-exact reference for rtl/mix_chan.v + rtl/line_mixer.v.

The decision rule is the integer form of mixer/line_mixer.py `mix()`:
    blend   when |ea - eb| * 256 <  BLEND_Q8  * max(ea, eb)   (or both 0)
    switch  when |ea - eb| * 256 >  SWITCH_Q8 * max(ea, eb)   towards the cleaner one
with BLEND_Q8 = 38 (0.1484 ~ 0.15) and SWITCH_Q8 = 64 (0.25 exactly), plus a
sync/length check the prototype does not have: a bad line loses against a
good one. Lines are paired by (field, line number); see line_mixer.v for the
rules for unpaired lines. The model assumes both channels stay alive.
"""
from collections import deque

N_WORDS = 360
USE_A, USE_B, USE_BLEND, USE_NONE = 0b01, 0b10, 0b11, 0b00


def is_bad(rec, len_ntsc=1716, len_pal=1728, tol=2):
    length = min(rec.length, 4095)
    return rec.xy_bad != 0 or not (abs(length - len_ntsc) <= tol or abs(length - len_pal) <= tol)


def decide_pair(ea, eb, cur, bad_a=False, bad_b=False, blend_q8=38, switch_q8=64):
    """(use, new_cur) for a paired line; cur 0 = A, 1 = B."""
    if bad_a and not bad_b:
        return USE_B, 1
    if bad_b and not bad_a:
        return USE_A, 0
    if bad_a and bad_b:
        return (USE_B if cur else USE_A), cur
    m, d = max(ea, eb), abs(ea - eb)
    if m == 0 or d * 256 < blend_q8 * m:
        return USE_BLEND, cur
    if cur == 0 and ea > eb and d * 256 > switch_q8 * m:
        return USE_B, 1
    if cur == 1 and eb > ea and d * 256 > switch_q8 * m:
        return USE_A, 0
    return (USE_B if cur else USE_A), cur


def words(active):
    """360 little-endian words {Y1, Cr, Y0, Cb} of a line's active bytes."""
    return [int.from_bytes(active[4 * i:4 * i + 4], 'little') for i in range(N_WORDS)]


def blend_words(wa, wb):
    out = []
    for x, y in zip(wa, wb):
        v = 0
        for k in range(4):
            a, b = (x >> 8 * k) & 0xFF, (y >> 8 * k) & 0xFF
            v |= ((a + b + 1) >> 1) << 8 * k
        out.append(v)
    return out


class Mixer:
    """Feed completed line records per channel in arrival order; read `trace` and `out`."""

    def __init__(self, near=8, ext_bad=(False, False), **kw):
        self.q = (deque(), deque())
        self.ext_bad = ext_bad    # decoder status says no lock (held for the whole run)
        self.near = near
        self.kw = kw
        self.cur = 0
        self.trace = []           # (use, pop, field, line)
        self.out = []             # (field, line, idx, data)
        self.overflow = False

    def push(self, ch, rec):
        if len(self.q[ch]) == 4:
            self.overflow = True
        else:
            self.q[ch].append(rec)
        self.run()

    def _emit(self, use, pop, f, l):
        self.trace.append((use, pop, f, l))
        qa, qb = self.q
        if use:
            if use == USE_BLEND:
                ws = blend_words(words(qa[0].active), words(qb[0].active))
            else:
                ws = words((qa if use == USE_A else qb)[0].active)
            self.out += [(f, l, i, w) for i, w in enumerate(ws)]
        if pop & 1:
            qa.popleft()
        if pop & 2:
            qb.popleft()

    def run(self):
        qa, qb = self.q
        while True:
            if qa and qb and (qa[0].field, qa[0].line_in_field) == (qb[0].field, qb[0].line_in_field):
                a, b = qa[0], qb[0]
                use, self.cur = decide_pair(a.hf_energy, b.hf_energy, self.cur,
                                            is_bad(a, **self.kw) or self.ext_bad[0],
                                            is_bad(b, **self.kw) or self.ext_bad[1])
                self._emit(use, 0b11, a.field, a.line_in_field)
            elif qa and qb and qa[0].field == qb[0].field:
                la, lb = qa[0].line_in_field, qb[0].line_in_field
                near = abs(la - lb) < self.near
                if la < lb:
                    self._emit(USE_A if (self.cur == 0 or near) else USE_NONE, 0b01, qa[0].field, la)
                else:
                    self._emit(USE_B if (self.cur == 1 or near) else USE_NONE, 0b10, qb[0].field, lb)
            elif len(qa) >= 3:
                self._emit(USE_A if self.cur == 0 else USE_NONE, 0b01, qa[0].field, qa[0].line_in_field)
            elif len(qb) >= 3:
                self._emit(USE_B if self.cur == 1 else USE_NONE, 0b10, qb[0].field, qb[0].line_in_field)
            else:
                return
