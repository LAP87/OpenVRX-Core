"""First fixed-parameter comparison for Core #28; no RF or FPGA test."""
import argparse
import json
from pathlib import Path
import time

import iq_demod_ref as iq


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.out.exists():
        ap.error('refusing to overwrite a comparison')
    result = dict(schema=1, model_only=True, hardware=False, phase_lut_ideal=True,
                  kp='3/8', ki='1/32', power_iir='1/256', weight_max=2, cases=[])
    for bits in [4, 7]:
        for cn in [4, 8, 12]:
            started = time.monotonic()
            row = iq.compare_discriminators(cn, bits)
            row['elapsed_seconds'] = time.monotonic()-started
            # This is also a compatibility check against the untouched original API.
            old_snr, old_sync = iq.run_case(cn, bits, lines=60)
            assert row['metrics']['adjacent'] == dict(luma_snr_db=old_snr, sync_hits=old_sync)
            result['cases'].append(row)
            args.out.write_text(json.dumps(result, indent=2)+'\n')
            print(bits, cn, row['metrics'], 'sync target', row['gated_sync_not_worse'], flush=True)


if __name__ == '__main__':
    main()
