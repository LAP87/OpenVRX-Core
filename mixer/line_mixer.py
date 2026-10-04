#!/usr/bin/env python3
"""Offline prototype of a line-by-line video mixer for two analog FPV receivers.

Hypothesis under test (not how commercial mixers work, which is unpublished):
weak-signal "snow" raises high-frequency energy along a video line, so for each
line pick the receiver whose line is less noisy, with hysteresis so the choice
does not flicker, and average the two when both are about equally clean.

    python line_mixer.py a.mkv b.mkv --out mixed.mkv --stats stats.csv

The two recordings are aligned first: a frame offset from the brightness time
series, then a sub-image shift from phase correlation.
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np


def read_gray(path, limit=None):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f'cannot open {path}')
    frames = []
    while limit is None or len(frames) < limit:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f)
    cap.release()
    if not frames:
        raise SystemExit(f'no frames in {path}')
    return np.stack(frames).astype(np.float32)


def estimate_frame_offset(a, b, max_offset=60):
    """Frame lag k such that a[i] ~ b[i + k], from normalized mean-brightness series."""
    sa, sb = a.mean(axis=(1, 2)), b.mean(axis=(1, 2))
    sa, sb = (sa - sa.mean()) / (sa.std() + 1e-6), (sb - sb.mean()) / (sb.std() + 1e-6)
    best, best_k = -np.inf, 0
    for k in range(-max_offset, max_offset + 1):
        x, y = (sa[:len(sa) - k], sb[k:]) if k >= 0 else (sa[-k:], sb[:len(sb) + k])
        n = min(len(x), len(y))
        if n < 10:
            continue
        c = float(np.dot(x[:n], y[:n]) / n)
        if c > best:
            best, best_k = c, k
    return best_k


def estimate_shift(a_frame, b_frame):
    """(dx, dy) to apply to b so it lines up with a."""
    win = cv2.createHanningWindow(a_frame.shape[::-1], cv2.CV_64F)
    (dx, dy), _ = cv2.phaseCorrelate(a_frame.astype(np.float64), b_frame.astype(np.float64), win)
    return -dx, -dy


def align(a, b):
    k = estimate_frame_offset(a, b)
    if k > 0:
        b = b[k:]
    elif k < 0:
        a = a[-k:]
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    # Snow bursts dominate phase correlation, so estimate per frame after repairing
    # each channel's own noisy lines from its clean neighbours (repairing the same
    # rows in both would add identical stripes that pull dy towards zero), then
    # take the median over frames.
    def repaired(frame):
        noise = line_noise(frame[None])[0]
        bad = noise > 2 * np.median(noise)
        if bad.mean() > 0.5:
            return None
        rows, good = np.arange(len(frame)), np.flatnonzero(~bad)
        out = frame.copy()
        for x in range(frame.shape[1]):
            out[bad, x] = np.interp(rows[bad], good, frame[good, x])
        return out

    shifts = []
    for f in range(0, n, max(1, n // 25)):
        fa, fb = repaired(a[f]), repaired(b[f])
        if fa is not None and fb is not None:
            shifts.append(estimate_shift(fa, fb))
    dx, dy = (float(np.median([s[0] for s in shifts])), float(np.median([s[1] for s in shifts]))) if shifts else (0.0, 0.0)
    h, w = a.shape[1:]
    if abs(dx) > w / 8 or abs(dy) > h / 8:
        print(f'warning: implausible shift dx={dx:.1f} dy={dy:.1f}; not applying it', file=sys.stderr)
        dx = dy = 0.0
    if abs(dx) > 0.25 or abs(dy) > 0.25:
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        b = np.stack([cv2.warpAffine(f, m, (f.shape[1], f.shape[0]), borderMode=cv2.BORDER_REPLICATE) for f in b])
    return a, b, k, (dx, dy)


def line_noise(frames):
    """Mean absolute horizontal difference per line: shape (n_frames, n_lines)."""
    return np.abs(np.diff(frames, axis=2)).mean(axis=2)


def mix(a, b, blend_margin=0.15, switch_margin=0.25):
    """Return (mixed frames, choice) where choice is 0=A, 1=B, 2=blend per line.

    blend_margin: relative noise difference under which both lines are averaged.
    switch_margin: relative advantage the other channel needs before switching
    away from the current one (hysteresis down the frame and across frames).
    """
    na, nb = line_noise(a), line_noise(b)
    out = np.empty_like(a)
    choice = np.empty(na.shape, np.uint8)
    current = 0
    for f in range(a.shape[0]):
        for y in range(a.shape[1]):
            ea, eb = na[f, y], nb[f, y]
            rel = (ea - eb) / max(ea, eb, 1e-6)  # >0: A noisier
            if abs(rel) < blend_margin:
                out[f, y] = 0.5 * (a[f, y] + b[f, y])
                choice[f, y] = 2
                continue
            # switch only when the other channel is clearly better; otherwise stay (hysteresis)
            if current == 0 and rel > switch_margin:
                current = 1
            elif current == 1 and rel < -switch_margin:
                current = 0
            out[f, y] = a[f, y] if current == 0 else b[f, y]
            choice[f, y] = current
    return out, choice


def write_video(path, frames, fps):
    h, w = frames.shape[1:]
    fourcc = cv2.VideoWriter_fourcc(*('FFV1' if str(path).endswith('.mkv') else 'MJPG'))
    wr = cv2.VideoWriter(str(path), fourcc, fps, (w, h), isColor=False)
    for f in frames:
        wr.write(np.clip(f, 0, 255).astype(np.uint8))
    wr.release()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('a', type=Path)
    ap.add_argument('b', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--stats', type=Path)
    ap.add_argument('--fps', type=float, default=30.0)
    ap.add_argument('--limit', type=int, help='max frames to read per input')
    ap.add_argument('--blend-margin', type=float, default=0.15)
    ap.add_argument('--switch-margin', type=float, default=0.25)
    args = ap.parse_args(argv)

    a, b = read_gray(args.a, args.limit), read_gray(args.b, args.limit)
    if a.shape[1:] != b.shape[1:]:
        raise SystemExit(f'size mismatch {a.shape[1:]} vs {b.shape[1:]}; record both at the same resolution')
    a, b, k, (dx, dy) = align(a, b)
    print(f'aligned: frame offset {k}, shift dx={dx:.2f} dy={dy:.2f}, {len(a)} frames')
    mixed, choice = mix(a, b, args.blend_margin, args.switch_margin)
    write_video(args.out, mixed, args.fps)
    frac = [(choice == c).mean() for c in (0, 1, 2)]
    print(f'lines from A {frac[0]:.1%}, from B {frac[1]:.1%}, blended {frac[2]:.1%} -> {args.out}')
    if args.stats:
        na, nb, nm = line_noise(a), line_noise(b), line_noise(mixed)
        with args.stats.open('w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['frame', 'noise_a', 'noise_b', 'noise_mixed', 'share_a', 'share_b', 'share_blend'])
            for f in range(len(a)):
                c = choice[f]
                w.writerow([f, f'{na[f].mean():.2f}', f'{nb[f].mean():.2f}', f'{nm[f].mean():.2f}',
                            f'{(c == 0).mean():.3f}', f'{(c == 1).mean():.3f}', f'{(c == 2).mean():.3f}'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
