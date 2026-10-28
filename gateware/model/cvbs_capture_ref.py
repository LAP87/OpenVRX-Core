"""Reference for rtl/cvbs_capture.v: 6-bit composite video samples at 40 MS/s in (the C5VRX
receiver's PARLIO bus), the mixer's 53-bit entries out, with the same meaning as chan_capture.v
gives them for a TVP5150 (hub docs/design/2026-10-24/DIGITAL_INGANG.md).

The algorithm, integer only, bit for bit what the RTL does:

* Levels. Per line the sync tip (mean of 32 samples inside the pulse) and the back porch (mean of
  32 samples just before the active part) are measured; running estimates follow them with a
  shift-by-two IIR. The slicer sits halfway between them. Until a line has been measured the slicer sweeps
  (BOOT_*), and the first measured line counts only if it looks like a sync and a porch around the swept slicer
  (BOOT_DMIN, BOOT_KMIN); otherwise the lock drops and the sweep steps on.
* Sync. A sample below the slicer is `low`. Three low samples in a row start a pulse (its start is
  the first of the three), three high ones end it. Width < T_EQ is an equalizing pulse, width
  >= T_BROAD a broad (serration) pulse, in between a line sync.
* Line starts. Free running: any pulse start whose width reaches T_EQ is a line start; the second
  start within H_NOM +- H_TOL of the first locks. Locked: the next start is the first pulse start
  within +- WIN of last_start + hp; none by then and the line starts there anyway (`flywheel`,
  the line counts as bad); MISS_MAX flywheel lines in a row unlock. hp follows the measured
  period with a shift-by-four IIR.
* Vertical. The first broad pulse at a line start (after at least one line that was not broad)
  toggles the field and arms a countdown of V_LINES line starts; the active line numbering
  restarts at 0 when it reaches zero. A line is active when the countdown has reached zero,
  its pulse was not an equalizing pulse, and the signal is high again ACT_CHECK samples after the
  start (a broad pulse is still low there). That reproduces BT.656's V bit on a TVP5150
  (lines 20-263 and 283-525 active, hub design note).
* Resampling. A phase accumulator adds NCO_INC per sample and emits a luma sample every NCO_MOD
  (27/80 = 13.5/40). It restarts at every line start. The active part begins ACT_START samples
  after the line start (9.04 us, BT.601) and gives at most 720 luma samples = 360 words.
* Luma. COMB: the sample is added to the previous line's sample at the same position (a 1H comb,
  the NTSC subcarrier inverts every line); otherwise the sample is doubled. Y = 16 + ((c7 -
  2 blank) * G) >> 8 with G = round(219 * 256 / (2.5 * 2 d)) from a table over d = blank - sync,
  clamped to 1..254. Cb = Cr = 128.
* Entries. Word {0, field, line, idx, Y1 80 Y0 80}; after the line's last word, at the next line
  start, the marker {1, field, line, hf, bad, 0, length, 0} with hf = sum |Y[n] - Y[n-1]| over the
  line's luma samples, bad = 1 for a flywheel start, length = 2 * luma ticks of the line (the
  BT.656 byte count the mixer checks: 1716 +- 2 for NTSC).

synth() makes test streams: NTSC geometry (525 lines, 2542.22 samples per line), sync, blanking,
no burst yet (colour is task 65), active luma from a function of (line, x), optional noise and
faults. Everything stays in the stdlib.
"""
import json
import random
import sys
from pathlib import Path

# ---- parameters (shared with the RTL) ----------------------------------------------------------
H_NOM = 2542        # nominal line period in samples at 40 MS/s (63.556 us)
H_TOL = 128         # free-running lock window
WIN = 64            # locked: accept a pulse start this far from the prediction
MISS_MAX = 3        # flywheel lines before unlocking (a phase jump re-locks within two more lines)
LEN_INC, LEN_MOD = 27, 40   # free-running byte-tick NCO for the marker's length (27 MHz-equivalent)
T_EQ = 140          # pulse width below this: equalizing (2.3 us = 92; line sync 4.7 us = 188)
T_BROAD = 600       # pulse width from this: broad (27.1 us = 1084)
ACT_CHECK = 300     # samples after the start where a line sync has ended and a broad pulse has not
ACT_START = 362     # first active luma sample, 9.04 us after the sync edge (BT.601 525/60)
V_LINES = 16        # line starts from the first broad pulse to the first active line (4 -> 20, 267 -> 283)
NCO_INC, NCO_MOD = 27, 80
WORDS = 360
SYNC_WIN = (88, 120)    # samples after the start averaged for the sync tip: inside the 188-sample pulse for an
                        # edge anywhere within +- WIN of the predicted start, and after the start event (pos WIN)
PLL_SHIFT = 4           # locked: the next predicted start moves round((edge - prediction) / 16) toward the edge:
                        # at most one sample per line for edges within +- 23, so the length stays within the
                        # mixer's 2 ticks (3 samples); / 8 moved up to 3 samples and rounded to 3 ticks
HP_SHIFT = 6            # the period estimate: hp_acc (hp times 64) += edge period - hp, no dead zone; seeded with
                        # the locking period, so a PAL-length line needs no slow walk from H_NOM
PORCH_WIN = (320, 352)  # samples after the start averaged for the back porch (after the burst, before active)
SYNC_INIT, BLANK_INIT = 4, 20
# Bootstrap (bench 2026-10-27): the slicer sweeps one code every BOOT_STEP samples while unlocked, from
# (SYNC_INIT + BLANK_INIT) / 2 up to BOOT_MAX and round from BOOT_MIN, until a line with a real sync has been
# measured; then the measured levels replace the estimates at once. C5VRX puts its sync at 23 and the blanking
# at 31 codes, where a slicer of 12 never saw a pulse (hub docs/bench, 2026-10-27).
BOOT_STEP = 2 * H_NOM
BOOT_MIN, BOOT_MAX = 8, 40
# The first measured line must look like a sync and a porch around the slicer that found it: sync mean below the
# slicer, porch mean at or above it, and at least BOOT_DMIN codes between them. Otherwise the lock is dropped and the
# slicer steps on at once (bench 2026-10-28: with the slicer at or above the blanking level the sweep locked on the
# dark picture's period and measured 24/24, 25/25 or 32/39 where the sync sat at 13, then stayed "locked" with
# no usable line; 80 of 337 locks over the day's captures). And the sync mean must lie within BOOT_KMIN codes of the
# line's lowest slicer average: a real sync tip is the lowest level of its line, while a lock on a dark part of the
# picture (slicer above the blanking, 32/39 with the sync at 14) measures something well above it.
BOOT_DMIN = 4
BOOT_KMIN = 4
# The slicer sees the sum of the AVG samples before the current one against AVG times the level (bench
# 2026-10-27: the C5VRX sync tip carries +-8 codes of noise; the first-three-low-samples edge then wandered up to
# 32 samples from line to line, the mixer refused the lengths and the picture jumped; an 8-sample average keeps
# the periods within 3). The current sample is left out so that the RTL compares a registered sum.
AVG = 8


def gain_table(white_x8=20):
    """G for d7 = 2 (blank - sync) in 0..127: round(219 * 256 / (R * d7)), 0 where d7 < 2, with R = white_x8 / 8
    the source's white-to-blanking swing over its blanking-to-sync swing: 2.5 (20/8) for standard composite
    (100 over 40 IRE), 31/8 for C5VRX's bus (white 62, blanking 31, sync 23 measured 2026-10-27), where the
    standard table clipped everything above code 51 to white."""
    return [0 if d7 < 2 else min(4095, (219 * 256 * 8 * 2 + white_x8 * d7) // (2 * white_x8 * d7)) for d7 in range(128)]


WHITE_X8_STD, WHITE_X8_C5VRX = 20, 31
GAIN = {WHITE_X8_STD: gain_table(WHITE_X8_STD), WHITE_X8_C5VRX: gain_table(WHITE_X8_C5VRX)}


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Capture:
    """Feed samples one at a time with step(); entries collect in .entries as
    ('word', field, line, idx, data32) and ('marker', field, line, hf, bad, length)."""

    def __init__(self, comb=True, avg=AVG, white_x8=WHITE_X8_STD, boot_check=True):
        self.comb = comb
        self.avg = avg
        self.boot_check = boot_check   # False: the first measured line is taken as it is (before 2026-10-28; tests)
        self.gain = GAIN[white_x8] if white_x8 in GAIN else gain_table(white_x8)
        self.window = [0] * avg      # the last avg samples, zeros before the first
        self.win_sum = 0
        self.entries = []
        self.n = 0
        self.sync16, self.blank16 = SYNC_INIT << 4, BLANK_INIT << 4   # level estimates in 1/16 codes
        self.levels_fresh = False    # the estimates come from a measured line (else the slicer sweeps)
        self.boot_slice = (SYNC_INIT + BLANK_INIT) >> 1
        self.boot_cnt = 0
        self.boot_rejects = 0        # first measured lines refused (BOOT_DMIN, BOOT_KMIN), for the tests
        self.line_min = (1 << 16) - 1   # the lowest slicer sum (win_sum) since the line start
        self.low_run = self.high_run = 0
        self.in_pulse = False
        self.pulse_start = 0
        self.pulse_width = 0
        self.locked = False
        self.lock_trace = []         # (sample index, locked) at every change: the RTL's `lock` (task 69)
        self._lock_prev = False
        self.have_start = False
        self.last_start = 0
        self.hp = H_NOM
        self.hp_acc = H_NOM << HP_SHIFT
        self.miss = 0
        # locked: the line starts at the prediction (+ WIN, like a flywheel start), the accepted edge only
        # nudges the next prediction and feeds the period estimate (bench 2026-10-27: edge jitter of up to
        # 32 samples made the mixer refuse the lengths)
        self.pred = 0                # the next predicted start
        self.last_edge = 0           # the last accepted edge: the period estimate runs edge to edge
        self.prev_had_edge = False   # the line before the pending one had an edge: last_edge is one line back
        self.pend_edge = None        # the edge accepted for the pending line, and its pulse's class so far
        self.pend_eq = True
        self.pend_broad = False
        self.cur_edge = None         # the current line's accepted edge (free running: its start)
        self.field = 0
        self.countdown = -1          # -1: no vertical sync seen yet
        self.seen_normal = True      # armed: the next broad pulse at a line start is a vertical sync
        self.line_no = 0
        self.numbered = False        # numbering restarted at least once
        self.acc_len = 0             # free-running 27/40 NCO: byte ticks for the marker's length
        self.len_ticks = 0
        self.prev_active = False     # the previous line was active: its samples are a valid comb partner
        self.prev_len = 0            # ... up to this position (a short line leaves stale samples beyond it)
        # per-line state
        self.pos = -1                # samples since the line start, -1 before the first start
        self.cur_active = False
        self.cur_bad = False
        self.cur_line = 0
        self.cur_field = 0
        self.acc = 0
        self.ticks = 0
        self.y_count = 0
        self.y_prev = None
        self.hf = 0
        self.y_pending = None
        self.sync_sum = self.porch_sum = 0
        self.pulse_was_broad = False
        self.pulse_was_eq = True
        self.prev_line = [0] * 4096  # 1H comb memory, indexed by position in the line
        self.cur_line_buf = [0] * 4096
        self.have_prev_line = False
        self.start_pending = None
        self.active_decided = False

    # -- helpers -------------------------------------------------------------------------------
    @property
    def sync(self):
        return self.sync16 >> 4

    @property
    def blank(self):
        return self.blank16 >> 4

    def _finish_line(self, flywheel_next):
        """The line that ends now: its marker (if active) and the level updates."""
        if self.pos >= 0:
            if self.pos >= PORCH_WIN[1] and not self.cur_bad and not self.pulse_was_eq:
                # a real line sync or broad pulse lies under the sync window; the porch window is
                # clean only after a line sync (a broad pulse is still low there)
                # 32-sample means in 1/16 codes: sum >> 5 << 4 = sum >> 1; shift-by-two IIR (floor);
                # the first measured line replaces the bootstrap estimates outright, if it passes the check
                if not self.levels_fresh:
                    sync_m16, porch_m16, slice16 = self.sync_sum >> 1, self.porch_sum >> 1, self.boot_slice << 4
                    if self.pulse_was_broad:
                        self.sync16 = sync_m16
                    elif not self.boot_check or (
                            sync_m16 < slice16 <= porch_m16 and porch_m16 - sync_m16 >= BOOT_DMIN << 4
                            and sync_m16 * self.avg <= (self.line_min << 4) + (BOOT_KMIN << 4) * self.avg):
                        self.sync16, self.blank16 = sync_m16, porch_m16
                        self.levels_fresh = True
                    else:
                        # not a sync and a porch around this slicer: drop the lock, sweep on from the next code
                        self.locked = False
                        self.boot_slice = BOOT_MIN if self.boot_slice >= BOOT_MAX else self.boot_slice + 1
                        self.boot_cnt = 0
                        self.boot_rejects += 1
                else:
                    self.sync16 += ((self.sync_sum >> 1) - self.sync16) >> 2
                    if not self.pulse_was_broad:
                        self.blank16 += ((self.porch_sum >> 1) - self.blank16) >> 2
            if self.cur_active:
                self.entries.append(('marker', self.cur_field, self.cur_line, self.hf, int(self.cur_bad),
                                     min(self.len_ticks, 4095)))
        self.prev_line, self.cur_line_buf = self.cur_line_buf, self.prev_line
        self.prev_active = self.cur_active
        self.prev_len = self.pos if self.pos >= 0 else 0      # the comb partner exists below this position
        self.have_prev_line = self.pos >= 0

    def _start_line(self, start_at, flywheel, edge):
        """A line starts at start_at; edge is its accepted sync edge (None: a flywheel line, no edge within
        WIN of the prediction). The pending pulse's class becomes the line's."""
        self._finish_line(flywheel)
        self.last_start = start_at
        self.have_start = True
        self.pos = self.n - start_at          # samples already past the start (the 3-sample detector lags)
        self.cur_bad = flywheel
        self.acc = 0
        self.ticks = 0
        self.len_ticks = 0
        self.y_count = 0
        self.y_prev = None
        self.hf = 0
        self.y_pending = None
        self.sync_sum = self.porch_sum = 0
        self.active_decided = False
        self.cur_active = False
        self.cur_edge = edge
        self.pulse_was_broad = self.pend_broad
        self.pulse_was_eq = self.pend_eq if edge is not None else False   # a real pulse counts as equalizing
        self.pend_edge, self.pend_eq, self.pend_broad = None, True, False   # until its width reaches T_EQ
        if flywheel:
            self.miss += 1
            if self.miss > MISS_MAX:
                self.locked = False
                self.have_start = False
                self.levels_fresh = False    # the next signal may sit at other levels: sweep again
        else:
            self.miss = 0

    def _line_class_update(self, width_so_far, pending):
        """Called every sample while the accepted pulse of the current line (pending False) or of the pending
        line (pending True: accepted before the start event) lasts."""
        if pending:
            if width_so_far >= T_EQ:
                self.pend_eq = False
            if width_so_far >= T_BROAD:
                self.pend_broad = True
            return
        if width_so_far >= T_EQ:
            self.pulse_was_eq = False
        if width_so_far >= T_BROAD and not self.pulse_was_broad:
            self.pulse_was_broad = True
            if self.seen_normal:
                # first broad pulse at a line start since a non-broad line: vertical sync
                self.field ^= 1
                self.countdown = V_LINES
                self.seen_normal = False

    def step(self, s):
        """One 6-bit sample."""
        # byte ticks at 27 MHz-equivalent, free running: the marker's length is the ticks per line
        self.acc_len += LEN_INC
        if self.acc_len >= LEN_MOD:
            self.acc_len -= LEN_MOD
            self.len_ticks += 1
        locked_before = self.locked
        slice_level = (self.sync + self.blank) >> 1 if self.levels_fresh else self.boot_slice
        # the slicer on the moving sum of the avg samples before this one (the RTL keeps that sum in a register,
        # so no adder sits in front of the comparison); then this sample enters the window
        ws = self.win_sum
        low = ws < slice_level * self.avg
        self.win_sum += s - self.window[self.n % self.avg]
        self.window[self.n % self.avg] = s
        if low:
            self.low_run = min(self.low_run + 1, 3)
            self.high_run = 0
        else:
            self.high_run = min(self.high_run + 1, 3)
            self.low_run = 0
        edge = False
        if not self.in_pulse and self.low_run == 3:
            self.in_pulse = True
            self.pulse_start = self.n - 2
            self.pulse_width = 3
            edge = True
        elif self.in_pulse:
            if self.high_run == 3:
                self.in_pulse = False
            else:
                self.pulse_width += 1

        # -- line starts ---------------------------------------------------------------------
        started = False
        if edge:
            if self.locked:
                # the first edge within WIN of the prediction is the line's: it nudges the next prediction
                # and carries the period estimate (edge to edge); the line itself starts at the prediction
                if self.pend_edge is None and abs(self.pulse_start - self.pred) <= WIN:
                    self.pend_edge = self.pulse_start
                    if self.prev_had_edge:       # else last_edge is more than a line back: no period
                        period = self.pulse_start - self.last_edge
                        self.hp_acc = clamp(self.hp_acc + (period - self.hp),
                                            (H_NOM - H_TOL) << HP_SHIFT, (H_NOM + H_TOL) << HP_SHIFT)
                        self.hp = (self.hp_acc + (1 << (HP_SHIFT - 1))) >> HP_SHIFT
                    self.last_edge = self.pulse_start
            elif self.have_start:
                # free running: pulses closer than a line (equalizing and broad pulses at half
                # lines, noise) are not line starts; a line period locks
                period = self.pulse_start - self.last_start
                if period >= H_NOM - H_TOL:
                    # a line period locks, when the pulse that started the line was a real sync (width
                    # >= T_EQ): noise crossing the swept slicer makes edges a line apart, not such pulses
                    self.locked = period <= H_NOM + H_TOL and not self.pulse_was_eq
                    self._start_line(self.pulse_start, False, self.pulse_start)
                    started = True
                    if self.locked:
                        self.last_edge = self.pulse_start
                        self.prev_had_edge = True
                        self.hp = period                          # the locking period seeds the estimate
                        self.hp_acc = period << HP_SHIFT
                        self.pred = self.pulse_start + self.hp
            else:
                self._start_line(self.pulse_start, False, self.pulse_start)
                started = True
        if self.locked and not started and self.n == self.pred + WIN:
            # the start event, WIN samples after the prediction: with or without an edge (flywheel)
            had_edge, err = self.pend_edge is not None, (self.pend_edge or 0) - self.pred
            self._start_line(self.pred, not had_edge, self.pend_edge)
            started = True
            self.prev_had_edge = had_edge
            if self.locked:       # the start may have dropped the lock (MISS_MAX flywheel lines)
                self.pred += self.hp + (((err + (1 << (PLL_SHIFT - 1))) >> PLL_SHIFT) if had_edge else 0)
        # the line's lowest slicer sum: the ending line's was read by _finish_line above, the new line starts with
        # this sample's
        self.line_min = ws if started else min(self.line_min, ws)

        # -- within the line ----------------------------------------------------------------
        if self.pos >= 0:
            if not started:
                self.pos += 1
            p = self.pos
            # the accepted pulse of this line, or of the pending one (a flywheel start has no pulse: eq stays
            # False)
            if self.in_pulse and self.cur_edge is not None and self.pulse_start == self.cur_edge:
                self._line_class_update(self.pulse_width, False)
            elif self.in_pulse and self.pend_edge is not None and self.pulse_start == self.pend_edge:
                self._line_class_update(self.pulse_width, True)
            if SYNC_WIN[0] <= p < SYNC_WIN[1]:
                self.sync_sum += s
            if PORCH_WIN[0] <= p < PORCH_WIN[1]:
                self.porch_sum += s
            if p == ACT_CHECK and not self.active_decided:
                self.active_decided = True
                broad_now = low
                if not broad_now and not self.pulse_was_eq:
                    self.seen_normal = True
                if self.countdown > 0:
                    self.countdown -= 1
                    if self.countdown == 0:
                        self.line_no = 0
                        self.numbered = True
                        self.cur_active = True
                    else:
                        self.cur_active = False
                elif self.countdown == 0 and self.numbered:
                    self.cur_active = not self.pulse_was_eq and not broad_now
                    if self.cur_active:
                        self.line_no += 1
                else:
                    self.cur_active = False
                if self.cur_active:
                    self.cur_line = self.line_no
                    self.cur_field = self.field
                if self.pulse_was_eq and self.countdown == 0:
                    pass
            if p < 4096:
                self.cur_line_buf[p] = s
            # luma ticks
            self.acc += NCO_INC
            if self.acc >= NCO_MOD:
                self.acc -= NCO_MOD
                self.ticks += 1
                if self.cur_active and p >= ACT_START and self.y_count < 2 * WORDS:
                    use_prev = self.comb and self.prev_active and p < 4096 and p < self.prev_len
                    c7 = s + (self.prev_line[p] if use_prev else s)
                    d7 = 2 * (self.blank - self.sync)
                    g = self.gain[clamp(d7, 0, 127)]
                    delta = c7 - 2 * self.blank
                    q = (abs(delta) * g) >> 8            # magnitude first: truncation toward zero, as the RTL
                    y = clamp(16 + q if delta >= 0 else 16 - q, 1, 254)
                    if self.y_prev is not None:
                        self.hf += abs(y - self.y_prev)
                    self.y_prev = y
                    if self.y_count & 1:
                        data = (y << 24) | (0x80 << 16) | (self.y_pending << 8) | 0x80
                        self.entries.append(('word', self.cur_field, self.cur_line, self.y_count >> 1, data))
                    else:
                        self.y_pending = y
                    self.y_count += 1
        # the slicer sweep while unlocked (the lock state at the start of this sample, as the RTL's register)
        if locked_before:
            self.boot_cnt = 0
        else:
            self.boot_cnt += 1
            if self.boot_cnt == BOOT_STEP:
                self.boot_cnt = 0
                self.boot_slice = BOOT_MIN if self.boot_slice >= BOOT_MAX else self.boot_slice + 1
        if self.locked != self._lock_prev:
            self.lock_trace.append((self.n, self.locked))
            self._lock_prev = self.locked
        self.n += 1

    def run(self, samples):
        for s in samples:
            self.step(s)
        return self.entries


# ---- synthetic composite ------------------------------------------------------------------------
SAMPLES_PER_LINE = 2542.2222        # 63.5556 us at 40 MS/s
SYNC_W = 188                        # 4.7 us
EQ_W = 92                           # 2.3 us
BROAD_W = int(SAMPLES_PER_LINE / 2) - SYNC_W   # 27.1 us
ACTIVE_W = 2133                     # 53.33 us


def pulse_plan_525():
    """(line 1..525) -> pulses at 0H and 0.5H: 'n' normal sync, 'e' equalizing, 'b' broad, '-' none."""
    plan = {}
    for ln in range(1, 526):
        a = b = '-'
        if 1 <= ln <= 3 or 7 <= ln <= 9:
            a = b = 'e'
        elif 4 <= ln <= 6:
            a = b = 'b'
        elif ln == 263:
            a, b = 'n', 'e'
        elif 264 <= ln <= 265:
            a = b = 'e'
        elif ln == 266:
            a, b = 'e', 'b'
        elif 267 <= ln <= 268:
            a = b = 'b'
        elif ln == 269:
            a, b = 'b', 'e'
        elif 270 <= ln <= 271:
            a = b = 'e'
        elif ln == 272:
            a, b = 'e', '-'
        else:
            a = 'n'
        plan[ln] = (a, b)
    return plan


def active_525(ln):
    return 20 <= ln <= 263 or 283 <= ln <= 525


def synth(luma_fn, frames=1, levels=(4, 22, 62), noise=0.0, seed=1, faults=None, first_line=1):
    """Samples (list of ints 0..63) of `frames` 525-line frames. luma_fn(line, x) -> 0..255 luma
    (16 black .. 235 white) for x in 0..719. levels = (sync, blank, white) in codes. faults: dict
    line -> 'nosync' (the line's sync pulse is missing) or 'short' (the next line starts 300
    samples early)."""
    sync_c, blank_c, white_c = levels
    rnd = random.Random(seed)
    plan = pulse_plan_525()
    faults = faults or {}
    out = []
    t = 0.0           # exact time in samples of the current line start
    lines = [(f, ln) for f in range(frames) for ln in range(first_line, 526)]
    for k, (f, ln) in enumerate(lines):
        pa, pb = plan[ln]
        fault = faults.get(ln + 525 * f)
        length = SAMPLES_PER_LINE - (300 if fault == 'short' else 0)
        start = int(round(t))
        end = int(round(t + length))
        half = int(round(t + SAMPLES_PER_LINE / 2))
        line = [blank_c] * (end - start)

        def put(lo, w):
            for i in range(lo, min(lo + w, end)):
                if i - start >= 0:
                    line[i - start] = sync_c

        if pa == 'n' and fault != 'nosync':
            put(start, SYNC_W)
        elif pa == 'e':
            put(start, EQ_W)
        elif pa == 'b':
            put(start, BROAD_W)
        if pb == 'e':
            put(half, EQ_W)
        elif pb == 'b':
            put(half, BROAD_W)
        if active_525(ln):
            for x in range(720):
                i = int(round(ACT_START + x * (40.0 / 13.5)))
                if i < len(line):
                    yv = clamp(luma_fn(ln, x), 16, 235)
                    line[i] = blank_c + ((yv - 16) * (white_c - blank_c) + 109) // 219
            # hold each luma sample until the next one (zero-order hold at 13.5 MS/s)
            last = None
            for i in range(ACT_START, min(ACT_START + ACTIVE_W, len(line))):
                if line[i] != blank_c or last is None:
                    last = line[i]
                else:
                    line[i] = last
        if noise:
            line = [clamp(int(round(v + rnd.gauss(0, noise))), 0, 63) for v in line]
        out.extend(line)
        t += length
    return out


def bars(ln, x):
    """Eight grey bars, a BT.601 ramp would hide ordering faults; bars show them."""
    return 16 + (x * 8 // 720) * 31


def expected_entries(samples, comb=True, avg=AVG, white_x8=WHITE_X8_STD):
    return Capture(comb=comb, avg=avg, white_x8=white_x8).run(samples)


def expected_lock_trace(samples, comb=True, avg=AVG, white_x8=WHITE_X8_STD):
    """(sample index, locked) at every change of the line flywheel's lock."""
    c = Capture(comb=comb, avg=avg, white_x8=white_x8)
    c.run(samples)
    return c.lock_trace


def write_hex(path, samples):
    Path(path).write_text('\n'.join(f'{s:02x}' for s in samples) + '\n')


def gain_vh(white_x8=WHITE_X8_STD):
    """The case arms of rtl/cvbs_gain.vh (white_x8 20) or rtl/cvbs_gain_c5.vh (31): the gain table as the RTL
    function gain_of sees it."""
    return ''.join(f"                7'd{d7}: gain_of = 12'd{g};\n" for d7, g in enumerate(gain_table(white_x8)))


def write_gain_vh(path, white_x8=WHITE_X8_STD):
    Path(path).write_text('// Generated by gateware/model/cvbs_capture_ref.py (write_gain_vh); do not edit.\n'
                          f'// G = round(219 * 256 / ({white_x8}/8 * d7)) for d7 = 2 (blank - sync), 0 below d7 = 2 '
                          f'(WHITE_X8 = {white_x8}).\n' + gain_vh(white_x8))


def entries_json(entries):
    return json.dumps([list(e) for e in entries])


if __name__ == '__main__':
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('cvbs_demo')
    s = synth(bars, frames=1)
    write_hex(out.with_suffix('.hex'), s)
    ent = expected_entries(s)
    out.with_suffix('.expected.json').write_text(entries_json(ent))
    words = sum(1 for e in ent if e[0] == 'word')
    markers = [e for e in ent if e[0] == 'marker']
    print(f'{len(s)} samples, {words} words, {len(markers)} markers; lines {markers[0][2]}..{markers[-1][2]}')
