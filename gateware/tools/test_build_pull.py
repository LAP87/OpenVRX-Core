"""build.sh's pull test (PULL=UP or PULL=DOWN): the weak pulls go on bits 0-6 of
each decoder bus and nowhere else.

Bit 7 is left alone: YOUT7 is the TVP5150AM1's I2C address strap, sampled at
reset (SLES209E table 2-1, I2CSEL). A pull-up against the module's own strap
resistor can move the decoder to the other address, and the probe then shows
"i2c NA" for a decoder that is wired correctly.

Runs the sed line taken out of build.sh on the constraints of m3_probe.
Negative control: the same line without the bit range also changes bit 7.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
DATA_BITS = {f'tvp{d}_d[{i}]' for d in 'ab' for i in range(7)}


def sed_line():
    lines = [l.strip() for l in (GW / 'build.sh').read_text().splitlines() if 'PULL_MODE=NONE/PULL_MODE=$PULL' in l]
    assert len(lines) == 1, lines
    return lines[0]


def pulled(tmp, line, pull):
    """Ports whose constraint line the sed line changed; every changed line must now carry the pull."""
    before = (GW / 'boards' / 'tangnano20k.cst').read_text() + (GW / 'boards' / 'm3_probe.cst').read_text()
    (tmp / 'm3_probe.cst').write_text(before)
    subprocess.run(['bash', '-c', f'PULL={pull}; top=m3_probe; {line}'], cwd=tmp, check=True)
    after = (tmp / 'm3_probe.cst').read_text()
    assert len(before.splitlines()) == len(after.splitlines())
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert all(b == a.replace('PULL_MODE=NONE', f'PULL_MODE={pull}') for a, b in changed), changed
    return {b.split('"')[1] for _, b in changed}


@pytest.mark.skipif(shutil.which('bash') is None or shutil.which('sed') is None, reason='needs bash and sed')
def test_pull_leaves_the_address_strap_alone(tmp_path):
    line = sed_line()
    for pull in ('UP', 'DOWN'):
        assert pulled(tmp_path, line, pull) == DATA_BITS
    old = line.replace(r'\[[0-6]\]', r'\[')
    assert old != line
    assert pulled(tmp_path, old, 'UP') == DATA_BITS | {'tvpa_d[7]', 'tvpb_d[7]'}
