"""Formal proofs (gateware/formal/run.sh): async FIFO and genlock timing by
k-induction in yosys, each with negative controls that must produce a real
counterexample. About a minute."""
import subprocess
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
BIN = GW.parent / '.venv' / 'bin'


@pytest.mark.skipif(not (BIN / 'yowasp-yosys').exists(), reason='open toolchain not installed')
def test_formal_proofs():
    r = subprocess.run([str(GW / 'formal' / 'run.sh')], capture_output=True, text=True)
    lines = r.stdout.splitlines()
    assert r.returncode == 0, r.stdout + r.stderr
    assert sum(l.startswith('PROVEN') for l in lines) == 3, lines
    assert sum(l.startswith('CONTROL OK') for l in lines) == 5, lines
