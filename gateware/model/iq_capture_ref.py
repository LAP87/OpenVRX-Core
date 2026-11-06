"""Nominal IQ-to-monochrome-Capture adapter, not a hardware calibration.

The unchanged demodulator supplies IRE. Convert with the existing model's
22 + 0.22*IRE output scale (clip to six bits), then feed Python ints into the
unchanged composite Capture. Truth is never supplied to Capture. Grey-bar
truth is used only for scoring emitted pixels, without offset removal or
alignment. The fixed three-low-sample sync score remains a separate metric.
"""
from collections import Counter
import math
import struct

import numpy as np

import cvbs_capture_ref as cv

# kind, field, line, word-index/HF, data/bad, unused/length; little endian.
ENTRY = struct.Struct('<BBHIII')


def video_codes(video):
    return np.clip(np.rint(22+0.22*video), 0, 63).astype(np.uint8)


def write_entries(path, entries):
    with path.open('xb') as out:
        for entry in entries:
            if entry[0] == 'word':
                _, field, line, index, data = entry
                out.write(ENTRY.pack(0, field, line, index, data, 0))
            else:
                _, field, line, hf, bad, length = entry
                out.write(ENTRY.pack(1, field, line, hf, bad, length))


def score_entries(entries):
    """Score full closed rows. Never count startup or trailing partial words."""
    pending = []
    complete = valid = malformed = bad_count = chroma_errors = 0
    squared_error = pixels = 0
    fields = Counter()
    lengths = Counter()
    markers = 0
    for entry in entries:
        if entry[0] == 'word':
            pending.append(entry)
            continue
        _, field, line, hf, bad, length = entry
        markers += 1
        lengths[length] += 1
        bad_count += int(bool(bad))
        good_shape = (len(pending) == 360 and
                      all(w[1:4] == (field, line, i) for i, w in enumerate(pending)))
        if not good_shape:
            malformed += 1
            pending = []
            continue
        complete += 1
        if not bad and abs(length-1716) <= 2:
            valid += 1
            fields[field] += 1
        for i, word in enumerate(pending):
            data = word[4]
            chroma_errors += int(data & 0x00ff00ff != 0x00800080)
            for x, y in [(2*i, (data >> 8) & 255), (2*i+1, (data >> 24) & 255)]:
                delta = y-cv.bars(line, x)
                squared_error += delta*delta
                pixels += 1
        pending = []
    return dict(markers=markers, complete_rows=complete, valid_rows=valid,
                malformed_rows=malformed, bad_markers=bad_count,
                valid_rows_by_field=dict(fields), marker_lengths=dict(lengths),
                chroma_errors=chroma_errors, pixels=pixels,
                squared_error=squared_error,
                pixel_rmse=math.sqrt(squared_error/pixels) if pixels else None,
                trailing_words=len(pending))


def decode(codes):
    # numpy uint8 arithmetic in the reference's moving sum could underflow.
    # The model's documented input is a Python integer, not a numpy scalar.
    capture = cv.Capture(comb=True, avg=8, white_x8=20, boot_check=True)
    entries = capture.run(map(int, codes))
    return capture, entries, score_entries(entries)
