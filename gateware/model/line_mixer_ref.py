"""Bit-exact reference for rtl/mix_chan.v + rtl/line_mixer.v.

The decision rule is the integer form of mixer/line_mixer.py `mix()`:
    blend   when |ea - eb| * 256 <  BLEND_Q8  * max(ea, eb)   (or both 0)
    switch  when |ea - eb| * 256 >  SWITCH_Q8 * max(ea, eb)   towards the cleaner one
with BLEND_Q8 = 38 (0.1484 ~ 0.15) and SWITCH_Q8 = 64 (0.25 exactly), plus a
sync/length check the prototype does not have: a bad line loses against a
good one. Lines are paired by (field, line number); see line_mixer.v for the
rules for unpaired lines. The event model includes arrival deadlines, channel
expiry, epochs and recovery. It models line decisions, not CDC cycle delays.
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
        return USE_NONE, cur
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
    """Timed line-level specification. Times are in ns; clocks are independent.

    A healthy unmatched line is usable after one pairing window. Repeated or
    older keys are never usable. Full or incomplete lines cannot enter the
    queue. Both-bad pairs are discarded. These are output requirements, rather
    than a cycle-by-cycle reproduction of the Verilog state machine.
    """

    def __init__(self, ext_bad=(False, False), pair_wait_ns=4096 * 15.4,
                 timeout_ns=262144 * 15.4, **kw):
        self.q = (deque(), deque())
        self.ext_bad = list(ext_bad)
        self.pair_wait = pair_wait_ns
        self.timeout = timeout_ns
        self.kw = kw
        self.cur = 0
        self.trace, self.out = [], []
        self.overflow = False
        self.epoch, self.offset = [0, 0], [0, 0]
        self.previous = [None, None]
        self.last_seen = [None, None]
        self.resync = [True, True]
        self.last_key = None
        self.now = 0.

    def alive(self, ch, now):
        return self.last_seen[ch] is not None and now - self.last_seen[ch] <= self.timeout

    def push(self, ch, rec, now=None):
        if now is None:
            now = self.now
        self.advance(now)
        previous = self.previous[ch]
        if previous is not None and (rec.field != previous[0] or rec.line_in_field < previous[1]):
            self.epoch[ch] = (self.epoch[ch] + 1) % 256
        self.previous[ch] = (rec.field, rec.line_in_field)
        self.last_seen[ch] = now
        if rec.active_count == N_WORDS * 4:
            if len(self.q[ch]) == 4:
                self.overflow = True
            else:
                self.q[ch].append((rec, self.epoch[ch], now,
                                   self.ext_bad[ch] or is_bad(rec, **self.kw)))
        self.run(now)

    def key(self, ch):
        rec, epoch, _, _ = self.q[ch][0]
        return ((epoch + self.offset[ch]) % 256, rec.line_in_field)

    @staticmethod
    def older(a, b):
        delta = (a[0] - b[0]) % 256
        return delta >= 128 or (delta == 0 and a[1] < b[1])

    def past(self, ch):
        k = self.key(ch)
        return self.last_key is not None and (k == self.last_key or self.older(k, self.last_key))

    def bad(self, ch, now):
        return self.ext_bad[ch] or not self.alive(ch, now) or self.q[ch][0][3]

    def _emit(self, use, pop, ch):
        rec = self.q[ch][0][0]
        f, l = rec.field, rec.line_in_field
        self.trace.append((use, pop, f, l))
        if use:
            if use == USE_BLEND:
                ws = blend_words(words(self.q[0][0][0].active), words(self.q[1][0][0].active))
            else:
                ws = words(self.q[use - 1][0][0].active)
            self.out += [(f, l, i, w) for i, w in enumerate(ws)]
            self.last_key = self.key(ch)
        for channel in (0, 1):
            if pop & (1 << channel):
                self.q[channel].popleft()

    def advance(self, now):
        """Resolve deadlines even when neither decoder supplies another marker."""
        while True:
            deadlines = [q[0][2] + self.pair_wait for q in self.q if q]
            future = [t for t in deadlines if self.now < t <= now]
            if not future:
                break
            self.now = min(future)
            self.run(self.now)
        self.now = now
        self.run(now)

    def run(self, now):
        for ch in (0, 1):
            if not self.alive(ch, now):
                self.resync[ch] = True
        while self.q[0] or self.q[1]:
            both = all(self.q)
            raw_pair = both and (self.q[0][0][0].field, self.q[0][0][0].line_in_field) == (
                self.q[1][0][0].field, self.q[1][0][0].line_in_field)
            fresh = both and all(now - q[0][2] < self.pair_wait for q in self.q)
            realign = raw_pair and fresh and any(self.resync)
            if raw_pair and (self.key(0) == self.key(1) or realign):
                if realign:
                    anchor = 1 if self.resync == [True, False] else 0 if self.resync == [False, True] else self.cur
                    other = 1 - anchor
                    self.offset[other] = (self.key(anchor)[0] - self.q[other][0][1]) % 256
                    self.resync = [False, False]
                a, b = self.q[0][0][0], self.q[1][0][0]
                if self.past(0) or self.past(1):
                    use = USE_NONE
                else:
                    use, self.cur = decide_pair(a.hf_energy, b.hf_energy, self.cur,
                                                self.bad(0, now), self.bad(1, now))
                self._emit(use, 3, 0)
                continue
            stale = next((ch for ch in (0, 1) if self.q[ch] and self.past(ch)), None)
            if stale is not None:
                self._emit(USE_NONE, 1 << stale, stale)
                continue
            if both:
                ch = 0 if self.older(self.key(0), self.key(1)) else 1
            else:
                ch = 0 if self.q[0] else 1
                if now - self.q[ch][0][2] < self.pair_wait:
                    return
            use = USE_NONE if self.bad(ch, now) else 1 << ch
            if use:
                self.cur = ch
            self._emit(use, 1 << ch, ch)
