"""Reference for rtl/rssi_adc.v: what each pair of RSSI readings must publish.

ADS1115 code (TI SBAS444E table 7-1): trunc(uV * 32768 / FSR_uV), clamped to -32768..32767;
rssi_adc.v uses FSR +-4.096 V and counts a negative code as 0.

Per round (one reading of each channel):
- a channel whose transaction was not acknowledged has no reading: `valid` is 0 and its raw
  value stays;
- while calibrating (cal high before and during the round), each valid reading widens the
  channel's [min, max]; cal rising resets both ranges (min FFFFh, max 0) and clears cal_ok;
  cal falling sets cal_ok per channel when max >= min and max - min >= MIN_SPAN;
- pct = 0 at or below min, 100 at or above max, else floor((raw - min) * 100 / (max - min));
  published pct is 0 for an uncalibrated channel;
- a channel is low after N_LOW rounds in a row in which it was calibrated, valid and
  pct < LOW_PCT; it warns while low if the other channel is calibrated, valid, not low and at
  least MARGIN_PCT points higher (near the floor a point or two of RSSI says nothing).
"""

FSR_UV = 4_096_000
LOW_PCT, MARGIN_PCT, N_LOW, MIN_SPAN = 20, 5, 3, 400


def code(uv, fsr_uv=FSR_UV):
    c = int(uv * 32768 / fsr_uv) if uv >= 0 else -int(-uv * 32768 / fsr_uv)
    c = max(-32768, min(32767, c))
    return max(c, 0)                         # rssi_adc.v: a negative code counts as 0


class Rssi:
    def __init__(self, low_pct=LOW_PCT, margin_pct=MARGIN_PCT, n_low=N_LOW, min_span=MIN_SPAN):
        self.low_pct, self.margin_pct, self.n_low, self.min_span = low_pct, margin_pct, n_low, min_span
        self.raw = [0, 0]
        self.valid = [False, False]
        self.mn = [0xFFFF, 0xFFFF]
        self.mx = [0, 0]
        self.cal_ok = [False, False]
        self.n = [0, 0]
        self.cal = False

    def set_cal(self, on):
        if on and not self.cal:
            self.mn, self.mx, self.cal_ok = [0xFFFF, 0xFFFF], [0, 0], [False, False]
        if not on and self.cal:
            self.cal_ok = [self.mx[c] >= self.mn[c] and self.mx[c] - self.mn[c] >= self.min_span for c in (0, 1)]
        self.cal = on

    def load(self, mn_a, mx_a, mn_b, mx_b):
        self.mn, self.mx = [mn_a, mn_b], [mx_a, mx_b]
        self.cal_ok = [self.mx[c] >= self.mn[c] and self.mx[c] - self.mn[c] >= self.min_span for c in (0, 1)]

    def pct(self, c):
        r, mn, mx = self.raw[c], self.mn[c], self.mx[c]
        if r >= mx:
            return 100
        if r <= mn:
            return 0
        return (r - mn) * 100 // (mx - mn)

    def round(self, codes):
        """codes: (code A or None, code B or None); None = not acknowledged. Returns the
        published state as rssi_adc.v's testbench prints it."""
        for c in (0, 1):
            self.valid[c] = codes[c] is not None
            if self.valid[c]:
                self.raw[c] = codes[c]
                if self.cal:
                    self.mn[c] = min(self.mn[c], self.raw[c])
                    self.mx[c] = max(self.mx[c], self.raw[c])
        p = [self.pct(c) for c in (0, 1)]
        is_low = [self.cal_ok[c] and self.valid[c] and p[c] < self.low_pct for c in (0, 1)]
        self.n = [min(self.n[c] + 1, self.n_low) if is_low[c] else 0 for c in (0, 1)]
        low = [self.n[c] == self.n_low for c in (0, 1)]
        warn = [low[c] and not low[1 - c] and self.cal_ok[1 - c] and self.valid[1 - c]
                and p[c] is not None and p[1 - c] is not None and p[1 - c] - p[c] >= self.margin_pct
                for c in (0, 1)]
        pct = [p[c] if self.cal_ok[c] else 0 for c in (0, 1)]
        return dict(raw=tuple(self.raw), valid=tuple(map(int, self.valid)), mn=tuple(self.mn), mx=tuple(self.mx),
                    cal_ok=tuple(map(int, self.cal_ok)), pct=tuple(pct), low=tuple(map(int, low)),
                    warn=tuple(map(int, warn)))
