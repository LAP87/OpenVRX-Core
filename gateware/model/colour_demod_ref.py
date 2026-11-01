"""Reference model for task 65: NTSC colour demodulation in the FPGA, on the same 6-bit composite
samples at 40 MS/s that cvbs_capture_ref.py feeds the luma path (the C5VRX PARLIO bus).

Why not the usual 4xFsc trick: 40 MS/s is 11.1746 samples per subcarrier cycle, not 4. The plan
(hub docs/ARBETSPLAN.md task 65) is therefore a per-line burst-phase NCO at 3.579545 MHz, a 1H
comb, and Cb/Cr at 4:2:2. This model is the integer reference for that RTL: bit for bit what a
fixed-point implementation does, so sim testbenches can compare against it word for word, like
cvbs_capture_ref.py for the luma path.

Chain, all integer, all at 40 MS/s:

* 1H comb (shared by luma and chroma, as in cvbs_capture_ref): with the previous active line's
  sample prev[p] at the same position p, luma uses c7 = s + prev[p] (the subcarrier inverts every
  line -- 227.5 Fsc cycles per line -- so it cancels), chroma uses csub = s - prev[p] (luma
  cancels, chroma doubles). With comb off, luma doubles the sample and chroma demodulates the
  raw sample minus blanking, so luma leaks into chroma (the negative control).
* Burst lock. The burst sits in the back porch, samples BURST_LO..BURST_HI after the line start,
  at subcarrier phase 180 deg. Over that window the model accumulates the burst vector against the
  running NCO: with the NCO at subcarrier phase + delta, burst_i ~ (A*N/2)*sin(delta) (the
  double-frequency terms average out over the 9 burst cycles), so est ~ 256*burst_i/mag is delta
  in 1/256-cycle units. est > 0 means the NCO leads the burst, so the increment must shrink:
  inc = FSC_INC - err*LOOP_GAIN/256, with err the shift-by-four IIR of est (LOOP_GAIN =
  256 * 2^32/(FS*H_NOM) ~ 6621*256 closes one line's phase error in about one line), clamped.
  (The sign was verified against a phase scan: burst_i > 0 for delta > 0, and raising inc raises
  delta -- the other sign is positive feedback and wanders.) All multipliers round ((x + 64) >> 7,
  an arithmetic floor shift, unbiased for both signs); floor truncation would bias the burst
  vector by -0.5 per sample = -20 over the 40-sample window and park the loop ~15 deg off.
  The NCO phase runs continuously, never reset at line starts, so every burst re-anchors it; a
  constant burst-phase offset of the source only shifts the NCO's free phase, never the
  demodulated hue.
* Chroma demod. Every sample is multiplied by the NCO's cos/sin (8-bit tables, phase = top 8 bits
  of the 32-bit accumulator): i = (csub*cos + 64) >> 7, q = (csub*sin + 64) >> 7. The 2*Fsc term
  this leaves is removed by a CHROMA_TAPS boxcar on i and q (running sums, one add and one
  subtract per sample; 32 taps at 40 MS/s nulls at k*1.25 MHz and leaves 4.9 % of 2*Fsc), and one
  Cb/Cr pair is emitted every second luma tick (the 27/80 NCO of cvbs_capture_ref, 13.5 MS/s ->
  6.75 MHz chroma, 4:2:2). Axis convention: with the burst at 180 deg and the synth putting chroma
  at phi = atan2(Cr-128, Cb-128) + pi on subcarrier phase w*i, the 1H comb output is
  csub = 2*amp*sin(d/2)*cos(w*i + phi - d/2) where d = 2*pi*2542/SPC = 172.83 deg is the subcarrier
  phase step over one line (2542 samples = 227.48 cycles, not 227.5 -- the honest 40 MS/s grid).
  Demodulating against the NCO (= the subcarrier grid, delta = 0) leaves the DC vector
  (i_lp, q_lp) = amp*sin(d/2)*(cos(phi - d/2), -sin(phi - d/2)). With c = cos(d/2), s = sin(d/2)
  the exact inverse map (derived analytically, verified to <0.3 codes on all eight bars) is
  Cb = 128 + K*(-c*i_lp - s*q_lp) and Cr = 128 + K*(-s*i_lp + c*q_lp), i.e.
  Cb = 128 - (i_lp*ROT_C8 + q_lp*ROT_S8)*K >> 7 and
  Cr = 128 - (i_lp*ROT_S8 - q_lp*ROT_C8)*K >> 7 with ROT_C8 = 127*cos(d/2), ROT_S8 = 127*sin(d/2)
  and K = 111*16384/(127*CHROMA_FRAC*(white-blank)*|sin(d/2)|) so full-scale chroma maps to +-111
  codes (see chroma_k(); in the RTL the equivalent calibration comes from the measured burst
  amplitude, the only on-signal reference). The imperfect comb also leaves 2*cos(d/2) = 12.5 % of
  the subcarrier in the combed luma -- present on the bench too.
* Luma. Y = 16 + ((c7 - 2*blank) * G) >> 8 with the same gain table as cvbs_capture_ref
  (magnitude first, truncation toward zero, as the RTL).

The word layout matches what the mixer and fb_display expect: a 32-bit word {Y1, Cr, Y0, Cb}
(rtl/fb_display.v reads Y from [31:24]/[15:8], Cr from [23:16], Cb from [7:0]; cvbs_capture_ref's
luma word packs Y1 into [31:24], Y0 into [15:8] and 0x80 into the chroma bytes). pack_words()
assembles the (y, cb, cr) stream into those words.

Metrics (the plan asks for colour bars, colour error and phase noise):
  luma SNR  : 219 (the 16..235 range) over the RMS luma error against the truth, in dB
  hue RMS   : RMS of the per-line filtered burst phase error over the frame's later lines, degrees
  chroma RMS: RMS error of (Cb, Cr) against the truth on colour bars, in 8-bit units
  sync hits : fraction of markers that are not bad, from cvbs_capture_ref.Capture

synth_colour() makes test streams: NTSC geometry as cvbs_capture_ref.synth plus a 9-cycle burst
at 180 deg in the back porch and a subcarrier on the active part, with luma_fn(line, x) -> Y and
chroma_fn(line, x) -> (Cb, Cr), optional gaussian noise in codes and a per-line burst phase ramp
in degrees (a wandering-hue source, as the bench saw from C5VRX on 2026-10-22).

Negative controls live in sim/test_colour_demod.py: comb off leaves luma in the chroma, a burst
phase ramp degrades the hue metric monotonically, noise degrades chroma RMS monotonically, and
a burst-less source leaves the NCO free-running (large hue RMS).

Not modelled: PAL, channel differential gain/phase, and pre-emphasis. Everything stays in the
stdlib.

    .venv/bin/python gateware/model/colour_demod_ref.py            # the metrics table
    .venv/bin/python gateware/model/colour_demod_ref.py --noise 3 --phase-ramp 2
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
BURST_MIN = 60                      # burst vector magnitude gate: a real burst measures ~210,
                                    # VBI garbage ~15, so 60 separates them
# burst amplitude in codes in synth_colour: +-10 IRE at levels (4, 22, 62), where 100 IRE =
# white - blank = 40 codes, so 0.4 codes per IRE -> +-4 codes. (An earlier 40 codes = +-100 IRE
# clipped below the sync tip on the 6-bit bus and the capture saw the burst as a broad pulse.)
BURST_AMP = 4
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
# 1H comb geometry: the subcarrier phase step over one line (H_NOM samples) is
# D_LINE = 2*pi*H_NOM/SPC = 172.83 deg (not 180: 2542 samples = 227.48 cycles). The comb output is
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

    def step(self, s):
        """One sample. Returns (y, cb, cr) at a luma tick on an active line, else None."""
        ph8 = (self.phase >> 24) & 0xFF
        cos, sin = COS_T[ph8], SIN_T[ph8]
        out = None
        if self.line_start_at is not None:
            p = self.n - self.line_start_at
            if BURST_LO <= p < BURST_HI:
                # demodulate (s - blank): the blanking DC would otherwise leak ~blank*N/2/128
                # into the burst vector (the window is 3.58 cycles, not an integer)
                sb = s - self.blank
                # round to nearest (floor shift is biased -0.5 per term: -20 over the 40-sample
                # window, which would park the loop ~15 deg off burst phase)
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
                if self.cur_active and p >= cv.ACT_START and self.ticks <= 2 * cv.WORDS:
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
                    if self.ticks % 2 == 0:    # 4:2:2: one chroma pair per two luma samples
                        i_lp = self.i_sum // CHROMA_TAPS
                        q_lp = self.q_sum // CHROMA_TAPS
                        # exact inverse of the comb/demod axis map (module header):
                        # Cb = 128 - (i_lp*ROT_C8 + q_lp*ROT_S8)*K >> 7
                        # Cr = 128 - (i_lp*ROT_S8 - q_lp*ROT_C8)*K >> 7
                        self.cb = clamp(128 - (((i_lp * ROT_C8 + q_lp * ROT_S8) * self.k) >> 14), 1, 254)
                        self.cr = clamp(128 - (((i_lp * ROT_S8 - q_lp * ROT_C8) * self.k) >> 14), 1, 254)
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
            words.append((y << 24) | (cr << 16) | (pend[0] << 8) | pend[1])
            pend = None
    return words


# ---- synthetic colour composite -----------------------------------------------------------------
def synth_colour(luma_fn, chroma_fn, lines=525, first_line=1, levels=(4, 22, 62),
                 burst_amp=BURST_AMP, noise=0.0, seed=1, phase_ramp=0.0, with_burst=True):
    """6-bit samples at 40 MS/s of `lines` consecutive NTSC lines starting at first_line.
    luma_fn(line, x) -> Y 16..235 for x 0..719; chroma_fn(line, x) -> (Cb, Cr), 128 +- 111.
    phase_ramp: burst phase added per line, degrees. noise: gaussian sigma in codes.
    levels: (sync, blank, white) in codes. Returns (samples, [(start, line_no)] line starts)."""
    sync_c, blank_c, white_c = levels
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
                ph = 2 * math.pi * i / SPC + math.pi + math.radians(phase_ramp * k)
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
                    ph = 2 * math.pi * (start + i) / SPC + phi
                    line[i] = clamp(int(round(base + amp * math.sin(ph))), 0, 63)
        if noise:
            line = [clamp(int(round(v + rnd.gauss(0, noise))), 0, 63) for v in line]
        out.extend(line)
        t += cv.SAMPLES_PER_LINE
    return out, starts


def colour_bars_chroma(ln, x):
    """Eight bars: white, yellow, cyan, green, magenta, red, blue, black (BT.601 Cb/Cr)."""
    bars = [(235, 128, 128), (235, 16, 146), (179, 166, 16), (150, 54, 34),
            (106, 202, 222), (63, 192, 240), (32, 90, 240), (16, 128, 128)]
    _y, cb, cr = bars[min(x * 8 // 720, 7)]
    return cb, cr


# ---- metrics ------------------------------------------------------------------------------------
def capture_events(samples, comb=True, white_x8=None, levels=(4, 22, 62)):
    """Run cvbs_capture_ref.Capture over the samples and return (cap, events): events maps the
    sample index of each line-start event to (start_at, active, sync, blank), with active taken
    from _finish_line (the capture only decides cur_active at ACT_CHECK, after the start event).
    white_x8 defaults to the table matching `levels` (same convention as run_frame)."""
    cap, events, _ = drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels)
    return cap, events


def drive_capture(samples, comb=True, white_x8=None, levels=(4, 22, 62), demod=None,
                  on_entry=None, events=None):
    """Run a fresh cvbs_capture_ref.Capture over the samples, recording the line-start events
    (start_at, active, sync, blank) at their sample index. The capture only decides cur_active
    at the line's end (_finish_line, at the next start), so the events are complete only after
    the run: with events=None this is pass 1, which just collects them. With precomputed events
    (pass 2), a ColourDemod given as `demod` is driven in lockstep -- line_start before its step
    at the event's sample -- and on_entry(e) is called with every entry the capture emits, after
    the demod has stepped the same sample. Returns (cap, events, demod)."""
    if white_x8 is None:
        white_x8 = round(8 * (levels[2] - levels[1]) / (levels[1] - levels[0]))
    cap = cv.Capture(comb=comb, white_x8=white_x8)
    if events is None:
        starts = {}
        orig_s, orig_f = cap._start_line, cap._finish_line

        def wrapped_s(start_at, flywheel, edge):
            orig_s(start_at, flywheel, edge)
            starts[cap.n] = [start_at, None, cap.sync, cap.blank]

        def wrapped_f(flywheel_next):
            active = cap.cur_active
            orig_f(flywheel_next)
            if starts:
                starts[max(starts)][1] = active

        cap._start_line = wrapped_s
        cap._finish_line = wrapped_f
        for s in samples:
            cap.step(s)
        events = {n: (ev[0], bool(ev[1]), ev[2], ev[3]) for n, ev in starts.items()}
    else:
        for i, s in enumerate(samples):
            if demod is not None and i in events:
                st, act, sync, blank = events[i]
                demod.line_start(st, act, sync, blank)
            n0 = len(cap.entries)
            cap.step(s)
            if demod is not None:
                demod.step(s)
            if on_entry is not None:
                for e in cap.entries[n0:]:
                    on_entry(e)
    return cap, events, demod


def expected_colour_entries(samples, comb=True, levels=(4, 22, 62), white_x8=None,
                            chroma_k=None):
    """The mixer entries rtl/cvbs_capture.v with COLOUR=1 emits for these samples: the capture's
    own entries (words and markers, in order) with each word's chroma bytes [23:16]/[7:0] filled
    from ColourDemod (Cr/Cb at the word's tick, 4:2:2) instead of 0x80. Bit-for-bit the target of
    sim/test_colour_demod_rtl.py, like cvbs_capture_ref.expected_entries is for test_cvbs_capture."""
    if white_x8 is None:
        white_x8 = round(8 * (levels[2] - levels[1]) / (levels[1] - levels[0]))
    if chroma_k is None:
        chroma_k = globals()['chroma_k'](levels[2] - levels[1])
    _, events, _ = drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels)
    dem = ColourDemod(comb=comb, white_x8=white_x8, chroma_k=chroma_k)
    entries = []

    def on_entry(e):
        if e[0] == 'word':
            # the capture emits the word at the tick with odd y_count; the demod updated cb/cr
            # at that same tick (its even ticks), so they pair with Y1
            data = (e[4] & 0xFF00FFFF) | (dem.cr << 16) | dem.cb
            entries.append(('word', e[1], e[2], e[3], data))
        else:
            entries.append(e)

    drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels, demod=dem,
                  on_entry=on_entry, events=events)
    return entries


def run_frame(luma_fn=cv.bars, chroma_fn=colour_bars_chroma, lines=120, first_line=1,
              noise=0.0, seed=1, phase_ramp=0.0, comb=True, levels=(4, 22, 62),
              with_burst=True, hue_skip=10, white_x8=None):
    """Synthesize `lines` lines (from first_line=1, so the vertical interval arms the capture's
    active-line counting), run cvbs_capture_ref.Capture for the line-start events and levels,
    drive ColourDemod from those events, and measure against the truth.

    Returns a dict: luma_snr_db, hue_rms_deg (RMS over lines after hue_skip), chroma_rms,
    sync_hits (fraction of markers not bad), markers, burst_lines, demod_samples, and the raw
    y/cb/cr lists.
    """
    samples, starts = synth_colour(luma_fn, chroma_fn, lines=lines, first_line=first_line,
                                   noise=noise, seed=seed, phase_ramp=phase_ramp, levels=levels,
                                   with_burst=with_burst)
    # the gain table must match the synth levels: R = (white-blank)/(blank-sync) = white_x8/8.
    # levels (4, 22, 62) give R = 40/18 = 2.22 -> white_x8 = round(8*40/18) = 18; the default
    # WHITE_X8_STD (20) assumes standard composite levels (sync 4, blank 22, white 67) which clip
    # on the 6-bit bus, so the synth's 62 is used with its own table (same convention as
    # test_cvbs_capture's C5VRX case: levels (23, 31, 62) with white_x8 31).
    if white_x8 is None:
        white_x8 = round(8 * (levels[2] - levels[1]) / (levels[1] - levels[0]))
    cap, events, _ = drive_capture(samples, comb=comb, white_x8=white_x8, levels=levels)
    dem = ColourDemod(comb=comb, white_x8=white_x8, chroma_k=chroma_k(levels[2] - levels[1]))
    ys, cbs, crs, tick_abs = [], [], [], []
    for i, s in enumerate(samples):
        if i in events:
            start_at, active, sync, blank = events[i]
            dem.line_start(start_at, active, sync, blank)
        r = dem.step(s)
        if r is not None:
            ys.append(r[0])
            cbs.append(r[1])
            crs.append(r[2])
            tick_abs.append(i)       # absolute sample index of the tick
    # the line each tick belongs to: the latest synth line start <= the tick's sample index
    line_of_tick = []
    si = 0
    for i in tick_abs:
        while si < len(starts) and i >= starts[si][0]:
            si += 1
        line_of_tick.append(si)      # 1-based index into starts
    # truth per emitted tick from the ABSOLUTE sample index: x = (i - line_start - ACT_START)*13.5/40
    # (the synth now writes the subcarrier per sample at the absolute index, so this is exact)
    truth_y, truth_cb, truth_cr = [], [], []
    for k, i in zip(line_of_tick, tick_abs):
        ln = starts[k - 1][1] if 0 < k <= len(starts) else 1
        lstart = starts[k - 1][0] if 0 < k <= len(starts) else 0
        x = min(int((i - lstart - cv.ACT_START) * 13.5 / 40), 719)
        truth_y.append(clamp(luma_fn(ln, x), 16, 235))
        cbv, crv = chroma_fn(ln, x)
        truth_cb.append(cbv)
        truth_cr.append(crv)
    n = min(len(ys), len(truth_y))
    if n:
        rms = math.sqrt(sum((ys[i] - truth_y[i]) ** 2 for i in range(n)) / n)
        luma_snr = 20 * math.log10(219.0 / max(rms, 1e-9))
    else:
        luma_snr = 0.0
    # chroma at 4:2:2: compare each even-tick pair against the mean of its two truth positions
    cerr = []
    for i in range(0, n - 1, 2):
        cerr.append(cbs[i] - (truth_cb[i] + truth_cb[i + 1]) / 2)
        cerr.append(crs[i] - (truth_cr[i] + truth_cr[i + 1]) / 2)
    crms = math.sqrt(sum(e * e for e in cerr) / len(cerr)) if cerr else 0.0
    hue = dem.burst_phase_err_deg[hue_skip:]
    hue_rms = math.sqrt(sum(e * e for e in hue) / len(hue)) if hue else 0.0
    markers = [e for e in cap.entries if e[0] == 'marker']
    hits = sum(1 for m in markers if not m[4]) / len(markers) if markers else 0.0
    return {'luma_snr_db': luma_snr, 'hue_rms_deg': hue_rms, 'chroma_rms': crms,
            'sync_hits': hits, 'markers': len(markers), 'burst_lines': len(dem.burst_phase_err_deg),
            'demod_samples': n, 'y': ys, 'cb': cbs, 'cr': crs}



def lut_vh():
    """The case arms of the three rtl/colour_luts_*.vh includes: the 8-bit cos/sin tables (phase =
    top 8 bits of the 32-bit NCO accumulator, values biased by +128) and the 256-entry reciprocal
    ROM INV_LUT (est = burst_i*INV_LUT[m]>>8 ~ 256*burst_i/m), as the RTL functions cos_of/sin_of/
    inv_of see them. sim/test_colour_demod_rtl.py checks the files against this."""
    cos = [f"                8'd{p}: cos_of = 8'sd{c + 128};" for p, c in enumerate(COS_T)]
    sin = [f"                8'd{p}: sin_of = 8'sd{s + 128};" for p, s in enumerate(SIN_T)]
    inv = [f"                8'd{m}: inv_of = 16'd{v};" for m, v in enumerate(INV_LUT)]
    head = '// Generated by gateware/model/colour_demod_ref.py (lut_vh); do not edit.\n'
    return {'colour_luts_cos.vh': head + '// cos(2*pi*p/256), +-127, biased +128.\n' + '\n'.join(cos) + '\n',
            'colour_luts_sin.vh': head + '// sin(2*pi*p/256), +-127, biased +128.\n' + '\n'.join(sin) + '\n',
            'colour_luts_inv.vh': head + '// round(65536/m); index 0 unused.\n' + '\n'.join(inv) + '\n'}


def write_lut_vh(dirpath):
    for name, text in lut_vh().items():
        Path(dirpath, name).write_text(text)


def table(lines=120):
    print('noise  ramp  lumaSNR_dB  hueRMS_deg  chromaRMS  sync_hits  burst_lines')
    rows = []
    for noise in (0.0, 1.0, 3.0, 6.0):
        for ramp in (0.0, 2.0, 8.0):
            r = run_frame(lines=lines, noise=noise, phase_ramp=ramp)
            rows.append((noise, ramp, r['luma_snr_db'], r['hue_rms_deg'], r['chroma_rms'],
                         r['sync_hits'], r['burst_lines']))
            print('%5.1f  %4.1f  %9.2f  %10.2f  %8.2f  %9.3f  %11d' % rows[-1])
    return rows


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--noise', type=float, default=None)
    ap.add_argument('--phase-ramp', type=float, default=None)
    ap.add_argument('--lines', type=int, default=120)
    a = ap.parse_args()
    if a.noise is not None or a.phase_ramp is not None:
        r = run_frame(lines=a.lines, noise=a.noise or 0.0, phase_ramp=a.phase_ramp or 0.0)
        print({k: v for k, v in r.items() if k not in ('y', 'cb', 'cr')})
    else:
        table(a.lines)
