"""M6's development command channel (puck_ui.v, DEVCMD = 1) against model/m6_cmd_ref.py.

sim/tb_m6_cmd.v sends one byte of every command, and two that are not commands, to puck_ui's uart_rxd at the
log's rate, far enough apart that a heartbeat log line falls between any two. Checked per command:
  * the receiver delivers every byte, and exactly the commands count (cmd);
  * every log line is the 101-byte DEVCMD line, read by tools/snowlog.py, and shows the model's state after
    the commands received before the line started (channel, MHz, mode, filter, latency, HOLD, OSD, echo,
    count); between any two commands there is a line, so each command shows in the next line;
  * the module's outputs follow: low_lat, filter_vcr with one filter_changed pulse per T / V, mode and
    force_bad, ch_hold, osd_show, band/channel with one RX5808 write per effective + or - (none for + under
    HOLD), dump_req for D and F;
  * "?" gives one status line, the model's, after the line being sent and before the next one.
Channel steps cross a band boundary both ways (F8 -> R1 -> F8).

Negative controls:
  * DEVCMD = 0 with the same bytes: 89-byte lines, nothing changes, no status line, no dump request;
  * copies of rtl/puck_ui.v with one command left without effect (LOW, the filter request, the RX5808 write
    of +, the status line, the count, OSD forcing), each of which must fail the check.

Run: .venv/bin/python -m pytest -q gateware/sim/test_m6_cmd.py"""
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
sys.path.insert(0, str(GW / 'tools'))
import m6_cmd_ref as ref  # noqa: E402
import snowlog  # noqa: E402

BAUD = 62_500                   # tb_m6_cmd.v
GAP = 30_000                    # clocks between commands (1 MHz clock; a heartbeat line every 20 ms)
SEQ = '?LBVTabm+++++-H+h-Oo*DFx\n?'
END = 20 * 1000 + GAP * (len(SEQ) + 2)
DEC = [dict(init=1, err=0, alt=1, valid=1, st=0x100E, misc_ok=1, misc=0x0D, ri=0),
       dict(init=1, err=1, alt=0, valid=0, st=0, misc_ok=0, misc=0, ri=3)]

MUTANTS = {
    'low_without_effect': ([('"L": low_lat <= 1\'b1;', '"L": ;')], 'low_lat|line'),
    'vcr_without_request': ([('"V": begin filter_vcr <= 1\'b1; filter_changed <= 1\'b1; end',
                              '"V": filter_vcr <= 1\'b1;')], 'filter_changed'),
    'step_without_rx5808_write': ([('                      || cmd_step;', '                      ;')], 'RX5808'),
    'no_status_line': ([('"?": q_req <= 1\'b1;', '"?": ;')], 'status line'),
    'not_counted': ([('cmd_count <= cmd_count + 1\'b1;', 'cmd_count <= cmd_count;')], 'line'),
    'osd_not_forced': ([("assign osd_show = (osd_force == 2'd1) || (osd_force != 2'd2 && ((osd_ms != 0) || "
                         "(page != P_FLY)));", "assign osd_show = (osd_ms != 0) || (page != P_FLY);")], 'osd'),
}


def run(name, devcmd=1, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    ui = (GW / 'rtl' / 'puck_ui.v').read_text()
    for old, new in MUTANTS[mutant][0] if mutant else []:
        assert ui.count(old) == 1, (mutant, old)
        ui = ui.replace(old, new)
    (work / 'puck_ui.v').write_text(ui)
    first = 25_000                                   # after the first heartbeat line
    words = [((first if i == 0 else GAP - 160) << 8) | ord(c) for i, c in enumerate(SEQ)]
    (work / 'cmds.hex').write_text(''.join(f'{w:08x}\n' for w in words))
    src = [HERE / 'tb_m6_cmd.v', *[p for p in sorted((GW / 'rtl').glob('*.v')) if p.name != 'puck_ui.v'],
           work / 'puck_ui.v']
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_m6_cmd',
                    f'-Ptb_m6_cmd.DEVCMD={devcmd}', f'-Ptb_m6_cmd.END_CLK={END}', *map(str, src)],
                   cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True,
                         text=True).stdout
    assert re.search(r'^END \d+$', out, re.M), out[-2000:]
    return parse(out)


def parse(out):
    ev = {'send': [], 'rx': [], 'sig': [], 'spi': [], 'dump': [], 'lines': []}
    cur, t0 = [], None
    for line in out.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == 'SEND':
            ev['send'].append((int(p[1]), int(p[2], 16)))
        elif p[0] == 'RX':
            ev['rx'].append((int(p[1]), int(p[2], 16), p[3] == '1'))
        elif p[0] == 'SIG':
            ev['sig'].append((int(p[1]), p[2], int(p[3])))
        elif p[0] == 'SPI':
            ev['spi'].append(int(p[1]))
        elif p[0] == 'DUMP':
            ev['dump'].append((int(p[1]), int(p[2])))
        elif p[0] == 'TX':
            if not cur:
                t0 = int(p[1])
            cur.append(int(p[2], 16))
            if cur[-1] == 0x0A:
                ev['lines'].append((t0, bytes(cur).decode('ascii', 'replace')))
                cur = []
    return ev


def states(rx, devcmd=True):
    s = [ref.initial()]
    for _, byte, _ in rx:
        s.append(ref.apply(s[-1], byte, devcmd=devcmd))
    return s


def sig(r, name):
    return [(t, v) for t, n, v in r['sig'] if n == name]


def check(r, devcmd=True):
    sent = [b for _, b in r['send']]
    assert sent == [ord(c) for c in SEQ], sent
    if devcmd:
        assert [b for _, b, _ in r['rx']] == sent, ('receiver', r['rx'])
        assert [c for _, _, c in r['rx']] == [b in ref.COMMANDS for b in sent], ('cmd', r['rx'])
    rx = [x for x in r['rx'] if x[2]] if devcmd else []
    st = states(rx)
    t_rx = [t for t, _, _ in rx]
    s_lines = [(t, ln) for t, ln in r['lines'] if ln.startswith('S ')]
    q_lines = [(t, ln) for t, ln in r['lines'] if ln.startswith('Q ')]
    assert len(s_lines) + len(q_lines) == len(r['lines']), ('line', r['lines'])
    want_len = ref.BASE_LEN + (ref.CMD_LEN if devcmd else 0) + 2
    for t, ln in s_lines:
        assert len(ln) == want_len, ('line length', t, ln)
        rec = snowlog.parse(ln.strip())
        assert rec is not None, ('line', t, ln)
        k_lo = sum(1 for x in t_rx if x + 3 <= t)
        k_hi = sum(1 for x in t_rx if x <= t)
        ok = []
        for k in range(k_lo, k_hi + 1):
            s = st[k]
            fields = ref.log_fields(s)
            same = all(rec[f] == v for f, v in fields.items())
            if devcmd:
                same = same and ln[ref.BASE_LEN:-2] == ref.suffix(s)
            else:
                same = same and 'lat' not in rec
            ok.append(same)
        assert any(ok), ('line', t, ln, [ref.log_fields(st[k]) for k in range(k_lo, k_hi + 1)],
                         [ref.suffix(st[k]) for k in range(k_lo, k_hi + 1)])
    for a, b in zip(t_rx, t_rx[1:]):             # a line between any two commands: each shows in the next line
        assert any(a + 3 < t < b for t, _ in s_lines), ('line between commands', a, b)
    # the status line: one per "?", after the line being sent, before the next one
    q_rx = [t for t, b, _ in rx if b == ord('?')]
    assert len(q_lines) == len(q_rx), ('status line', q_lines, q_rx)
    for tq, (t, ln) in zip(q_rx, q_lines):
        assert ln.rstrip('\r\n') == ref.q_line(DEC, baud=BAUD), ('status line', ln, ref.q_line(DEC, baud=BAUD))
        nxt = [ts for ts, _ in s_lines if ts > tq]
        assert tq < t and (not nxt or t < nxt[0]), ('status line', tq, t, nxt[:1])
        assert t - tq < 17_000, ('status line', tq, t)
    # outputs
    final = st[-1]

    def transitions(name, attr):
        want, prev = [], getattr(st[0], attr)
        for s in st[1:]:
            v = getattr(s, attr)
            if v != prev:
                want.append(v)
            prev = v
        return want
    assert [v for _, v in sig(r, 'low_lat')] == transitions('low_lat', 'low_lat'), ('low_lat', sig(r, 'low_lat'))
    assert [v for _, v in sig(r, 'filter_vcr')] == transitions('filter_vcr', 'filter_vcr'), ('filter_vcr',)
    assert len(sig(r, 'filter_changed')) == final.filter_req, ('filter_changed', sig(r, 'filter_changed'))
    assert [v for _, v in sig(r, 'mode')] == transitions('mode', 'mode'), ('mode', sig(r, 'mode'))
    want_fb, prev = [], ref.force_bad(st[0])
    for s in st[1:]:
        if ref.force_bad(s) != prev:
            want_fb.append(ref.force_bad(s))
        prev = ref.force_bad(s)
    assert [v for _, v in sig(r, 'force_bad')] == want_fb, ('force_bad', sig(r, 'force_bad'))
    assert [v for _, v in sig(r, 'ch_hold')] == transitions('hold', 'hold'), ('ch_hold', sig(r, 'ch_hold'))
    want_ch, prev = [], (st[0].band, st[0].ch)
    for s in st[1:]:
        if (s.band, s.ch) != prev:
            want_ch.append(s.band * 8 + s.ch)
        prev = (s.band, s.ch)
    assert [v for _, v in sig(r, 'chan')] == want_ch, ('chan', sig(r, 'chan'))
    # RX5808: the first write after reset (RX_FIRST_MS), then one per effective step, within 1 ms of it
    assert len(r['spi']) == 1 + final.spi_writes, ('RX5808 writes', r['spi'], final.spi_writes)
    steps = [t_rx[k] for k in range(len(rx)) if st[k + 1].spi_writes > st[k].spi_writes]
    for ts, tw in zip(steps, r['spi'][1:]):
        assert 0 < tw - ts < 5000, ('RX5808 write', ts, tw)
    # OSD: visible OSD_MS after reset, then as forced
    osd = sig(r, 'osd_show')
    want_osd, prev = [], 1
    auto_off_at = 2000
    events = sorted([(auto_off_at, None)] + [(t_rx[k], k + 1) for k in range(len(rx))], key=lambda e: e[0])
    auto, cur = 1, st[0]
    for t, k in events:
        if k is None:
            auto = 0
        else:
            cur = st[k]
        v = int(ref.osd_on(cur, auto))
        if v != prev:
            want_osd.append(v)
        prev = v
    assert [v for _, v in osd] == want_osd, ('osd', osd, want_osd)
    want_dump = [{'D': 1, 'F': 2}[c] for c in final.dumps]
    assert [v for _, v in r['dump']] == want_dump, ('dump', r['dump'])


def test_m6_command_channel():
    check(run('tb_m6_cmd'))


def test_m6_command_channel_off_ignores_everything():
    """Negative control: DEVCMD = 0, same bytes."""
    r = run('tb_m6_cmd_off', devcmd=0)
    check(r, devcmd=False)
    assert not r['rx'] and not r['dump'] and not any(ln.startswith('Q') for _, ln in r['lines'])


@pytest.mark.parametrize('mutant', sorted(MUTANTS))
def test_m6_command_channel_negative_control(mutant):
    r = run(f'tb_m6_cmd_{mutant}', mutant=mutant)
    with pytest.raises(AssertionError, match=MUTANTS[mutant][1]):
        check(r)


def test_model_channel_steps_wrap():
    """+ from L8 gives A1, - from A1 gives L8; HOLD and a scan refuse a step."""
    s = ref.initial(band=5, ch=7)
    assert (ref.apply(s, ord('+')).band, ref.apply(s, ord('+')).ch) == (0, 0)
    s = ref.initial(band=0, ch=0)
    assert (ref.apply(s, ord('-')).band, ref.apply(s, ord('-')).ch) == (5, 7)
    held = ref.apply(s, ord('H'))
    assert (ref.apply(held, ord('+')).band, ref.apply(held, ord('+')).ch) == (0, 0)
    assert ref.apply(s, ord('+'), scan_busy=True).spi_writes == 0
    assert ref.apply(s, ord('x')) == s
