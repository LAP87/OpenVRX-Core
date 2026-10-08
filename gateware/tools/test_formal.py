"""Formal proofs (gateware/formal/run.sh): async FIFO, genlock timing, and the clock
domain crossings of fb_backend.v (toggle handshakes, mode bit, line buffer slots) by
k-induction in yosys, each with negative controls that must produce a real
counterexample, including lost sync and a recovery flag that never expires."""
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
    assert sum(l.startswith('PROVEN') for l in lines) == 7, lines
    assert sum(l.startswith('CONTROL OK') for l in lines) == 14, lines
