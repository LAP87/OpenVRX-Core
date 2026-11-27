"""Model-only regression for #29. No claim of RTL or physical receiver behaviour."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import cvbs_capture_ref as cv
import pair_align_ref as pa


BASELINE_WORDS = [84600, 86400, 0, 0, 85680, 85320]


@pytest.mark.parametrize('seed', range(1, 7))
def test_original_noise_table_and_opt_in_pulse_end(seed):
    """The original failure stays visible. The opt-in proposal recovers 243 complete lines
    for each of the six published seeds; default Capture still behaves like the original RTL."""
    s = pa.pair_stream(cv.synth(cv.bars, frames=1, levels=(23, 31, 62), noise=2.0, seed=seed))
    original = cv.Capture(white_x8=cv.WHITE_X8_C5VRX)
    original.run(s)
    assert sum(e[0] == 'word' for e in original.entries) == BASELINE_WORDS[seed - 1]
    proposal = cv.Capture(white_x8=cv.WHITE_X8_C5VRX, robust_pulses=True)
    proposal.run(s)
    words = [e for e in proposal.entries if e[0] == 'word']
    assert len(words) == 87480
    assert {e[1] for e in words} == {1}
    assert {e[2] for e in words} == set(range(243))
    assert all([e[3] for e in words[i:i + 360]] == list(range(360))
               for i in range(0, len(words), 360))
    assert proposal.numbered and proposal.locked
    assert proposal.paired_input and proposal.pulse_end_confirm == 16


def test_clean_unpaired_entries_and_lock_trace_are_unchanged():
    # The issue names ntsc_clean_frame.hex, but make_vectors.py makes that fixture
    # as 8-bit BT.656, not the 6-bit composite samples Capture accepts. Use a real
    # composite frame here; the named fixture gets a separate non-picture guard below.
    s = cv.synth(cv.bars, frames=1)
    original, proposal = cv.Capture(), cv.Capture(robust_pulses=True)
    original.run(s)
    proposal.run(s)
    assert original.entries and original.entries == proposal.entries
    assert original.lock_trace == proposal.lock_trace
    assert original.boot_rejects == proposal.boot_rejects


def test_named_bt656_fixture_is_not_misreported_as_composite_coverage():
    fixture = Path(__file__).parents[1]/'vectors/ntsc_clean_frame.hex'
    s = [int(v, 16) for v in fixture.read_text().split()]
    assert max(s) > 63
    original, proposal = cv.Capture(), cv.Capture(robust_pulses=True)
    original.run(s)
    proposal.run(s)
    assert not original.entries and not proposal.entries


def test_bench_bootstrap_entries_and_rejections_are_unchanged():
    fixture = Path(__file__).parents[1]/'vectors/digin_bench_2026-10-28_1251.hex'
    x = [int(v, 16) for v in fixture.read_text().split()]
    s = [50] * (30 * cv.H_NOM) + x + x
    original = cv.Capture(white_x8=cv.WHITE_X8_C5VRX)
    proposal = cv.Capture(white_x8=cv.WHITE_X8_C5VRX, robust_pulses=True)
    original.run(s)
    proposal.run(s)
    assert original.entries == proposal.entries
    assert original.lock_trace == proposal.lock_trace
    assert original.boot_rejects == proposal.boot_rejects >= 1
    assert (original.sync, original.blank) == (proposal.sync, proposal.blank)
    assert proposal.locked and proposal.levels_fresh


@pytest.mark.parametrize('width,expected_broad', [(cv.T_BROAD-3, False), (cv.T_BROAD, True)])
def test_end_confirmation_does_not_make_a_short_pulse_broad(width, expected_broad):
    """Longer end qualification must not count its trailing high samples as extra sync width.
    A real short pulse remains short; a real broad pulse still arms the vertical countdown."""
    for enabled in (False, True):
        c = cv.Capture(avg=1, robust_pulses=enabled)
        c.run([20, 20, 22, 22]*1024)  # confirm pairs before testing the proposed end qualifier
        assert c.pulse_end_confirm == (16 if enabled else 3)
        c.run([20]*20 + [4]*width + [20]*40)
        assert c.pulse_was_broad is expected_broad
        assert (c.countdown >= 0) is expected_broad


def test_flat_paired_level_never_produces_a_picture():
    c = cv.Capture(robust_pulses=True)
    c.run([31]*(30*cv.H_NOM))
    assert not c.locked and not c.entries and not c.numbered


@pytest.mark.parametrize('phase', [0, 1])
def test_pair_evidence_is_required_on_either_parity(phase):
    c = cv.Capture(robust_pulses=True)
    x = [20, 20, 22, 22]*2048
    if phase == 0:
        x.insert(0, x[0])
    c.run(x)
    assert c.paired_input and c.pulse_end_confirm == 16
    c.run([20, 21, 22, 23]*2048)
    assert not c.paired_input and c.pulse_end_confirm == 3
