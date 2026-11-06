"""Fixed first controls / separately launched noise phase for task75."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

import iq_demod_ref as iq
import iq_capture_ref as adapter


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--cn', type=int, choices=[4, 8, 12])
    args = ap.parse_args()
    args.out.mkdir(exist_ok=False)
    result = dict(schema=1, model_only=True, hardware=False,
                  runtime=dict(python=sys.version, prefix=sys.prefix, numpy=np.__version__),
                  parameters=dict(lines=1050, first_line=1, fs=iq.FS, seed=1, dev=2.8,
                                  channel_bw=12e6, video_bw=4.2e6, cn=args.cn,
                                  code_blank=22, code_per_ire=.22, code_bits=6,
                                  comb=True, avg=8, white_x8=20, boot_check=True), cases=[])
    started = time.monotonic()
    clean, starts, info = iq.composite_ire(iq.cv.bars, 1050, first_line=1)
    video = iq.lowpass(clean, 4.2e6)
    result['source_video_sha256'] = sha(video.astype('<f8').tobytes())

    def run(name, bits, demod, iq_hash=None):
        codes = adapter.video_codes(demod)
        capture, entries, metrics = adapter.decode(codes)
        raw = args.out/(name+'.entries.bin')
        adapter.write_entries(raw, entries)
        row = dict(name=name, bits=bits, iq_sha256=iq_hash,
                   codes_sha256=sha(codes.tobytes()), code_samples=len(codes),
                   clipping_zero=int(np.count_nonzero(codes == 0)),
                   clipping_max=int(np.count_nonzero(codes == 63)),
                   raw=dict(path=raw.name, bytes=raw.stat().st_size, sha256=sha(raw.read_bytes())),
                   metrics=metrics, lock_trace=capture.lock_trace,
                   boot_rejects=capture.boot_rejects,
                   original_slicer=iq.sync_hit_rate(demod, starts),
                   original_luma_snr=float(iq.luma_snr_db(demod, video, info)))
        result['cases'].append(row)
        (args.out/'results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(name, metrics, 'slicer',row['original_slicer'],flush=True)
        if args.cn is None and name in ('bypass', 'adjacent7'):
            assert metrics['valid_rows'] >= 400 and set(metrics['valid_rows_by_field']) == {0,1}, metrics
            assert metrics['malformed_rows'] == metrics['chroma_errors'] == 0, metrics
            assert metrics['pixel_rmse'] < 16, metrics

    if args.cn is None:
        run('bypass', None, video)
    base = iq.lowpass(iq.fm_modulate(video, 2.8), 6e6, taps=95)
    if args.cn is not None:
        base = iq.lowpass(iq.add_noise(base, args.cn, 12e6, np.random.default_rng(1)), 6e6, taps=95)
    for bits in ([7] if args.cn is None else [4, 7]):
        z = iq.quantise_iq(base, bits)
        scale = 1 << (bits-1)
        raw = np.column_stack((np.rint(z.real*scale), np.rint(z.imag*scale))).astype('<i2').tobytes()
        iq_hash = sha(raw)
        # Per-depth IQ is identical for all discriminators. No per-path AGC.
        run('adjacent'+str(bits), bits, iq.lowpass(iq.fm_demodulate(z,2.8),4.2e6),iq_hash)
        run('gated'+str(bits), bits, iq.lowpass(iq.fm_demodulate_pll(z,bits,2.8),4.2e6),iq_hash)
        if args.cn is None or (args.cn == 12 and bits == 4):
            run('wrong_sign'+str(bits), bits,
                iq.lowpass(iq.fm_demodulate_pll(z,bits,2.8,loop_sign=-1),4.2e6),iq_hash)
    result['elapsed_seconds'] = time.monotonic()-started
    result['complete'] = True
    (args.out/'results.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
