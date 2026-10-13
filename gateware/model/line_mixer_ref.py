"""Bit-exact reference for rtl/mix_chan.v + rtl/line_mixer.v.

Paired lines. Two lines pair when they carry the same line number and arrived
within T_PAIR of each other (the F bit is not compared: two decoders may
disagree on it). The decision is the integer form of mixer/line_mixer.py `mix()`:
    blend   when |ea - eb| * 256 <  BLEND_Q8  * max(ea, eb)   (or both 0)
    switch  when |ea - eb| * 256 >  SWITCH_Q8 * max(ea, eb)   towards the cleaner one
with BLEND_Q8 = 38 (0.1484 ~ 0.15) and SWITCH_Q8 = 64 (0.25 exactly), plus a
check the prototype does not have: a bad line (undecodable timing code, wrong
length, decoder unlocked) loses against a good one, and of two good lines one from
a weak receiver (ext_weak, RSSI warning) loses against one from a receiver that is
not weak (no blend; that receiver becomes current). A line with fewer than 360
whole words is not stored at all (see push).

Lone lines. A line whose partner has not arrived T_PAIR after it is resolved
alone, oldest first. It is shown
  * if it comes from the current channel, or
  * to fill a gap: the channels are in step (a pair within the last N_STEP
    resolutions), the line is good, and no line of the other channel (whatever
    its number) arrived within T_PAIR of it.
The current channel changes without a pair when
  * health: its last 8 lines were all bad and the other channel's all good, or
  * silence: it has delivered nothing for N_STEP lines of the other channel
    if the channels were in step when it went quiet, else for N_DEAD lines
    (N_DEAD is longer than a vertical blanking interval, so two channels that
    are out of step do not steal `cur` from each other in their blanking).
Nothing here depends on wall-clock silence: a blanking interval common to
both channels produces no lines and therefore no decisions.

Lines bad on both receivers. A line that would be shown although it is bad on
both receivers (a pair of bad lines, or a lone bad line: the other receiver has
none) is not written, unless the line shown before it in the same output field
was such a line as well. The field store replaces a missing line with the line
above (two at most), so a single bad line disappears; in a run of them only the
first is left out, because noise is better than a frozen picture. Everything
else is decided as if the line had been shown: the current channel, health,
silence counters and the output field state. The decision is traced with
use 0 (`omitted` says which ones were left out by this rule).

Output order. Line numbers leave strictly increasing within a field. Each
channel has a field counter (advanced when its own line number restarts); a
line is admitted when it starts a new field or lies above the last line sent.
Whether it starts a new field is judged on a channel that has a line in the
current output field: for a pair whose current channel has none (the other one
carried the field), on the partner.
The output F bit is a synthetic visible boundary tag, not the decoder's F.
An admitted boundary remains pending while lines are omitted; the next emitted
line toggles the last visible tag once, even after several fully omitted fields.

Time is in ns, or in system clock edges. The RTL measures ages in system-clock
cycles from the edge at which mix_chan takes a line's marker from its FIFO;
arrival_cycle() gives that edge from the byte stream. On those times the model is
exact also at the edge of the pairing window (sim/test_mixer.py::
test_pairing_window_edge, sim/test_fuzz_chain.py). On times in ns from the byte
stream alone, decisions within a few cycles of T_PAIR can differ, so the other
mixer tests keep clear of that boundary.
"""
from collections import deque

N_WORDS = 360
USE_A, USE_B, USE_BLEND, USE_NONE = 0b01, 0b10, 0b11, 0b00
T_PAIR_CYCLES = 1024


def arrival_cycle(t_run, t_byte, k, active_count, t_sys):
    """System clock edge at which mix_chan takes the marker of a line, for a bench that drives
    byte 0 of the stream at the first falling edge of the byte clock at or after t_run (ns),
    byte clocks starting low, the system clock starting low with period t_sys. k: index of the
    EAV's XY byte that ends the line. Edges counted from 0 at t_sys / 2.

    The path: bt656_rx takes byte k at the rising edge E(k) and pulses rec_valid; chan_capture
    puts the marker into the FIFO one byte clock later, or two when the line's last word leaves
    word_packer in the same clock (a line of 4..1440 active bytes, a multiple of 4); the FIFO
    write is one more byte clock. The read side sees the Gray pointer after two system clock
    edges (the first edge strictly after the write), and mix_chan takes the marker at the next.
    A line arrives in the model at this edge (its time t, in system clock edges)."""
    n0 = -(-t_run // t_byte)                       # first falling edge at or after t_run
    collide = active_count % 4 == 0 and 4 <= active_count <= 4 * N_WORDS
    t_write = (n0 + 0.5 + k + 1 + 1 + (1 if collide else 0) + 1) * t_byte
    j = int((t_write + 1e-6) / t_sys - 0.5) + 1    # first edge (j + 0.5) t_sys after t_write
    while (j + 0.5) * t_sys <= t_write + 1e-6:
        j += 1
    while j > 0 and (j - 0.5) * t_sys > t_write + 1e-6:
        j -= 1
    return j + 2


def is_bad(rec, len_ntsc=1716, len_pal=1728, tol=2):
    length = min(rec.length, 4095)
    return rec.xy_bad != 0 or not (abs(length - len_ntsc) <= tol or abs(length - len_pal) <= tol)


def decide_pair(ea, eb, cur, bad_a=False, bad_b=False, blend_q8=38, switch_q8=64, weak_a=False, weak_b=False):
    """(use, new_cur) for a paired line; cur 0 = A, 1 = B."""
    if bad_a and not bad_b:
        return USE_B, 1
    if bad_b and not bad_a:
        return USE_A, 0
    if bad_a and bad_b:
        return (USE_B if cur else USE_A), cur
    if weak_a and not weak_b:
        return USE_B, 1
    if weak_b and not weak_a:
        return USE_A, 0
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


class _Line:
    __slots__ = ('rec', 't', 'bad', 'fc', 'peer_sick', 'self_well', 'weak')

    def __init__(self, rec, t, bad, fc, peer_sick, self_well, weak=False):
        self.rec, self.t, self.bad, self.fc = rec, t, bad, fc
        self.peer_sick, self.self_well, self.weak = peer_sick, self_well, weak


class Mixer:
    """Feed completed line records with their arrival times: push(ch, rec, t_ns), in time
    order, then finish(). Read `trace` [(use, pop, field, line)] and `out` [(field, line,
    idx, data)].

    ext_bad: per channel either a bool (held for the whole run) or a function t_ns -> bool
    (decoder status "no lock", sampled when a line arrives).
    ext_weak: the same form (RSSI warning, rssi_adc.v): a weak channel's arriving lines count
    as bad for its health (sick, self_well) and lose a pair against a good line of a channel
    that is not weak; the lines themselves are not bad (shown alone, never left out for it). keep_words=False skips `out`.
    omit_bad=False writes lines bad on both receivers like any other (the rule before 2026-10-08).
    `omitted` has one entry per decision: True where a line was left out by that rule.
    """

    def __init__(self, t_pair=T_PAIR_CYCLES * 15.4, n_step=8, n_dead=40, ext_bad=(False, False),
                 keep_words=True, omit_bad=True, ext_weak=(False, False), **kw):
        self.t_pair, self.n_step, self.n_dead = t_pair, n_step, n_dead
        self.ext_bad, self.keep_words, self.omit_bad = ext_bad, keep_words, omit_bad
        self.ext_weak = ext_weak
        self.kw = kw
        self.q = (deque(), deque())
        self.hist = ([], [])          # bad flags of the last 8 arrived lines
        self.fc = [0, 0]              # field counter (mod 4): advances when the line number restarts
        self.prev = [None, None]      # (field, line) of the last arrived line
        self.last_arr = [None, None]  # arrival time of the last line
        self.cur = 0
        self.step_valid = False       # a pair has happened
        self.since_pair = 0           # lone resolutions since the last pair (saturates at n_step)
        self.quiet = [0, 0]           # lone lines of the other channel since this one's last line
        self.qfast = [False, False]   # the channels were in step when this one went quiet
        self.o_valid = False          # output field state
        self.o_line = 0
        self.o_fbit = 1               # last visible tag; the first output field gets F = 0
        self.pending_field = False    # an admitted field boundary not yet carried by output words
        self.o_fc = [0, 0]
        self.join = [False, False]
        self.trace = []               # (use, pop, field, line)
        self.curs = []                # current channel after each decision
        self.omitted = []             # per decision: left out because it was bad on both receivers
        self.newfield = []            # per decision: the line started an output field
        self.out = []                 # (field, line, idx, data)
        self.overflow = False
        self.bad_last = False         # the last line shown (or left out) in this output field was bad on both
        self.adm_new = False          # the last admitted line started an output field
        self.pushed = [None, None]    # time of each channel's last line, and its `sick` before that line
        self.sick_before = [False, False]

    # ---- per-channel bookkeeping at arrival
    def _ext(self, ch, t, which=None):
        e = (which or self.ext_bad)[ch]
        return bool(e(t)) if callable(e) else bool(e)

    def _sick(self, ch):
        return len(self.hist[ch]) == 8 and all(self.hist[ch])

    def _well(self, ch):
        return len(self.hist[ch]) == 8 and not any(self.hist[ch])

    def push(self, ch, rec, t):
        """Two lines at the same time (the same clock edge in the RTL): each sees the other's
        health as it was before that edge (mix_chan registers `sick`)."""
        self._advance(t)
        # a line with fewer than 360 whole words (late SAV, short active part) is incomplete: it
        # counts as bad for health, is not stored and is not a delivered line for the other
        # channel's gap fill
        complete = rec.active_count >= 4 * N_WORDS
        bad = is_bad(rec, **self.kw) or self._ext(ch, t) or not complete
        peer_sick = self.sick_before[1 - ch] if self.pushed[1 - ch] == t else self._sick(1 - ch)
        self.sick_before[ch], self.pushed[ch] = self._sick(ch), t
        weak = self._ext(ch, t, self.ext_weak)
        h = self.hist[ch]
        h.append(bad or weak)                                 # weak RSSI counts against health
        del h[:-8]
        p = self.prev[ch]
        if p is not None and (rec.line_in_field <= p[1] or rec.field != p[0]):
            self.fc[ch] = (self.fc[ch] + 1) & 3
        self.prev[ch] = (rec.field, rec.line_in_field)
        if complete:
            self.last_arr[ch] = t
        if len(self.q[ch]) == 4:
            self.overflow = True       # (the RTL also drops a line whose words were partly lost)
            return
        if not complete:
            return
        self.q[ch].append(_Line(rec, t, bad, self.fc[ch], peer_sick, self._well(ch), weak))
        self._pairs()

    def finish(self, t=float('inf')):
        """Resolve every line whose pairing window has closed by time t."""
        self._advance(t)

    # ---- resolution
    @property
    def in_step(self):
        return self.step_valid and self.since_pair < self.n_step

    def _pairs(self):
        qa, qb = self.q
        while (qa and qb and qa[0].rec.line_in_field == qb[0].rec.line_in_field
               and abs(qa[0].t - qb[0].t) < self.t_pair):
            self._pair()

    def _advance(self, t):
        """Lone lines whose window closed at or before t, oldest first (tie: A)."""
        while True:
            due = [(q[0].t + self.t_pair, ch) for ch, q in enumerate(self.q) if q and q[0].t + self.t_pair <= t]
            if not due:
                return
            self._solo(min(due)[1])
            self._pairs()

    def _admit(self, ch, e, owner, step, judge=None):
        """May this line leave now? Updates admission/join state when it may; the visible F tag
        is consumed later by _emit. judge: the channel whose field state decides, if not ch."""
        f, l = e.rec.field, e.rec.line_in_field
        jc, je = (ch, e) if judge is None else judge
        if not self.o_valid:
            ok = new = True
        elif self.join[jc]:
            if je.fc == self.o_fc[jc]:
                ok, new = l > self.o_line, False
            else:                                   # this channel has moved on to its next field
                ok = new = owner or step
        elif owner and not step:                    # the numbering owner changed out of step: start over
            ok = new = True
        else:
            ok, new = l > self.o_line, False
        if ok:
            self.adm_new = new
            if new:
                self.pending_field = True     # a boundary is consumed only by a visible line
                self.join = [False, False]
            self.o_valid, self.o_line = True, l
            self.join[ch] = True
            self.o_fc[ch] = e.fc
        return ok

    def _next_fbit(self):
        """Tag a line with the pending synthetic boundary, without consuming it yet."""
        return self.o_fbit ^ self.pending_field

    def _omit(self, show, both_bad):
        """Is this shown line left out as bad on both receivers? Call after _admit."""
        if not show:
            return False
        prev = False if self.adm_new else self.bad_last
        self.bad_last = both_bad
        return self.omit_bad and both_bad and not prev

    def _emit(self, use, pop, field, line, omitted=False, new=False):
        if omitted:
            use = USE_NONE
        if use:
            self.o_fbit = field
            self.pending_field = False
        self.trace.append((use, pop, field, line))
        self.newfield.append(new)
        self.curs.append(self.cur)
        self.omitted.append(omitted)
        qa, qb = self.q
        if use and self.keep_words:
            if use == USE_BLEND:
                ws = blend_words(words(qa[0].rec.active), words(qb[0].rec.active))
            else:
                ws = words((qa if use == USE_A else qb)[0].rec.active)
            self.out += [(field, line, i, w) for i, w in enumerate(ws)]
        if pop & 1:
            qa.popleft()
        if pop & 2:
            qb.popleft()

    def _pair(self):
        a, b = self.q[0][0], self.q[1][0]
        use, self.cur = decide_pair(a.rec.hf_energy, b.rec.hf_energy, self.cur, a.bad, b.bad,
                                    weak_a=a.weak, weak_b=b.weak)
        own, other = (a, b)[self.cur], 1 - self.cur
        # a current channel with no line in this output field (the other one carried it) is judged
        # on the partner's field counter: both lines carry the same number
        judge = (other, (a, b)[other]) if not self.join[self.cur] and self.join[other] else None
        show = self._admit(self.cur, own, owner=True, step=True, judge=judge)
        if show:
            other = 1 - self.cur
            self.join[other] = True
            self.o_fc[other] = (a, b)[other].fc
            field = self._next_fbit()
        else:
            use, field = USE_NONE, own.rec.field
        omitted = self._omit(show, a.bad and b.bad)
        self.step_valid, self.since_pair = True, 0
        self.quiet = [0, 0]
        self._emit(use, 0b11, field, own.rec.line_in_field, omitted, show and self.adm_new)

    def _solo(self, x):
        e, other = self.q[x][0], 1 - x
        step = self.in_step                          # as it was before this line
        # silence and health of the current channel, seen from a lone line of the other one
        if x != self.cur:
            q = min(self.quiet[self.cur] + 1, self.n_dead)
            fast = self.qfast[self.cur] if self.quiet[self.cur] else step
            dead = q >= self.n_dead or (fast and q >= self.n_step)
            if dead or (e.peer_sick and e.self_well):
                self.cur = x
        owner = x == self.cur
        # gap fill: the other channel (the current one when this matters) delivered nothing
        # within T_PAIR of this line; anything it delivers later comes after this resolution
        p_last = self.last_arr[other]
        gap_ok = step and not e.bad and (p_last is None or p_last <= e.t - self.t_pair)
        show = (owner or gap_ok) and self._admit(x, e, owner, step)
        omitted = self._omit(show, e.bad)              # lone: the other receiver has no such line
        # counters
        if self.quiet[other] == 0:
            self.qfast[other] = step
        self.quiet[other] = min(self.quiet[other] + 1, self.n_dead)
        self.quiet[x] = 0
        self.since_pair = min(self.since_pair + 1, self.n_step)
        self._emit((USE_B if x else USE_A) if show else USE_NONE, 0b10 if x else 0b01,
                   self._next_fbit() if show else e.rec.field, e.rec.line_in_field,
                   omitted, show and self.adm_new)
