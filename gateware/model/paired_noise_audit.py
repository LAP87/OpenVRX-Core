"""Diagnose Core #29 with the original capture model; no RTL or hardware is run.

Run from Core: python gateware/model/paired_noise_audit.py --out /path/to/new.json
The six seeds and one-frame sample budget are the issue's original experiment.
Diagnostics observe model state; they do not change the slicer or the stimuli.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import time

import cvbs_capture_ref as cv
import pair_align_ref as pa


class ObservedCapture(cv.Capture):
    """Record events at line boundaries and pulses in the two vertical intervals."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.line_events = []
        self.vertical_events = []
        self.vertical_pulses = []
        self.pulse_widths = collections.Counter()

    def _finish_line(self, flywheel_next):
        if self.pos < 0:
            return super()._finish_line(flywheel_next)
        row = dict(n=self.n, start=self.last_start, edge=self.cur_edge,
                   eq=self.pulse_was_eq, broad=self.pulse_was_broad,
                   active=self.cur_active, bad=self.cur_bad, field=self.cur_field,
                   line=self.cur_line, countdown=self.countdown, numbered=self.numbered,
                   sync=self.sync, blank=self.blank, slicer=self.boot_slice,
                   sync_sum=self.sync_sum, porch_sum=self.porch_sum,
                   words=self.y_count // 2, locked=self.locked,
                   boot_rejects=self.boot_rejects)
        super()._finish_line(flywheel_next)
        row.update(next_sync=self.sync, next_blank=self.blank,
                   next_boot_rejects=self.boot_rejects, next_locked=self.locked)
        self.line_events.append(row)

    def _line_class_update(self, width_so_far, pending):
        before = self.field
        super()._line_class_update(width_so_far, pending)
        if self.field != before:
            self.vertical_events.append(dict(n=self.n, pulse_start=self.pulse_start,
                                             width=width_so_far, field=self.field,
                                             pending=pending, seen_normal=self.seen_normal))

    def step(self, s):
        was_pulse = self.in_pulse
        start, width = self.pulse_start, self.pulse_width
        super().step(s)
        if was_pulse and not self.in_pulse:
            self.pulse_widths[width] += 1
            truth_line = int(start / cv.SAMPLES_PER_LINE) + 1
            if truth_line <= 10 or 264 <= truth_line <= 273:
                self.vertical_pulses.append(dict(n=start, width=width, truth_line=truth_line,
                                                accepted=start in (self.cur_edge, self.pend_edge)))


def entry_digest(entries):
    h = hashlib.sha256()
    for e in entries:
        h.update((json.dumps(e, separators=(',', ':')) + '\n').encode())
    return h.hexdigest()


def run_case(samples, seed, kind, **kwargs):
    c = ObservedCapture(white_x8=cv.WHITE_X8_C5VRX, **kwargs)
    started = time.monotonic()
    c.run(samples)
    words = sum(e[0] == 'word' for e in c.entries)
    markers = [e for e in c.entries if e[0] == 'marker']
    groups = []
    for e in markers:
        if not groups or groups[-1]['field'] != e[1]:
            groups.append(dict(field=e[1], count=0, first_line=e[2], last_line=e[2]))
        groups[-1]['count'] += 1
        groups[-1]['last_line'] = e[2]
    return dict(seed=seed, kind=kind, samples=len(samples), words=words,
                markers=len(markers), field_groups=groups, entry_sha256=entry_digest(c.entries),
                elapsed_seconds=time.monotonic() - started, lock_trace=c.lock_trace,
                paired_input=c.paired_input, pulse_end_confirm=c.pulse_end_confirm,
                boot_rejects=c.boot_rejects, final_levels=[c.sync, c.blank],
                final_countdown=c.countdown, final_locked=c.locked,
                vertical_events=c.vertical_events, line_events=c.line_events,
                vertical_pulses=c.vertical_pulses, pulse_width_histogram=sorted(c.pulse_widths.items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seeds', type=int, nargs='+', default=list(range(1, 7)))
    ap.add_argument('--robust-pulses', action='store_true', help='opt-in model proposal; not implemented in RTL')
    args = ap.parse_args()
    if args.out.exists():
        ap.error('refusing to overwrite an existing audit')
    result = dict(schema=1, levels=[23, 31, 62], noise=2.0, frames=1,
                  robust_pulses=args.robust_pulses, cases=[])
    for seed in args.seeds:
        s = cv.synth(cv.bars, frames=1, levels=tuple(result['levels']), noise=2.0, seed=seed)
        for kind, stream in [('unpaired', s), ('paired', pa.pair_stream(s))]:
            row = run_case(stream, seed, kind, robust_pulses=args.robust_pulses)
            result['cases'].append(row)
            print(seed, kind, row['words'], row['markers'], row['vertical_events'], flush=True)
            # A partial result remains inspectable if a later case fails or is interrupted.
            args.out.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
