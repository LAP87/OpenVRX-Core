"""Receiver boundary C, feasibility model (task 67): an analog FPV link as complex baseband IQ, quantised
to q bits per axis as the ESP32-C5's diagnostic bus offers it (4 bits in C5VRX-5's own demodulator,
7 bits in zerowidth's tap), demodulated with a plain phase differentiator, and measured.

Chain, all at FS = 40 MS/s:
  composite video (IRE, from cvbs_capture_ref's NTSC geometry) -> video low-pass -> FM modulation
  (DEV MHz per volt of composite, 1 V = 140 IRE) -> channel low-pass (+-BW/2) -> complex white noise at
  a carrier-to-noise ratio defined in BW -> AGC to a fixed RMS -> quantise I and Q to q bits ->
  FM demodulation (angle of z[n] conj z[n-1]) -> video low-pass -> metrics against the clean composite:
    luma SNR  : 100 IRE over the RMS error in the active parts of active lines, in dB
    sync hits : lines whose sync edge is found within +-3 samples of the truth by a fixed slicer
    6-bit SNR : the same demodulated video quantised to C5VRX's 6-bit output scale (22 codes per
                100 IRE, as the bench saw 22 of 64 codes in use), for the composite path of task 64

What it does not model: pre-emphasis, the receiver's own filter calibration, DC offsets, Wi-Fi bursts,
multipath, the U85Q phase tracker and C5VRX's gain loop. These are results for the specified synthetic
chain, not a lower bound for real hardware. A different receiver can do better or worse. The model
compares bit depths and demodulators; it does not establish what either achieves in the field.

    .venv/bin/python gateware/model/iq_demod_ref.py            # the table
    .venv/bin/python gateware/model/iq_demod_ref.py --lines 120 --dev 2.8 --bw 12e6
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cvbs_capture_ref as cv  # noqa: E402

FS = 40e6
IRE_PER_VOLT = 140.0


# ---- composite in IRE -------------------------------------------------------------------------
def composite_ire(luma_fn, lines, first_line=20, seed=1):
    """Floats in IRE at FS for `lines` consecutive NTSC lines starting at line `first_line` of field 1:
    sync -40, blank 0, white 100; the vertical interval as in cvbs_capture_ref.synth. Returns
    (samples, line_starts in samples, [(start, active) per line])."""
    plan = cv.pulse_plan_525()
    out = []
    starts = []
    info = []
    t = 0.0
    for k in range(lines):
        ln = (first_line - 1 + k) % 525 + 1
        pa, pb = plan[ln]
        start = int(round(t))
        end = int(round(t + cv.SAMPLES_PER_LINE))
        half = int(round(t + cv.SAMPLES_PER_LINE / 2))
        line = np.zeros(end - start)

        def put(lo, w):
            a, b = max(lo - start, 0), min(lo - start + w, end - start)
            if b > a:
                line[a:b] = -40.0

        if pa == 'n':
            put(start, cv.SYNC_W)
        elif pa == 'e':
            put(start, cv.EQ_W)
        elif pa == 'b':
            put(start, cv.BROAD_W)
        if pb == 'e':
            put(half, cv.EQ_W)
        elif pb == 'b':
            put(half, cv.BROAD_W)
        active = cv.active_525(ln)
        if active:
            x = np.arange(720)
            pos = np.rint(cv.ACT_START + x * (FS / 13.5e6)).astype(int)
            y = np.array([cv.clamp(luma_fn(ln, int(xx)), 16, 235) for xx in x], dtype=float)
            ire = (y - 16.0) * 100.0 / 219.0
            # zero-order hold between luma positions
            for i in range(720):
                lo = pos[i]
                hi = pos[i + 1] if i + 1 < 720 else min(lo + 3, end - start)
                line[lo:hi] = ire[i]
        out.append(line)
        starts.append(start)
        info.append((start, active))
        t += cv.SAMPLES_PER_LINE
    return np.concatenate(out), np.array(starts), info


def lowpass(x, cutoff_hz, taps=63):
    """Windowed-sinc FIR, zero phase (filtfilt-like by symmetric kernel and 'same' convolution)."""
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff_hz / FS * n) * np.hamming(taps)
    h /= h.sum()
    if np.iscomplexobj(x):
        return np.convolve(x.real, h, mode='same') + 1j * np.convolve(x.imag, h, mode='same')
    return np.convolve(x, h, mode='same')


# ---- link -----------------------------------------------------------------------------------------
def fm_modulate(video_ire, dev_mhz_per_volt):
    """Complex baseband of an FM carrier whose frequency follows the video: blank = 0 Hz."""
    f_inst = (video_ire / IRE_PER_VOLT) * dev_mhz_per_volt * 1e6
    phase = 2 * np.pi * np.cumsum(f_inst) / FS
    return np.exp(1j * phase)


def add_noise(z, cn_db, bw_hz, rng):
    """Complex white noise so that carrier power / noise power in bw_hz equals cn_db."""
    c = np.mean(np.abs(z) ** 2)
    n_density = c / (10 ** (cn_db / 10) * bw_hz)           # per Hz
    sigma2 = n_density * FS                                  # total noise power over the sample rate
    noise = (rng.standard_normal(len(z)) + 1j * rng.standard_normal(len(z))) * np.sqrt(sigma2 / 2)
    return z + noise


def quantise_iq(z, bits, rms_target=0.25):
    """AGC to rms_target of full scale (+-1), then uniform quantisation to `bits` per axis; the C5VRX
    'ultrafine' lane is a window of the ADC word, which an AGC inside the window reproduces here."""
    g = rms_target / max(np.sqrt(np.mean(np.abs(z) ** 2)), 1e-12)
    z = z * g
    levels = 2 ** (bits - 1)
    def q(v):
        return np.clip(np.round(v * levels), -levels, levels - 1) / levels
    return q(z.real) + 1j * q(z.imag)


def fm_demodulate(z, dev_mhz_per_volt):
    """Instantaneous frequency from the phase step, back to IRE."""
    d = np.angle(z[1:] * np.conj(z[:-1]))
    f_inst = np.concatenate([[0.0], d]) * FS / (2 * np.pi)
    return f_inst / (dev_mhz_per_volt * 1e6) * IRE_PER_VOLT


def fm_demodulate_pll(z, bits, dev_mhz_per_volt, gated=True, loop_sign=1):
    """Opt-in integer-loop experiment; adjacent phase remains run_case's default."""
    from fm_pll_ref import FMPLL, TURN
    pll = FMPLL(bits, gated=gated, loop_sign=loop_sign)
    scale = 1 << (bits-1)
    integer_i = np.rint(z.real*scale).astype(np.int16)
    integer_q = np.rint(z.imag*scale).astype(np.int16)
    inc = np.fromiter((pll.step(int(i), int(q)) for i, q in zip(integer_i, integer_q)),
                      dtype=np.float64, count=len(z))
    return inc * FS / TURN / (dev_mhz_per_volt*1e6) * IRE_PER_VOLT


def compare_discriminators(cn_db, bits, lines=60, dev=2.8, bw=12e6, video_bw=4.2e6, seed=1):
    """Three demodulators consume the same immutable quantised complex stream.

    Metrics retain the original zero-phase FIR, sync tolerance and time origin;
    no delay search or alignment is performed to improve the PLL's score.
    """
    import hashlib
    clean, starts, info = composite_ire(cv.bars, lines)
    video = lowpass(clean, video_bw)
    z = lowpass(fm_modulate(video, dev), bw/2, taps=95)
    z = lowpass(add_noise(z, cn_db, bw, np.random.default_rng(seed)), bw/2, taps=95)
    z = quantise_iq(z, bits)
    scale = 1 << (bits-1)
    raw = np.column_stack((np.rint(z.real*scale), np.rint(z.imag*scale))).astype('<i2').tobytes()
    row = dict(cn_db=cn_db, bits=bits, lines=lines, fs=FS, dev=dev, bw=bw,
               video_bw=video_bw, seed=seed, iq_sha256=hashlib.sha256(raw).hexdigest(),
               iq_samples=len(z), metrics={})
    streams = [('adjacent', fm_demodulate(z, dev)),
               ('gated_pll', fm_demodulate_pll(z, bits, dev, gated=True)),
               ('ungated_pll', fm_demodulate_pll(z, bits, dev, gated=False))]
    for name, demod in streams:
        filtered = lowpass(demod, video_bw)
        row['metrics'][name] = dict(luma_snr_db=float(luma_snr_db(filtered, video, info)),
                                    sync_hits=sync_hit_rate(filtered, starts))
    row['gated_sync_not_worse'] = row['metrics']['gated_pll']['sync_hits'] >= row['metrics']['adjacent']['sync_hits']
    return row


# ---- metrics ----------------------------------------------------------------------------------------
def luma_snr_db(demod, clean, info):
    err = []
    for start, active in info:
        if not active:
            continue
        a, b = start + cv.ACT_START + 40, start + cv.ACT_START + cv.ACTIVE_W - 40
        err.append(demod[a:b] - clean[a:b])
    e = np.concatenate(err)
    e = e - np.mean(e)                                   # a level offset is removed by the clamp downstream
    rms = np.sqrt(np.mean(e ** 2))
    return 20 * np.log10(100.0 / max(rms, 1e-9))


def sync_hit_rate(demod, starts, slice_ire=-20.0, tol=3):
    """Fraction of line starts whose first crossing below slice_ire lies within +-tol samples."""
    low = demod < slice_ire
    hits = 0
    for s in starts[1:]:
        w = low[s - 40:s + 40]
        idx = np.flatnonzero(w)
        if len(idx) == 0:
            continue
        # first sample of the first run of at least 3 low samples
        run = np.flatnonzero(np.convolve(w.astype(int), np.ones(3, int), mode='valid') == 3)
        if len(run) and abs(run[0] - 40) <= tol:
            hits += 1
    return hits / max(len(starts) - 1, 1)


def requantise_6bit(demod):
    """C5VRX's output scale as the bench saw it: about 22 codes per 100 IRE, blank near code 22."""
    codes = np.clip(np.round(22 + demod * 0.22), 0, 63)
    return (codes - 22) / 0.22


def run_case(cn_db, bits, lines=90, dev=2.8, bw=12e6, video_bw=4.2e6, seed=1, out6=False):
    rng = np.random.default_rng(seed)
    clean, starts, info = composite_ire(cv.bars, lines)
    video = lowpass(clean, video_bw)
    z = fm_modulate(video, dev)
    z = lowpass(z, bw / 2, taps=95)
    z = add_noise(z, cn_db, bw, rng)
    z = lowpass(z, bw / 2, taps=95)                      # the receiver's channel filter
    z = quantise_iq(z, bits)
    demod = lowpass(fm_demodulate(z, dev), video_bw)
    if out6:
        demod = requantise_6bit(demod)
    return luma_snr_db(demod, video, info), sync_hit_rate(demod, starts)


def table(lines=90, dev=2.8, bw=12e6, cns=(0, 3, 5, 8, 12, 20, 30), bits_list=(4, 7)):
    rows = []
    for cn in cns:
        row = {'cn_db': cn}
        for b in bits_list:
            snr, hit = run_case(cn, b, lines=lines, dev=dev, bw=bw)
            row[f'snr_{b}b'] = snr
            row[f'sync_{b}b'] = hit
        snr6, hit6 = run_case(cn, 4, lines=lines, dev=dev, bw=bw, out6=True)
        row['snr_4b_out6'] = snr6
        row['sync_4b_out6'] = hit6
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lines', type=int, default=90)
    ap.add_argument('--dev', type=float, default=2.8, help='MHz per volt of composite (1 V = 140 IRE)')
    ap.add_argument('--bw', type=float, default=12e6, help='channel bandwidth in Hz, also the C/N reference')
    a = ap.parse_args()
    rows = table(lines=a.lines, dev=a.dev, bw=a.bw)
    print(f'FS 40 MS/s, deviation {a.dev} MHz/V, channel {a.bw / 1e6:.0f} MHz, {a.lines} lines of grey bars; luma SNR in dB, sync hits as a fraction')
    print(f"{'C/N':>5} | {'4-bit IQ':>16} | {'7-bit IQ':>16} | {'4-bit IQ, 6-bit out':>20}")
    for r in rows:
        print(f"{r['cn_db']:>5} | {r['snr_4b']:6.1f} dB {r['sync_4b']:5.2f} | {r['snr_7b']:6.1f} dB {r['sync_7b']:5.2f} | "
              f"{r['snr_4b_out6']:6.1f} dB {r['sync_4b_out6']:5.2f}")


if __name__ == '__main__':
    main()
