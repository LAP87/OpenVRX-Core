"""Unknown decoder status counts as bad (dec_bad.v, M4 and M6; hub LOGIKGRANSKNING F4).

sim/tb_dec_lock.v: tvp_ctrl polls two decoder models every POLL_MS as M4/M6 do, dec_bad.v turns
the status into mixer2's ext_bad, and the mixer gets two BT.656 streams in step: A a real picture
(vectors/ntsc_clean_frame.hex), B a flat one, as a free-running decoder may give. While both
report lock, B wins the pairs (less HF energy). Then B reports no lock and refuses 88h in its
next poll round: with the rule of 2026-10-21 no decision uses B's lines once one poll round has
passed after the loss. Negative control: the rule before it (only a valid status without lock is
bad) lets B's lines through while the void round leaves its status unknown.

Run: .venv/bin/python -m pytest -q gateware/sim/test_dec_lock.py"""
import functools
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys.path.insert(0, str(GW / 'model'))
import bt656  # noqa: E402

T_LOSS = 30_000_000             # ns
LINE = 63_556                   # ns, one NTSC line
OLD_RULE = ("    assign bad = {!(status_valid[1] && status1[1] && status1[2]),\n"
            "                  !(status_valid[0] && status0[1] && status0[2])};",
            "    assign bad = {status_valid[1] && !(status1[1] && status1[2]),\n"
            "                  status_valid[0] && !(status0[1] && status0[2])};")


@functools.lru_cache(maxsize=None)
def run(old_rule=False):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / f'tb_dec_lock{"_old" if old_rule else ""}'
    work.mkdir(parents=True, exist_ok=True)
    rule = GW / 'rtl' / 'dec_bad.v'
    if old_rule:
        text = rule.read_text()
        assert text.count(OLD_RULE[0]) == 1
        rule = work / 'dec_bad.v'
        rule.write_text(text.replace(*OLD_RULE))
    flat = work / 'flat_frame.hex'
    bt656.write_hex(flat, bt656.frame_bytes('ntsc', lambda line, x: 0x50) + bt656.line_bytes('ntsc', 1))
    rtl = [GW / 'rtl' / n for n in ('i2c_master.v', 'tvp_ctrl.v', 'chan_capture.v', 'bt656_rx.v', 'async_fifo.v',
                                    'mix_chan.v', 'line_mixer.v', 'snow_stats.v', 'noise_stats.v', 'mixer2.v',
                                    'cdc_sync.v', 'word_packer.v', 'dual_clock_ram.v')]
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_dec_lock',
                    f'-Ptb_dec_lock.T_LOSS_NS={T_LOSS}', *map(str, rtl), str(rule),
                    str(HERE / 'i2c_slave_model.v'), str(HERE / 'tb_dec_lock.v')], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec_a={GW / "vectors" / "ntsc_clean_frame.hex"}',
                          f'+vec_b={flat}'], cwd=work, env=env, check=True, capture_output=True, text=True).stdout
    assert 'RESULT done' in out, out[-2000:]
    return dict(rounds=[(int(t), int(d)) for t, d in re.findall(r'^ROUND (\d+) (\d)$', out, re.M)],
                loss=int(re.search(r'^LOSS (\d+)$', out, re.M)[1]),
                nacked=int(re.search(r'^NACKED (\d+)$', out, re.M)[1]),
                dec=[(int(t), u) for t, u in re.findall(r'^D (\d+) (\d\d)$', out, re.M)])


def b_used_after(r):
    """Decisions that used B's line (B alone or blended) later than one poll round plus two lines after the
    loss, and the round period that window used."""
    rb = [t for t, d in r['rounds'] if d == 1]
    period = max(b - a for a, b in zip(rb, rb[1:]) if b < r['loss'])
    late = [(t, u) for t, u in r['dec'] if t > r['loss'] + period + 2 * LINE and u[0] == '1']
    return late, period


def test_b_wins_while_locked():
    """Before the loss both decoders report lock and B's flat lines win the pairs, so the scenario
    exercises what the rule must stop."""
    r = run()
    before = [u for t, u in r['dec'] if 20_000_000 < t < r['loss']]
    assert len(before) > 100 and sum(u[0] == '1' for u in before) > 0.9 * len(before), before[:20]


def test_no_b_line_after_lock_loss():
    r = run()
    assert r['nacked'] > r['loss']
    late, period = b_used_after(r)
    assert period < 6_000_000, period                    # 88h read at least every 6 ms per decoder
    assert not late, late[:10]
    after = [u for t, u in r['dec'] if t > r['loss'] + period + 2 * LINE]
    assert len(after) > 100 and all(u == '01' for u in after), after[:20]


def test_old_rule_lets_b_through():
    """Negative control: the rule before 2026-10-21 uses B's lines while the void round leaves its status
    unknown."""
    late, _ = b_used_after(run(old_rule=True))
    assert late, 'the old rule should have used B after the loss'
