#!/usr/bin/env python3
"""Measure glass-to-glass video latency from a high-speed recording.

Film a blinking LED and the display(s) showing the FPV camera's view of that LED
in the same shot. This script tracks mean brightness in one LED region and one or
more screen regions, finds rising edges, pairs each LED edge with the next screen
edge and reports the delay.

Example:
    python analyze_latency.py clip.mp4 --capture-fps 240 \
        --led 100,200,20,20 --screen moneagle=400,220,60,40 --screen xr=900,300,60,40

Use --preview N to write frame N with a coordinate grid, to pick regions.
"""
import argparse
import csv
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np


def parse_roi(text):
    name, _, coords = text.rpartition('=')
    x, y, w, h = (int(v) for v in coords.split(','))
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f'empty region: {text}')
    return (name or 'screen', (x, y, w, h))


def brightness_series(path, rois):
    """Mean gray level per frame for each (name, (x, y, w, h)) region."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f'cannot open video: {path}')
    series = {name: [] for name, _ in rois}
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fh, fw = gray.shape
        for name, (x, y, w, h) in rois:
            if x + w > fw or y + h > fh:
                raise SystemExit(f'region {name} {x},{y},{w},{h} is outside {fw}x{fh} frame')
            series[name].append(float(gray[y:y + h, x:x + w].mean()))
    container_fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return {k: np.asarray(v) for k, v in series.items()}, container_fps


def rising_edges(values, low_frac=0.35, high_frac=0.65, min_gap=3):
    """Sub-frame times (in frames) where the signal rises through mid-level.

    Hysteresis: the signal must fall below low before the next rise above high
    counts, so flicker and noise do not create extra edges. The returned time is
    the linear interpolation of the 50 % crossing between the two frames.
    """
    lo, hi = np.percentile(values, 2), np.percentile(values, 98)
    span = hi - lo
    if span < 5:  # less than ~2 % of 8-bit range: no usable blinking
        return [], (lo, hi)
    low, high, mid = lo + low_frac * span, lo + high_frac * span, lo + 0.5 * span
    edges, armed, last = [], False, -min_gap
    for i in range(1, len(values)):
        if values[i] < low:
            armed = True
        elif armed and values[i] >= high and i - last >= min_gap:
            j = i
            while j > 0 and values[j - 1] >= mid:  # walk back to the mid crossing
                j -= 1
            a, b = values[j - 1], values[j]
            frac = (mid - a) / (b - a) if b != a else 0.0
            edges.append(j - 1 + float(np.clip(frac, 0.0, 1.0)))
            armed, last = False, i
    return edges, (lo, hi)


def estimate_lag(led, screen, max_lag):
    """Overall delay in frames from cross-correlating the on/off patterns.

    The LED must blink with random intervals; then only the true lag lines the
    two patterns up. Returns (lag, peak, runner_up): normalized correlation at
    the best lag and the best value more than a few frames away from it.
    """
    def binarize(v):
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        return (v > (lo + hi) / 2).astype(float) * 2 - 1
    a, b = binarize(led), binarize(screen)
    n = min(len(a), len(b))
    corr = np.array([np.dot(a[:n - k], b[k:n]) / (n - k) for k in range(0, min(max_lag, n - 2) + 1)])
    lag = int(np.argmax(corr))
    # the main peak is as wide as a typical on/off run; look for rivals outside it
    changes = np.flatnonzero(np.diff(a) != 0)
    run = int(np.median(np.diff(changes))) if len(changes) > 2 else 3
    away = np.abs(np.arange(len(corr)) - lag) > max(3, run)
    runner_up = float(corr[away].max()) if away.any() else -1.0
    return lag, float(corr[lag]), runner_up


def pair_delays(led_edges, screen_edges, frame_ms, lag, tolerance):
    """Pair each LED edge with the screen edge nearest to led + lag, within ± tolerance frames.

    Pairing around the correlation lag (instead of "next screen edge") cannot
    confuse consecutive blinks when the delay is longer than the blink period.
    """
    pairs = []
    se = np.asarray(screen_edges)
    for t in led_edges:
        if not len(se):
            break
        k = int(np.argmin(np.abs(se - (t + lag))))
        if abs(se[k] - (t + lag)) <= tolerance:
            pairs.append((t, float(se[k]), (se[k] - t) * frame_ms))
    return pairs


def summarize(delays):
    if not delays:
        return None
    s = sorted(delays)
    return {'n': len(s), 'median_ms': statistics.median(s), 'mean_ms': statistics.fmean(s),
            'stdev_ms': statistics.stdev(s) if len(s) > 1 else 0.0,
            'min_ms': s[0], 'max_ms': s[-1], 'p90_ms': s[min(len(s) - 1, int(0.9 * len(s)))]}


def write_preview(path, index, out):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f'cannot read frame {index}')
    h, w = frame.shape[:2]
    for x in range(0, w, 50):
        cv2.line(frame, (x, 0), (x, h), (0, 255, 255) if x % 250 == 0 else (0, 120, 120), 1)
        if x % 100 == 0:
            cv2.putText(frame, str(x), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    for y in range(0, h, 50):
        cv2.line(frame, (0, y), (w, y), (0, 255, 255) if y % 250 == 0 else (0, 120, 120), 1)
        if y % 100 == 0:
            cv2.putText(frame, str(y), (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    cv2.imwrite(str(out), frame)
    print(f'wrote {out} ({w}x{h})')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video', type=Path)
    ap.add_argument('--led', type=lambda s: parse_roi('led=' + s.split('=')[-1]), help='x,y,w,h of the LED')
    ap.add_argument('--screen', type=parse_roi, action='append', default=[],
                    help='[name=]x,y,w,h of the LED as seen on a display; repeat for several displays')
    ap.add_argument('--capture-fps', type=float,
                    help='real capture rate; phones often store 240 fps slow motion as 30 fps')
    ap.add_argument('--max-delay-ms', type=float, default=1000.0, help='largest delay searched for')
    ap.add_argument('--tolerance-ms', type=float, default=20.0,
                    help='how far an individual pair may deviate from the overall delay')
    ap.add_argument('--csv', type=Path, help='write every paired edge to this CSV')
    ap.add_argument('--preview', type=int, metavar='FRAME', help='write a gridded PNG of FRAME and exit')
    args = ap.parse_args(argv)

    if args.preview is not None:
        write_preview(args.video, args.preview, args.video.with_suffix(f'.frame{args.preview}.png'))
        return 0
    if not args.led or not args.screen:
        ap.error('--led and at least one --screen are required')
    # unnamed screens get distinct names; explicit duplicates would merge two displays
    args.screen = [(f'screen{i + 1}' if name == 'screen' else name, roi) for i, (name, roi) in enumerate(args.screen)]
    names = [n for n, _ in args.screen]
    if len(set(names)) != len(names) or 'led' in names:
        ap.error(f'screen names must be unique and not "led": {names}')

    series, container_fps = brightness_series(args.video, [args.led, *args.screen])
    fps = args.capture_fps or container_fps
    if not fps or fps <= 0:
        ap.error('frame rate unknown; pass --capture-fps')
    frame_ms = 1000.0 / fps
    if args.capture_fps and container_fps and abs(container_fps - args.capture_fps) > 1:
        print(f'note: container says {container_fps:.2f} fps, using --capture-fps {fps:g}')

    led_edges, _ = rising_edges(series['led'])
    print(f'{len(series["led"])} frames at {fps:g} fps ({frame_ms:.2f} ms/frame), {len(led_edges)} LED edges')
    rows, rc = [], 0
    for name, _ in args.screen:
        edges, _ = rising_edges(series[name])
        lag, peak, runner_up = estimate_lag(series['led'], series[name], int(args.max_delay_ms / frame_ms))
        print(f'{name}: pattern correlation peak {peak:.2f} at {lag * frame_ms:.1f} ms (next best {runner_up:.2f})')
        if peak < 0.5 or peak - runner_up < 0.15:
            print(f'{name}: delay is ambiguous — make the LED blink with random intervals, record longer, '
                  f'or raise --max-delay-ms')
            rc = 1
            continue
        pairs = pair_delays(led_edges, edges, frame_ms, lag, max(2.0, args.tolerance_ms / frame_ms))
        stats = summarize([d for *_, d in pairs])
        if stats is None:
            print(f'{name}: no paired edges (check region and exposure)')
            rc = 1
            continue
        print(f'{name}: n={stats["n"]} median={stats["median_ms"]:.1f} ms mean={stats["mean_ms"]:.1f} '
              f'sd={stats["stdev_ms"]:.1f} min={stats["min_ms"]:.1f} p90={stats["p90_ms"]:.1f} max={stats["max_ms"]:.1f}')
        if stats['n'] < 10:
            print(f'  warning: only {stats["n"]} samples; record longer for a stable figure')
        unpaired = len(led_edges) - stats['n']
        if unpaired:
            print(f'  {unpaired} LED edges had no screen edge within ±{args.tolerance_ms:g} ms of the overall delay '
                  f'(dropped/frozen frames, or the clip ends)')
        rows += [(name, led_t, scr_t, d) for led_t, scr_t, d in pairs]
    if args.csv:
        with args.csv.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['display', 'led_edge_frame', 'screen_edge_frame', 'delay_ms'])
            w.writerows((n, f'{a:.3f}', f'{b:.3f}', f'{d:.3f}') for n, a, b, d in rows)
        print(f'wrote {args.csv}')
    return rc


if __name__ == '__main__':
    sys.exit(main())
