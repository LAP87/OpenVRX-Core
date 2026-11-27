"""Model-only NTSC colour experiment for Core #27 on the six-bit, 40 MHz C5 bus.

The integer decoder uses a burst-referenced NCO, a 1H comb and a 32-sample
chroma boxcar. It receives the original capture model's actual line/active
signals and replaces only Cb/Cr in its emitted words. No RTL is supplied or
claimed bit-exact with this proposal.

The synthetic source uses the draft's stated polar Cb/Cr convention: amplitude
CHROMA_FRAC*(white-blank) times the normalized Cb/Cr vector, phase atan2(Cr,Cb)
plus pi. This isolates inverse-map, phase and packing errors; it is not a
complete electrical NTSC transmitter, RF-channel or real-camera model.
Y/Cb/Cr truth uses one consistent set of full-level BT.601 RGB bars. Burst
amplitude defaults to one quarter of blank-sync; source clipping is counted.

Metrics use the actual packed entries at their sample clocks, after capture
lock, excluding four initial visible lines and bar edges. Decoded hue is
measured against known Cb/Cr; the loop-control phase is reported separately.
Gain calibration assumes the provided source scale; no automatic calibration
or physical colour-quality claim is made. Only existing gain tables 20/31 are
used. The 1H inverse uses the measured line-start delay, not an assumed 2542
samples on every line.

Pure stdlib; no FPGA, native simulator, PAL, physical HDMI or receiver test.
"""
import argparse
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cvbs_capture_ref as cv  # noqa: E402

FS = 40e6
FSC = 3579545.0                     # NTSC subcarrier, Hz
SPC = FS / FSC                      # samples per subcarrier cycle: 11.1746
FSC_INC = round(2**32 * FSC / FS)   # NCO increment per sample (32-bit accumulator)
PHASES = 256
COS_T = [round(127 * math.cos(2 * math.pi * p / PHASES)) for p in range(PHASES)]
SIN_T = [round(127 * math.sin(2 * math.pi * p / PHASES)) for p in range(PHASES)]

# burst window in samples after the line start: (202, 313) = 111 samples = 9.93 subcarrier cycles
# (~10 cycles). The capture's line-start events sit +-5 samples from the true pulse edge (the edge
# detector's lag), so a window of ~10 whole cycles averages the burst regardless of that jitter:
# a 40-sample (3.58-cycle) window left a ~31 deg RMS hue error, this one gets ~1.6 deg clean and
# ~4 deg at noise sigma 1. The window stays inside the back porch (5.05..7.8 us; active starts
# 9.04 us). Only normal-sync lines carry a burst; on equalizing/broad-pulse lines (the vertical
# interval) the window sees no burst and _burst_lock() skips it on the magnitude gate BURST_MIN.
BURST_LO, BURST_HI = 202, 313
BURST_CYCLES = 10
BURST_MIN = 60                      # fixed magnitude gate, not proof of colour lock under noise
# synth_colour scales the burst peak with sync depth; its default is not a fixed four codes.
LOOP_SHIFT = 4                      # phase-error IIR: err += (est - err) >> 4
# err is in 1/256-cycle units; closing a phase error over one line (63.5 us) needs
# delta_inc = err * 256 * 2^32/(FS * H_NOM) ~ err * 256 * 6621 accumulator units per sample
LOOP_GAIN = 6621 * 256              # inc = FSC_INC - (err * LOOP_GAIN) >> 8 (est > 0: NCO leads, slow it)
INC_CLAMP = 2_000_000               # about +-1.2 cycles of range
# chroma low-pass: boxcar over CHROMA_TAPS demodulated samples at 40 MS/s; 32 taps leaves 4.9 %
# of the 2*Fsc term, 16 taps would leave 22 %
CHROMA_TAPS = 32
# synth_colour puts a chroma subcarrier of amplitude CHROMA_FRAC*(white-blank) on the active part
CHROMA_FRAC = 0.35
# Nominal calibration only. line_start derives rotation and gain from the actual
# integer start-to-start delay, so both 2542 and 2543 clocks use the right axes.
# Nominal phase is about 172.83 degrees modulo full cycles at a 2542-clock delay.
# csub = 2*amp*sin(D_LINE/2)*cos(w*i + phi - D_LINE/2); demodulated on the subcarrier grid this
# leaves (i_lp, q_lp) = amp*sin(D_LINE/2)*(cos(phi-D_LINE/2), -sin(phi-D_LINE/2)). ROT_C8/ROT_S8
# are 127*cos/sin(D_LINE/2); the Cb/Cr correction in step() is the exact inverse map (see header).
D_LINE = 2 * math.pi * cv.H_NOM / SPC
ROT_C8 = round(127 * math.cos(D_LINE / 2))
ROT_S8 = round(127 * math.sin(D_LINE / 2))
COMB_RES = 2 * abs(math.sin(D_LINE / 2))        # comb chroma gain: 1.996 (not 2)
# burst discriminator without a divider (the RTL has none): est = (burst_i*INV_LUT[min(mag,255)])>>8
# approximates 256*burst_i/mag through a reciprocal ROM, INV_LUT[m] = round(65536/m). Worst relative
# error ~0.2% (at m=255); the shift-by-four IIR absorbs the rounding, the metrics are unchanged.
INV_LUT = [65535] + [min(65535, round(65536 / m)) for m in range(1, 256)]   # 16-bit ROM: m=1 clamps to 65535


def chroma_k(white_blank):
    """K for the Cb/Cr output so the synth's full-scale chroma maps to +-111 codes. The subcarrier
    amplitude in the sample is CHROMA_FRAC*(white-blank); the comb multiplies by 2*sin(D_LINE/2)
    and the demod's sin*cos average halves it, so |(i_lp, q_lp)| = amp*|sin(D_LINE/2)| with amp =
    CHROMA_FRAC*(white-blank). The inverse map in step() multiplies the 8-bit rotated vector
    (i*ROT_C8 + q*ROT_S8) by K >> 14, so K = 111*128*127 / (CHROMA_FRAC*(white-blank)*|sin(D_LINE/2)|)."""
    # sin(D_LINE/2) < 0, so keep the sign: K is negative, which with the minus signs in step()
    # gives the correct positive Cb/Cr excursion. Scale: step() computes
    # (i*ROT_C8 + q*ROT_S8)*K >> 14, i.e. (i*c + q*s)*127 * K/2^14, so K = 111*2^14/(127*amp*|s|)
    # with amp = CHROMA_FRAC*white_blank and s = sin(D_LINE/2).
    return round(111 * 16384 / (127 * CHROMA_FRAC * white_blank * math.sin(D_LINE / 2)))


K_CHROMA_STD = chroma_k(62 - 22)    # levels (4, 22, 62): white - blank = 40


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class ColourDemod:
    """Feed one 6-bit sample at a time with step(); call line_start() at every line start event
    (the same events cvbs_capture_ref.Capture produces, same start_at). step() returns
    (y, cb, cr) at every luma tick on an active line, else None."""

    def __init__(self, comb=True, white_x8=cv.WHITE_X8_STD, loop_shift=LOOP_SHIFT,
                 chroma_k=K_CHROMA_STD):
        self.comb = comb
        self.gain = cv.gain_table(white_x8)
        self.loop_shift = loop_shift
        self.k = chroma_k
        self.k_nominal = chroma_k
        self.rot_c8, self.rot_s8 = ROT_C8, ROT_S8
        self.phase = 0                  # 32-bit NCO phase, continuous across lines
        self.err = 0                    # filtered burst phase error, 1/256-cycle units
        self.inc = FSC_INC              # increment applied to the phase this sample
        self.inc_new = FSC_INC          # computed at the burst-lock sample, applied from the next
        self.n = 0
        self.line_start_at = None
        self.cur_active = False
        self.sync = cv.SYNC_INIT
        self.blank = cv.BLANK_INIT
        self.acc = 0
        self.ticks = 0
        self.y_count = 0
        self.last_y_tick = None
        self.last_pair_times = None
        self.y_prev = None
        self.hf = 0
        self.y = 16
        self.cb = 128
        self.cr = 128
        # burst window accumulators
        self.burst_i = self.burst_q = self.burst_n = 0
        # chroma boxcar (running sums)
        self.i_sum = self.q_sum = 0
        self.i_win = [0] * CHROMA_TAPS
        self.q_win = [0] * CHROMA_TAPS
        self.win_pos = 0
        # 1H comb memory
        self.prev_line = [0] * 4096
        self.cur_line_buf = [0] * 4096
        self.prev_active = False
        self.prev_len = 0
        # metrics
        self.burst_phase_err_deg = []   # per line with a burst, the filtered error in degrees

    def line_start(self, start_at, active, sync, blank):
        if self.line_start_at is not None:
            # The actual capture start-to-start delay is 2542 or 2543 (and can jitter).
            # Its 1H comb phase is not always the nominal 2542-sample phase.
            delay = start_at - self.line_start_at
            angle = 2 * math.pi * FSC * delay / FS / 2
            self.rot_c8 = round(127 * math.cos(angle))
            self.rot_s8 = round(127 * math.sin(angle))
            self.k = round(self.k_nominal * math.sin(D_LINE / 2) / math.sin(angle))
            # the line that just ended becomes the comb partner
            self.prev_line, self.cur_line_buf = self.cur_line_buf, self.prev_line
            self.prev_active = self.cur_active
            self.prev_len = self.n - self.line_start_at
        self.line_start_at = start_at
        self.cur_active = active
        self.sync = sync
        self.blank = blank
        self.acc = 0
        self.ticks = 0
        self.y_count = 0
        self.last_y_tick = None
        self.last_pair_times = None
        self.y_prev = None
        self.hf = 0
        self.burst_i = self.burst_q = self.burst_n = 0
        self.win_pos = 0

    def _burst_lock(self):
        """Once per line, at the end of the burst window: fold the measured burst vector into err.
        With the NCO at subcarrier phase + delta, the burst (at subcarrier phase + 180 deg)
        accumulates as burst_i ~ (A*N/2)*sin(delta): est ~ burst_i*256/mag is delta in 1/256-cycle
        units (a reciprocal ROM approximates the division; see INV_LUT). burst_i > 0 means the
        NCO leads the burst, so the increment must shrink (raising inc raises delta -- the other
        sign is positive feedback, verified by a phase scan)."""
        if not self.burst_n:
            return
        mag = abs(self.burst_i) + abs(self.burst_q) + 1
        if mag < BURST_MIN:
            return                  # no burst in the window (vertical-interval line): skip
        # reciprocal ROM instead of a divider: est = (burst_i * INV_LUT[min(mag,255)]) >> 8
        # approximates burst_i*256/mag (the RTL has no divider; the IIR absorbs the ~0.2% error)
        m8 = mag if mag < 256 else 255
        est = clamp((self.burst_i * INV_LUT[m8]) >> 8, -512, 512)
        # err is a 12-bit two's-complement register in the RTL: the difference est-err is formed
        # in 12 bits (it wraps when |est-err| >= 2048, which happens for large err), so emulate
        # that wrap here to stay bit-exact with rtl/colour_demod.v
        d = ((est & 0x7FF) | (0x800 if est < 0 else 0)) - (self.err & 0xFFF)
        dv = ((d & 0xFFF) ^ 0x800) - 0x800
        self.err = (self.err + ((dv >> self.loop_shift) & 0xFFF)) & 0xFFF
        # the RTL registers the new inc on the clock after the lock sample and applies it on the
        # clock after that; the model applies the new increment to the phase one sample after the
        # lock sample to stay bit-exact with rtl/colour_demod.v (see the inc pipeline at the end
        # of step()). The metrics only see the filtered err, which is unaffected by this shift.
        # err is 12-bit two's complement: read it back signed for the gain multiply and the metric
        err_s = (self.err ^ 0x800) - 0x800
        self.inc_new = clamp(FSC_INC - ((err_s * LOOP_GAIN) >> 8), FSC_INC - INC_CLAMP, FSC_INC + INC_CLAMP)
        self.burst_phase_err_deg.append(err_s * 360.0 / PHASES)

    def inverse_chroma(self, i_sum, q_sum):
        """Invert the 1H comb axis map without truncating the boxcar's fractional bits."""
        den = CHROMA_TAPS * 16384
        cb = (i_sum * self.rot_c8 + q_sum * self.rot_s8) * self.k
        cr = (i_sum * self.rot_s8 - q_sum * self.rot_c8) * self.k
        return (clamp(128 - (cb + den//2)//den, 1, 254),
                clamp(128 - (cr + den//2)//den, 1, 254))

    def step(self, s):
        """One sample. Returns (y, cb, cr) at a luma tick on an active line, else None."""
        ph8 = (self.phase >> 24) & 0xFF
        cos, sin = COS_T[ph8], SIN_T[ph8]
        out = None
        if self.line_start_at is not None:
            p = self.n - self.line_start_at
            if BURST_LO <= p < BURST_HI:
                # demodulate (s - blank): the blanking DC would otherwise leak ~blank*N/2/128
                # into the burst vector (the window is close to ten cycles, not an integer)
                sb = s - self.blank
                # round to nearest (floor shift is biased -0.5 per term: -20 over the 40-sample
                # window; keep symmetric rounding for negative products too)
                self.burst_i += (sb * cos + 64) >> 7
                self.burst_q += (sb * sin + 64) >> 7
                self.burst_n += 1
                if p == BURST_HI - 1:
                    self._burst_lock()
            if p < 4096:
                self.cur_line_buf[p] = s
            # chroma front end: the comb subtraction (chroma doubles, luma cancels); with comb off
            # the raw sample minus blanking (luma leaks in: the negative control)
            if self.comb:
                csub = s - self.prev_line[p] if (self.prev_active and p < 4096 and p < self.prev_len) else 0
            else:
                csub = s - self.blank
            i = (csub * cos + 64) >> 7
            q = (csub * sin + 64) >> 7
            self.i_sum += i - self.i_win[self.win_pos]
            self.q_sum += q - self.q_win[self.win_pos]
            self.i_win[self.win_pos] = i
            self.q_win[self.win_pos] = q
            self.win_pos = (self.win_pos + 1) % CHROMA_TAPS
            # luma tick, the same 27/80 NCO as the capture model
            self.acc += cv.NCO_INC
            if self.acc >= cv.NCO_MOD:
                self.acc -= cv.NCO_MOD
                self.ticks += 1
                if self.cur_active and p >= cv.ACT_START and self.y_count < 2 * cv.WORDS:
                    self.y_count += 1
                    if self.comb and self.prev_active and p < 4096 and p < self.prev_len:
                        c7 = s + self.prev_line[p]
                    else:
                        c7 = 2 * s
                    d7 = 2 * (self.blank - self.sync)
                    g = self.gain[clamp(d7, 0, 127)]
                    delta = c7 - 2 * self.blank
                    qq = (abs(delta) * g) >> 8
                    self.y = clamp(16 + qq if delta >= 0 else 16 - qq, 1, 254)
                    if self.y_prev is not None:
                        self.hf += abs(self.y - self.y_prev)
                    self.y_prev = self.y
                    if self.y_count % 2 == 0:    # chroma for this word, at its Y1 tick
                        # exact inverse of the comb/demod axis map (module header):
                        # Cb = 128 - (i_lp*ROT_C8 + q_lp*ROT_S8)*K >> 7
                        # Cr = 128 - (i_lp*ROT_S8 - q_lp*ROT_C8)*K >> 7
                        self.cb, self.cr = self.inverse_chroma(self.i_sum, self.q_sum)
                        self.last_pair_times = (self.last_y_tick, self.n)
                    self.last_y_tick = self.n
                    out = (self.y, self.cb, self.cr)
        self.phase = (self.phase + self.inc) & 0xFFFFFFFF
        # inc pipeline: the value _burst_lock wrote this sample applies from the next sample
        # (the RTL: inc is registered at the lock clock, the phase adds it from the next clock)
        self.inc = self.inc_new
        self.n += 1
        return out


def pack_words(pairs):
    """(y, cb, cr) stream at luma ticks -> 32-bit BT.656 words {Y1, Cr, Y0, Cb} like
    cvbs_capture_ref's word entries (chroma at the even tick of each pair, Cb in byte 0)."""
    words = []
    pend = None
    for y, cb, cr in pairs:
        if pend is None:
            pend = (y, cb, cr)
        else:
            words.append((y << 24) | (cr << 16) | (pend[0] << 8) | cb)
            pend = None
    return words


# ---- synthetic colour composite -----------------------------------------------------------------
def synth_colour(luma_fn, chroma_fn, lines=525, first_line=1, levels=(4, 22, 62),
                 burst_amp=None, noise=0.0, seed=1, phase_ramp=0.0, with_burst=True,
                 phase_offset=0.0, stats=None):
    """6-bit samples at 40 MS/s of `lines` consecutive NTSC lines starting at first_line.
    luma_fn(line, x) -> Y 16..235 for x 0..719; chroma_fn(line, x) -> (Cb, Cr), 128 +- 111.
    phase_ramp: burst phase added per line, degrees. noise: gaussian sigma in codes.
    levels: (sync, blank, white) in codes. Returns (samples, [(start, line_no)] line starts)."""
    sync_c, blank_c, white_c = levels
    if burst_amp is None:
        burst_amp = (blank_c - sync_c) / 4
    if stats is not None:
        stats.update(active_clipped=0, burst_amp=burst_amp)
    rnd = random.Random(seed)
    plan = cv.pulse_plan_525()
    out = []
    starts = []
    t = 0.0
    for k in range(lines):
        ln = (first_line - 1 + k) % 525 + 1
        pa, pb = plan[ln]
        start = int(round(t))
        end = int(round(t + cv.SAMPLES_PER_LINE))
        starts.append((start, ln))
        line = [blank_c] * (end - start)
        # the subcarrier phase is continuous in the absolute sample index (phase(i) =
        # 2*pi*i/SPC + phi): 2542 samples between line starts is 227.48 cycles, so the
        # line-to-line inversion is 172.8 deg, not exactly 180 -- the 1H comb then leaves
        # 2*cos(pi*0.0199) ~ 12.5 % of the subcarrier in the luma, which is the honest number
        # at 40 MS/s (a real NTSC line is 227.5 cycles; the 0.22-sample remainder is the
        # quantisation of the 40 MS/s grid, present on the bench too). No per-line phase base.

        def put(lo, w):
            for i in range(lo, min(lo + w, end)):
                if i - start >= 0:
                    line[i - start] = sync_c

        if pa == 'n':
            put(start, cv.SYNC_W)
        elif pa == 'e':
            put(start, cv.EQ_W)
        elif pa == 'b':
            put(start, cv.BROAD_W)
        if pb == 'e':
            put(int(round(t + cv.SAMPLES_PER_LINE / 2)), cv.EQ_W)
        elif pb == 'b':
            put(int(round(t + cv.SAMPLES_PER_LINE / 2)), cv.BROAD_W)
        if with_burst and pa == 'n':
            # the burst replaces the back porch it occupies (a real burst rides on the blanking
            # level there); in the vertical interval there is no burst, and writing it over a
            # broad pulse would serrate that pulse and the capture would not see a vertical sync
            b_lo = start + BURST_LO
            b_hi = min(start + BURST_HI, end)
            for i in range(b_lo, b_hi):
                ph = 2 * math.pi * i / SPC + math.pi + math.radians(phase_ramp * k + phase_offset)
                line[i - start] = clamp(int(round(blank_c + burst_amp * math.sin(ph))), 0, 63)
        if cv.active_525(ln):
            # per-sample subcarrier phase (absolute sample index; continuous across lines). Writing
            # per x with a held value would freeze the phase for ~3 samples and the demod would see a
            # different (x-dependent) phase -- a real VTX does not do that.
            for i in range(cv.ACT_START, min(cv.ACT_START + cv.ACTIVE_W, len(line))):
                if BURST_HI <= i:               # the burst window was replaced above; leave it
                    x = min(int((i - cv.ACT_START) * 13.5 / 40), 719)
                    yv = clamp(luma_fn(ln, x), 16, 235)
                    cbv, crv = chroma_fn(ln, x)
                    base = blank_c + (yv - 16) * (white_c - blank_c) / 219.0
                    amp = CHROMA_FRAC * (white_c - blank_c) * math.hypot((cbv - 128) / 111.0,
                                                                         (crv - 128) / 111.0)
                    phi = math.atan2(crv - 128, cbv - 128) + math.pi
                    ph = 2 * math.pi * (start + i) / SPC + phi + math.radians(phase_offset)
                    raw = int(round(base + amp * math.sin(ph)))
                    if stats is not None and not 0 <= raw <= 63:
                        stats['active_clipped'] += 1
                    line[i] = clamp(raw, 0, 63)
        if noise:
            line = [clamp(int(round(v + rnd.gauss(0, noise))), 0, 63) for v in line]
        out.extend(line)
        t += cv.SAMPLES_PER_LINE
    return out, starts


COLOUR_BARS = [(235, 128, 128), (210, 16, 146), (170, 166, 16), (145, 54, 34),
               (106, 202, 222), (81, 90, 240), (41, 240, 110), (16, 128, 128)]


def colour_bars_luma(ln, x):
    """Y from the same full-level BT.601 bars as colour_bars_chroma."""
    return COLOUR_BARS[min(x * 8 // 720, 7)][0]


def colour_bars_chroma(ln, x):
    """White, yellow, cyan, green, magenta, red, blue, black; limited-range BT.601."""
    return COLOUR_BARS[min(x * 8 // 720, 7)][1:]


# ---- metrics ------------------------------------------------------------------------------------
def capture_events(samples, comb=True, white_x8=None, levels=(4, 22, 62)):
    """Run cvbs_capture_ref.Capture over the samples and return (cap, events): events maps the
    sample index of each line-start event to (start_at, active, sync, blank), with active taken
    from _finish_line (the capture only decides cur_active at ACT_CHECK, after the start event).
    white_x8 defaults to the table matching `levels` (same convention as run_frame)."""
    cap, events, _ = drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels)
    return cap, events


def gain_for_levels(levels):
    """Select an existing RTL table; do not invent an unsupported white_x8=18."""
    return cv.WHITE_X8_C5VRX if levels in ((23, 31, 62), (13, 25, 50)) else cv.WHITE_X8_STD


def drive_capture(samples, comb=True, white_x8=None, levels=(23, 31, 62), demod=None,
                  on_entry=None, events=None):
    """Drive the decoder from live capture state, including the unfinished last line.

    A start event resets the chroma NCO's luma-tick divider on the same sample
    as Capture. Its active flag follows Capture when ACT_CHECK decides it;
    there is no look-ahead to _finish_line and no second replay of the signal.
    """
    white_x8 = gain_for_levels(levels) if white_x8 is None else white_x8
    if white_x8 not in cv.GAIN:
        raise ValueError('only the existing gain tables 20 and 31 are supported')
    cap = cv.Capture(comb=comb, white_x8=white_x8)
    starts = {}
    orig_s, orig_f = cap._start_line, cap._finish_line

    def wrapped_s(start_at, flywheel, edge):
        orig_s(start_at, flywheel, edge)
        starts[cap.n] = [start_at, False, cap.sync, cap.blank]
        if demod is not None:
            demod.line_start(start_at, False, cap.sync, cap.blank)

    def wrapped_f(flywheel_next):
        active = cap.cur_active
        orig_f(flywheel_next)
        if starts:
            starts[max(starts)][1] = active

    cap._start_line, cap._finish_line = wrapped_s, wrapped_f
    for s in samples:
        n0 = len(cap.entries)
        cap.step(s)
        if demod is not None:
            demod.cur_active = cap.cur_active
            demod.step(s)
        if on_entry is not None:
            for e in cap.entries[n0:]:
                on_entry(e)
    if starts:
        starts[max(starts)][1] = cap.cur_active
    return cap, {n: tuple(e) for n, e in starts.items()}, demod


def replace_chroma(word, cb, cr):
    """Replace both bytes, including bit 7 of Cb; preserve the two original Y bytes."""
    return (word & 0xFF00FF00) | (cr << 16) | cb


def _decode(samples, comb=True, levels=(23, 31, 62), white_x8=None, chroma_k=None):
    white_x8 = gain_for_levels(levels) if white_x8 is None else white_x8
    k = globals()['chroma_k'](levels[2]-levels[1]) if chroma_k is None else chroma_k
    dem = ColourDemod(comb=comb, white_x8=white_x8, chroma_k=k)
    entries, times = [], []

    def on_entry(e):
        if e[0] == 'word':
            assert dem.y_count == 2*(e[3]+1) and dem.last_pair_times is not None, 'stale chroma'
            data = replace_chroma(e[4], dem.cb, dem.cr)
            entries.append((*e[:4], data))
            times.append(dem.last_pair_times)
        else:
            entries.append(e)

    cap, _, _ = drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels,
                              demod=dem, on_entry=on_entry)
    return entries, cap, dem, times


def expected_colour_entries(samples, comb=True, levels=(23, 31, 62), white_x8=None,
                            chroma_k=None):
    """Model proposal entries: original Y/markers with freshly decoded Cr and Cb."""
    return _decode(samples, comb, levels, white_x8, chroma_k)[0]


def run_frame(luma_fn=colour_bars_luma, chroma_fn=colour_bars_chroma, lines=360, first_line=1,
              noise=0.0, seed=1, phase_ramp=0.0, comb=True, levels=(23, 31, 62),
              with_burst=True, hue_skip=4, white_x8=None, phase_offset=0.0, chroma_k_override=None):
    """Measure actual packed entries at central bar pixels after four visible lines.

    Full-level Y/Cb/Cr truth is independent of the recovered capture numbering.
    Loop-control phase is not the decoded-hue metric. Empty output has no numeric
    quality score (None), so a lost field cannot pass an accuracy assertion.
    """
    import bisect
    stats = {}
    samples, starts = synth_colour(luma_fn, chroma_fn, lines=lines, first_line=first_line,
                                   noise=noise, seed=seed, phase_ramp=phase_ramp, levels=levels,
                                   with_burst=with_burst, phase_offset=phase_offset, stats=stats)
    entries, cap, dem, times = _decode(samples, comb, levels, white_x8, chroma_k_override)
    words = [e for e in entries if e[0] == 'word']
    starts_at = [s[0] for s in starts]
    sums = [[] for _ in range(8)]
    ys, cbs, crs = [], [], []
    for e, (t0, t1) in zip(words, times):
        data = e[4]
        y0, y1, cb, cr = data>>8&255, data>>24, data&255, data>>16&255
        ys.extend((y0, y1)); cbs.extend((cb, cb)); crs.extend((cr, cr))
        if e[2] < hue_skip:
            continue
        si = bisect.bisect_right(starts_at, t1)-1
        start, ln = starts[si]
        x1 = int((t1-start-cv.ACT_START)*13.5/40)
        x0 = int((t0-start-cv.ACT_START)*13.5/40)
        if not 0 <= x0 <= x1 < 720 or not 30 <= x1%90 < 60:
            continue
        ty0, ty1 = luma_fn(ln, x0), luma_fn(ln, x1)
        tcb, tcr = chroma_fn(ln, x1)
        sums[x1//90].append((y0, y1, cb, cr, ty0, ty1, tcb, tcr))
    bar_metrics, chroma_sq, y_sq, hue_sq = [], [], [], []
    for i, rows in enumerate(sums):
        if not rows:
            bar_metrics.append(dict(bar=i, count=0)); continue
        n = len(rows)
        mean_cb = sum(r[2] for r in rows)/n
        mean_cr = sum(r[3] for r in rows)/n
        tcb, tcr = rows[0][6:8]
        err = math.hypot(mean_cb-tcb, mean_cr-tcr)
        hue_error = None
        if (tcb, tcr) != (128, 128):
            hue_error = math.degrees(math.atan2(mean_cr-128, mean_cb-128)-math.atan2(tcr-128, tcb-128))
            hue_error = (hue_error+180)%360-180
        for y0, y1, cb, cr, ty0, ty1, tcb, tcr in rows:
            y_sq.extend(((y0-ty0)**2, (y1-ty1)**2))
            chroma_sq.extend(((cb-tcb)**2, (cr-tcr)**2))
            if (tcb, tcr) != (128, 128):
                d = math.degrees(math.atan2(cr-128, cb-128)-math.atan2(tcr-128, tcb-128))
                hue_sq.append(((d+180)%360-180)**2)
        bar_metrics.append(dict(bar=i, count=n, mean_y=sum((r[0]+r[1])/2 for r in rows)/n,
                                truth_y=(rows[0][4]+rows[0][5])/2, truth_cb=tcb, truth_cr=tcr,
                                mean_cb=mean_cb, mean_cr=mean_cr, vector_error=err, hue_error_deg=hue_error))
    markers = [e for e in entries if e[0] == 'marker']
    good = sum(not e[4] for e in markers)
    rms = lambda v: math.sqrt(sum(v)/len(v)) if v else None
    y_rms = rms(y_sq)
    burst = dem.burst_phase_err_deg[hue_skip:]
    clean_target = bool(all(b['count'] for b in bar_metrics)
                        and all(b['vector_error'] <= 16 for b in bar_metrics)
                        and all(abs(b['hue_error_deg']) <= 10 for b in bar_metrics
                                if b['hue_error_deg'] is not None)) if noise == 0 else None
    return dict(clean_target_pass=clean_target, levels=list(levels), noise=noise, seed=seed, lines=lines,
                white_x8=gain_for_levels(levels) if white_x8 is None else white_x8,
                words=len(words), demod_samples=2*len(words), markers=len(markers),
                first_lock_sample=next((n for n, v in cap.lock_trace if v), None),
                lock_trace=cap.lock_trace, sync_hits=good/len(markers) if markers else None,
                luma_snr_db=20*math.log10(219/max(y_rms,1e-9)) if y_rms is not None else None,
                chroma_rms=rms(chroma_sq), hue_rms_deg=rms(hue_sq),
                burst_phase_rms_deg=rms([x*x for x in burst]), burst_lines=len(dem.burst_phase_err_deg),
                bars=bar_metrics, clipping=stats,
                max_mean_vector_error=max((b['vector_error'] for b in bar_metrics if b['count']), default=None),
                max_mean_hue_error_deg=max((abs(b['hue_error_deg']) for b in bar_metrics
                                            if b['count'] and b['hue_error_deg'] is not None), default=None),
                y=ys, cb=cbs, cr=crs)




def table(lines=360):
    """The two measured source scales x noise 0/1/2/3, with explicit quality status."""
    print('levels noise words chromaRMS decodedHueRMS maxMeanVector maxMeanHue cleanTarget')
    rows = []
    for levels in [(23, 31, 62), (13, 25, 50)]:
        for noise in [0, 1, 2, 3]:
            r = run_frame(lines=lines, levels=levels, noise=noise, white_x8=31)
            row = {k:v for k,v in r.items() if k not in ('y', 'cb', 'cr')}
            rows.append(row)
            print(levels, noise, r['words'], r['chroma_rms'], r['hue_rms_deg'],
                  r['max_mean_vector_error'], r['max_mean_hue_error_deg'], r['clean_target_pass'], flush=True)
    return rows


if __name__ == '__main__':
    import json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lines', type=int, default=360)
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    if args.json is not None and args.json.exists():
        ap.error('refusing to overwrite existing metrics')
    rows = table(args.lines)
    if args.json is not None:
        args.json.write_text(json.dumps(dict(schema=1, model_only=True, cases=rows), indent=2)+'\n')
