"""Reference for rtl/pair_align.v: the C5VRX sample bus carries 6-bit samples at 40 MS/s in identical
pairs [D, D] (20 MS/s of unique samples, hub docs/design/2026-10-24/DIGITAL_INGANG.md). On the bench
(2026-10-27/28, 17 captures of 65 536 samples) the first sample of a pair could lack a bit whose rising
edge arrived up to one clock late: bit 2 in 41-66 % of its rising edges, never in the second sample, and
every isolated code-0 sample sat in the first position. Bits 0, 1, 3, 4 and 5 never differed within a
pair. The second sample of a pair is therefore the settled one.

The stage finds the pair phase and replaces the first sample of every pair with the second:

* Parity. Clocks since reset are counted; the count's LSB is the parity of the current sample. The pair
  phase is the parity of a pair's second sample (register `phase`, 0 after reset).
* Mismatch counters. Every sample is compared with the previous one. At an odd sample the comparison is
  between an even sample and the odd one after it (a pair (even, odd), whose second sample is odd: phase
  1); at an even sample between an odd and the even one after it (phase 0). The two counters c01 (phase 1)
  and c10 (phase 0) count the comparisons that differed.
* Window. Every 2^WIN_LOG2 clocks (4 096 = 102 us at 40 MHz), at the clock whose count has wrapped to 0,
  the chosen parity's count is published as `mism`, and the phase flips when the chosen parity differed at
  least HOLD_MIN times and the other parity differed less than half as often. The counters restart with
  that clock's comparison (which belongs to the new window; the count is 0, so it is a phase-0
  comparison). The sample at that clock still uses the old phase. Flat input (both counts under HOLD_MIN)
  and input without pairs (both counts alike) never move the phase.
* Output. q = d when the sample's parity is the phase (the second sample of its pair), else the previous
  sample (the previous pair's second). With the right phase the output is the input one sample late with
  every pair made identical: a late edge or a dropped first sample never reaches the capture. With the
  wrong phase the first sample is held over both positions, which doubles a glitch; that is what the
  window decision prevents.

The RTL registers q, so it appears one clock after d; the model returns q for the sample itself.

pair_stream(), glitch() and mismatching_pairs() make and measure test streams for sim/test_pair_align.py.
"""
import random

WIN_LOG2 = 12
HOLD_MIN = 16


class PairAlign:
    def __init__(self, win_log2=WIN_LOG2, hold_min=HOLD_MIN, phase=0):
        self.win = 1 << win_log2
        self.hold_min = hold_min
        self.phase = phase
        self.n = 0          # clocks since reset
        self.d1 = 0         # the previous sample (0 after reset)
        self.c01 = 0        # mismatching (even, odd) comparisons in the window
        self.c10 = 0        # mismatching (odd, even) comparisons in the window
        self.mism = 0       # the chosen parity's count of the last window
        self.phase_trace = []   # (clock, new phase) at every change
        self.mism_trace = []    # (clock, mism) at every window end

    def step(self, d):
        par = self.n & 1
        q = d if par == self.phase else self.d1
        diff = 1 if d != self.d1 else 0
        if self.n != 0 and self.n % self.win == 0:
            cur = self.c01 if self.phase else self.c10
            oth = self.c10 if self.phase else self.c01
            self.mism = cur
            self.mism_trace.append((self.n, cur))
            if cur >= self.hold_min and oth < (cur >> 1):
                self.phase ^= 1
                self.phase_trace.append((self.n, self.phase))
            self.c01 = 0
            self.c10 = diff          # par is 0 at a window end
        elif par:
            self.c01 += diff
        else:
            self.c10 += diff
        self.d1 = d
        self.n += 1
        return q

    def run(self, samples):
        return [self.step(s) for s in samples]


def pair_stream(samples, phase=1):
    """The bus's view of `samples` (40 MS/s): the sample at every even index is also sent at the odd index
    after it (20 MS/s of unique samples), so the second sample of a pair has odd parity (phase 1). With
    phase 0 one blanking-level sample is put in front so that the pairs sit on (odd, even)."""
    out = []
    for i in range(0, len(samples) - 1, 2):
        out.append(samples[i])
        out.append(samples[i])
    if phase == 0:
        out.insert(0, out[0])
    return out


def glitch(paired, phase=1, p_late=0.5, p_zero=0.0, seed=1):
    """The bench's faults put into a paired stream: at a rising edge of bit 2 (the settled sample has bit 2
    set, the previous pair's did not) the first sample of the pair lacks bit 2 with probability p_late; a
    first sample is replaced by code 0 with probability p_zero. Returns (stream, late edges, zeros)."""
    rnd = random.Random(seed)
    out = list(paired)
    first = 1 - phase
    late = zeros = 0
    prev_settled = None
    for k in range(first, len(out) - 1, 2):
        settled = out[k + 1]
        if prev_settled is not None and (settled & 4) and not (prev_settled & 4) and rnd.random() < p_late:
            out[k] = settled & ~4
            late += 1
        elif p_zero and rnd.random() < p_zero:
            out[k] = 0
            zeros += 1
        prev_settled = settled
    return out, late, zeros


def mismatching_pairs(stream, phase, start=0):
    """Pairs (first, second) from index `start` on whose two samples differ, for pairs whose second sample
    has parity `phase`."""
    first = 1 - phase
    k0 = start + ((first - start) % 2)
    return sum(1 for k in range(k0, len(stream) - 1, 2) if stream[k] != stream[k + 1])


def write_hex(path, samples):
    from pathlib import Path
    Path(path).write_text('\n'.join(f'{s:02x}' for s in samples) + '\n')
