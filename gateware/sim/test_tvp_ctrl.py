"""tvp_ctrl (I2C bring-up, status polling and re-initialisation of our own
TVP5150AM1s) against behavioural I2C slaves.

Start-up: RESETB pulse, six register writes per decoder in a fixed order (03h last), status
from 88h/89h. Afterwards 03h is read back in every poll round: a decoder whose
registers are back at their defaults gets the list again, and that is counted.
Controls: an undisturbed run counts nothing and writes nothing more; a decoder
that ignores writes, or an SDA line shorted low, makes the counter stop at 255
instead of wrapping; a decoder that joins late is brought up, and the error
flag follows it on and off the bus.

Run: .venv/bin/python -m pytest -q gateware/sim/test_tvp_ctrl.py"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(HERE))
import tvp_status  # noqa: E402

INIT = ('0d', 'fc', '47')           # 03h, 04h, 0Dh after the init list (00h = 00h is the default anyway)
SET = ('30', '00')                  # 02h (TV/VCR mode: TV), 28h (video standard: autoswitch, also the default)
INIT_LIST = [('00', '00'), ('04', 'fc'), ('0d', '47'), ('28', '00'), ('02', '30'), ('03', '0d')]
N = len(INIT_LIST)
ST_NTSC, ST_PAL = '000e', '306e'    # {89h, 88h} of the two decoder models: healthy NTSC and healthy PAL


def test_status_words_mean_what_the_datasheet_says():
    """The status words used by the models, the tests and BRINGUP.md, against the bit
    tables of SLES209E (sim/tvp_status.py)."""
    ntsc, pal = int(ST_NTSC, 16), int(ST_PAL, 16)
    assert tvp_status.healthy(ntsc, 'ntsc') and not tvp_status.healthy(ntsc, 'pal')
    assert tvp_status.healthy(pal, 'pal') and not tvp_status.healthy(pal, 'ntsc')
    # bits that vary on a good signal: field (89h bit 4), PAL switch (89h bit 5), peak white, VCR
    assert all(tvp_status.healthy(st, 'ntsc') for st in (0x000E, 0x100E, 0x008E, 0x000F))
    assert all(tvp_status.healthy(st, 'pal') for st in (0x006E, 0x106E, 0x206E, 0x306E))
    # negative controls: the words used here before. 402E is 50 Hz with the weak-signal flag,
    # 0006 is 60 Hz without colour lock; and no lock at all
    old = tvp_status.decode(0x402E)
    assert old['field_50hz'] and old['weak_signal'] and not old['line_alternating']
    assert not tvp_status.healthy(0x402E, 'ntsc') and not tvp_status.healthy(0x402E, 'pal')
    assert not tvp_status.healthy(0x0006, 'pal') and not tvp_status.healthy(0x0006, 'ntsc')
    assert not tvp_status.healthy(0x0000, 'ntsc')


KEEP_VALID = ("dev_err[di] <= 1'b1; status_valid[di] <= 1'b0; st <= S_NEXT;", "dev_err[di] <= 1'b1; st <= S_NEXT;")


def run(present1, split=0, scenario=0, alter=None):
    """Returns the testbench's RESULT line as a dict, and its MID line (or None).
    alter: (text, replacement) in a copy of tvp_ctrl.v (negative controls)."""
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    # one build directory per alteration: the negative controls may run in separate processes at once
    work = HERE / 'build' / f'tb_tvp_ctrl_{present1}{split}{scenario}{"_alt" + hashlib.md5(alter[1].encode()).hexdigest()[:6] if alter else ""}'
    work.mkdir(parents=True, exist_ok=True)
    ctrl = GW / 'rtl' / 'tvp_ctrl.v'
    if alter:
        text = ctrl.read_text()
        assert text.count(alter[0]) == 1
        ctrl = work / 'tvp_ctrl.v'
        ctrl.write_text(text.replace(*alter))
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_tvp_ctrl', f'-Ptb_tvp_ctrl.PRESENT1={present1}',
                    f'-Ptb_tvp_ctrl.SPLIT={split}', f'-Ptb_tvp_ctrl.SCENARIO={scenario}',
                    str(GW / 'rtl' / 'i2c_master.v'), str(ctrl),
                    str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_tvp_ctrl.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    line = next(l for l in out.splitlines() if l.startswith('RESULT'))
    assert 'timeout' not in line, out[-2000:]
    mid = next((l for l in out.splitlines() if l.startswith('MID')), None)
    fields = lambda l: dict(re.findall(r'(\w+)=(\w+)', l))
    r = fields(line)
    r['log'] = re.findall(r'^I2C W (\w\w) (\w\w)$', out, re.M)       # decoder 0's writes, in order
    return r, fields(mid) if mid else None


def test_two_decoders():
    r, _ = run(1)
    assert r['reset_low'] == '1' and r['reset_falls'] == '1'
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_04'], r['s0_0d'], r['s0_00']) == (*INIT, '00')
    assert (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT
    assert (r['s0_02'], r['s0_28']) == SET and (r['s1_02'], r['s1_28']) == SET
    assert r['s0_writes'] == str(N) and r['s1_writes'] == str(N)    # nothing is written again
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL and r['valid'] == '3'
    assert r['reinit0'] == '0' and r['reinit1'] == '0'
    assert int(r['rounds0']) >= 3 and int(r['rounds1']) >= 3 and r['lost0'] == '0' and r['lost1'] == '0'


def test_missing_decoder_flagged():
    r, _ = run(0)
    assert r['err'] == '2'                      # decoder 1 (5Dh) did not acknowledge
    assert (r['s0_03'], r['s0_04'], r['s0_0d']) == INIT
    assert r['st0'] == ST_NTSC and r['valid'] == '1'
    assert r['reinit0'] == '0' and r['reinit1'] == '0'


def test_same_address_split_sda():
    """Two identical modules (both 5Ch) on separate SDA lines with a shared SCL."""
    r, _ = run(1, split=1)
    assert r['err'] == '0'
    assert (r['s0_03'], r['s0_04'], r['s0_0d']) == INIT and (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT
    assert (r['s0_02'], r['s0_28']) == SET and (r['s1_02'], r['s1_28']) == SET
    assert r['s0_writes'] == str(N) and r['s1_writes'] == str(N)
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL and r['valid'] == '3'


def test_reset_decoder_is_brought_up_again():
    """Decoder 1 loses its registers twice. Each time the list is written again and counted;
    RESETB is not pulsed and decoder 0 is left alone."""
    for split in (0, 1):
        r, mid = run(1, split=split, scenario=1)
        assert (mid['s1_03'], mid['s1_04'], mid['s1_0d']) == INIT and mid['reinit1'] == '1' and mid['s1_writes'] == str(2 * N)
        assert (mid['s1_02'], mid['s1_28']) == SET
        assert (r['s1_03'], r['s1_04'], r['s1_0d']) == INIT and r['reinit1'] == '2' and r['s1_writes'] == str(3 * N)
        assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['s0_03'] == '0d'
        assert r['err'] == '0' and r['reset_falls'] == '1'


def test_reinit_counter_saturates():
    """A decoder that acknowledges writes but keeps 03h = 01h is retried in every poll round
    (more than 255 of them in this run): the counter stops at 255."""
    r, _ = run(1, scenario=2)
    assert r['s1_03'] == '01' and r['reinit1'] == '255'
    assert int(r['s1_writes']) > N * 256
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['err'] == '0'
    assert r['st0'] == ST_NTSC and r['st1'] == ST_PAL            # status polling goes on
    assert r['valid'] == '1'                                     # ... but decoder 1 is never up


def test_sda_shorted_low_shows_in_the_counter():
    """An SDA line stuck low reads as acknowledge and as data 00h (i2c_master cannot tell), so
    the error flag stays clear. What gives it away is status 0000 with the counter at 255."""
    r, _ = run(1, split=1, scenario=4)
    assert r['err'] == '0' and r['st1'] == '0000' and r['reinit1'] == '255' and r['s1_writes'] == '0'
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N) and r['st0'] == ST_NTSC
    assert r['valid'] == '1'                                     # 03h never reads 0Dh: decoder 1 never valid


@pytest.mark.parametrize('scenario', [5, 6, 7])
def test_failed_poll_round_is_not_valid(scenario):
    """Decoder 1 refuses 88h, 89h or 03h in one poll round; the other reads of that round
    succeed (review 2026-10-06, F2: a NACK on 88h was hidden by the ACK on 89h). Right after
    the round its status is not valid and the error flag is set; the words from before stay.
    The next whole round makes it valid again. A refused 03h is not a reset decoder."""
    r, mid = run(1, scenario=scenario)
    assert mid['err'] == '2' and mid['valid'] == '1' and mid['st1'] == ST_PAL, mid
    assert r['err'] == '0' and r['valid'] == '3' and r['st1'] == ST_PAL and r['st0'] == ST_NTSC, r
    assert r['reinit1'] == '0' and r['s1_writes'] == str(N)


def test_failed_poll_round_check_is_tested():
    """Negative control: a copy of tvp_ctrl.v that sets the error flag but leaves the status
    valid after a failed round is caught."""
    _, mid = run(1, scenario=5, alter=KEEP_VALID)
    assert mid['err'] == '2' and mid['valid'] == '3', mid


def test_late_decoder_and_error_flag():
    """Decoder 1 is not on the bus at start (error flag set), joins later (brought up, flag
    cleared: it is no longer sticky) and leaves again (flag set)."""
    r, mid = run(0, scenario=3)
    assert mid['err'] == '0' and mid['reinit1'] == '1' and mid['s1_writes'] == str(N)
    assert (mid['s1_03'], mid['s1_04'], mid['s1_0d']) == INIT and mid['valid'] == '3' and mid['st1'] == ST_PAL
    assert r['err'] == '2' and r['reinit1'] == '1' and r['s1_writes'] == str(N)
    assert r['reinit0'] == '0' and r['s0_writes'] == str(N)


WRONG_OP_MODE = ("parameter [7:0] OP_MODE = 8'h30", "parameter [7:0] OP_MODE = 8'h20")
WRONG_ORDER = ("3'd3: init_rom = {8'h28, VIDEO_STD};\n            3'd4: init_rom = {8'h02, OP_MODE};",
               "3'd3: init_rom = {8'h02, OP_MODE};\n            3'd4: init_rom = {8'h28, VIDEO_STD};")


def init_list_ok(r):
    return r['log'] == INIT_LIST and (r['s0_02'], r['s0_28']) == SET


def test_init_list_in_order():
    """Decoder 0 gets exactly the init list, in order, once: 28h (autoswitch) and 02h (TV mode)
    are written explicitly, 03h last (SLES209E 3.21.3, 3.21.32; README under M4)."""
    r, _ = run(1)
    assert r['log'] == INIT_LIST, r['log']
    assert init_list_ok(r)


@pytest.mark.parametrize('alter', [WRONG_OP_MODE, WRONG_ORDER], ids=['op_mode_vcr', 'order'])
def test_init_list_check_is_tested(alter):
    """Negative controls: 02h = 20h (VCR mode instead of TV), or 02h written before 28h."""
    r, _ = run(1, alter=alter)
    assert not init_list_ok(r), r['log']


WRONG_BIT = ("lost_lock[di] <= p88[4];", "lost_lock[di] <= p88[3];")


def test_lost_lock_flag():
    """Decoder 0 sets 88h bit 4 ("lost lock since 88h was last read") once. The next whole round
    reports it with its round_ok pulse, and only that round: reading 88h cleared the bit. Decoder 1
    never sets it (its 88h is 6Eh)."""
    r, _ = run(1, scenario=8)
    assert r['lost0'] == '1' and r['lost1'] == '0' and int(r['rounds0']) >= 3, r
    assert r['st0'] == ST_NTSC and r['valid'] == '3'


def test_lost_lock_bit_is_checked():
    """Negative control: bit 3 (colour lock, set on a healthy signal) taken for bit 4."""
    r, _ = run(1, scenario=8, alter=WRONG_BIT)
    assert r['lost0'] != '1' or r['lost1'] != '0', r
