"""rtl/cvbs_capture.v against model/cvbs_capture_ref.py: the same 6-bit composite samples at 40 MS/s
must give the same mixer entries, bit for bit (task 64, hub docs/design/2026-10-24/DIGITAL_INGANG.md).

Run:  .venv/bin/python -m pytest -q gateware/sim/test_cvbs_capture.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import cvbs_capture_ref as m  # noqa: E402


def run(samples, comb=True, tag='run'):
    """Entries the RTL emits for the samples, decoded like the model's tuples."""
    work = HERE / 'build' / 'cvbs_capture' / tag
    work.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    hexfile = work / 'samples.hex'
    outfile = work / 'entries.txt'
    m.write_hex(hexfile, samples)
    defines = [] if comb else ['-DCVBS_COMB=0']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), *defines, '-o', 'sim.vvp', '-s', 'tb_cvbs_capture',
                    str(HERE / 'tb_cvbs_capture.v'), str(GW / 'rtl' / 'cvbs_capture.v')],
                   cwd=work, env=env, check=True)
    res = subprocess.run(['vvp', '-n', 'sim.vvp', f'+hex={hexfile}', f'+out={outfile}', f'+n={len(samples)}'],
                         cwd=work, env=env, check=True, capture_output=True, text=True)
    assert re.search(r'RESULT samples=\d+ entries=\d+', res.stdout), res.stdout[-500:]
    out = []
    for line in outfile.read_text().split():
        v = int(line, 16)
        field = (v >> 51) & 1
        ln = (v >> 41) & 0x3FF
        if (v >> 52) & 1:
            out.append(('marker', field, ln, (v >> 21) & 0xFFFFF, (v >> 17) & 0xF, (v >> 1) & 0xFFF))
        else:
            out.append(('word', field, ln, (v >> 32) & 0x1FF, v & 0xFFFFFFFF))
    return out


def first_difference(got, exp):
    for i, (g, e) in enumerate(zip(got, exp)):
        if g != e:
            return f'entry {i}: rtl {g}, model {e}'
    if len(got) != len(exp):
        return f'{len(got)} entries from the rtl, {len(exp)} from the model'
    return None


def test_gain_table_matches_model():
    """rtl/cvbs_gain.vh is the model's table (regenerate with cvbs_capture_ref.write_gain_vh)."""
    vh = (GW / 'rtl' / 'cvbs_gain.vh').read_text()
    assert vh.endswith(m.gain_vh())


def test_clean_frame_matches_model():
    """One clean NTSC frame of grey bars: every word and marker as the model, both fields numbered
    from 0 after their vertical blanking, 360 words per line, lengths within the mixer's tolerance."""
    s = m.synth(m.bars, frames=1)
    exp = m.expected_entries(s)
    got = run(s, tag='clean')
    assert first_difference(got, exp) is None, first_difference(got, exp)
    markers = [e for e in got if e[0] == 'marker']
    assert len(markers) == 486                                   # 244 + 242 (the last line's marker needs the next start)
    assert all(abs(e[5] - 1716) <= 2 for e in markers)
    assert not any(e[4] for e in markers)
    fields = [e[1] for e in markers]
    assert fields[:244] == [fields[0]] * 244 and fields[244] != fields[0]
    assert [e[2] for e in markers[:244]] == list(range(244))


def test_noise_and_faults_match_model():
    """Noise of one code and two faults (a missing line sync, a short line): the same entries as
    the model; the missing sync is one flywheel line flagged bad, the phase jump re-locks within
    MISS_MAX + 2 lines, both numberings go on."""
    s = m.synth(m.bars, frames=1, noise=1.0, seed=3, faults={100: 'nosync', 300: 'short'})
    exp = m.expected_entries(s)
    got = run(s, tag='faults')
    assert first_difference(got, exp) is None, first_difference(got, exp)
    markers = [e for e in got if e[0] == 'marker']
    bad = [(e[1], e[2]) for e in markers if e[4]]
    assert (markers[0][1], 80) in bad                            # line 100 = active line 80 of the first field
    assert len(bad) <= 1 + m.MISS_MAX + 2
    assert len(markers) == 486


def test_negative_control_comb_off():
    """The RTL without the comb differs from the model with it on a two-line stream whose lines
    differ (the comparison bites), and equals the model without the comb."""
    def alt(ln, x):
        return 16 + (x * 219 // 720 if ln % 2 else 235 - x * 219 // 720)
    s = m.synth(alt, frames=1)
    got = run(s, comb=False, tag='nocomb')
    assert first_difference(got, m.expected_entries(s, comb=True)) is not None
    diff = first_difference(got, m.expected_entries(s, comb=False))
    assert diff is None, diff


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
