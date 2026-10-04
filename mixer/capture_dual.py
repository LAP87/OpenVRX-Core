#!/usr/bin/env python3
"""Record two video devices at the same time (e.g. two USB-UVC 5.8 GHz receivers on
the same channel) for offline mixer development.

    python capture_dual.py --a 0 --b 1 --seconds 120 --out flights/2026-10-02_backyard

Writes <out>_a.mkv, <out>_b.mkv (lossless FFV1 when available) and <out>_times.csv
with host timestamps per frame. Use --list to probe device indices first.
"""
import argparse
import csv
import sys
import threading
import time
from pathlib import Path

import cv2


def probe(max_index=10):
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ok, f = cap.read()
            print(f'device {i}: {"%dx%d" % (f.shape[1], f.shape[0]) if ok else "opened, no frame"} '
                  f'@ {cap.get(cv2.CAP_PROP_FPS):.1f} fps')
        cap.release()


def grab(index, path, seconds, stamps, label, width, height):
    cap = cv2.VideoCapture(index)
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    ok, frame = cap.read()
    if not ok:
        print(f'{label}: device {index} gives no frames', file=sys.stderr)
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    h, w = frame.shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'FFV1'), fps, (w, h))
    if not writer.isOpened():
        path = path.with_suffix('.avi')
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, (w, h))
    end, n = time.monotonic() + seconds, 0
    while time.monotonic() < end and ok:
        stamps.append((label, n, time.monotonic()))
        writer.write(frame)
        n += 1
        ok, frame = cap.read()
    writer.release()
    cap.release()
    print(f'{label}: {n} frames {w}x{h} @ {fps:.1f} fps -> {path}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--a', type=int, default=0)
    ap.add_argument('--b', type=int, default=1)
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--width', type=int)
    ap.add_argument('--height', type=int)
    ap.add_argument('--out', type=Path, default=Path('capture'))
    args = ap.parse_args(argv)
    if args.list:
        probe()
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    stamps = []
    threads = [threading.Thread(target=grab, args=(i, Path(f'{args.out}_{l}.mkv'), args.seconds, stamps, l,
                                                   args.width, args.height))
               for l, i in (('a', args.a), ('b', args.b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(f'{args.out}_times.csv', 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['device', 'frame', 'host_time_s'])
        w.writerows(sorted(stamps, key=lambda r: r[2]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
