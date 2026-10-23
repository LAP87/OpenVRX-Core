"""The field dump (rtl/field_dump.v) against model/field_dump_ref.py, and tools/fielddump.py on what comes out.

sim/tb_field_dump.v plays two synthetic word streams on two clocks of their own and asks for a dump of each:
  tap 0: 10 lines, line 4 never sent, fields with field bit 0 and 1 alternating and different content;
  tap 1: 10 lines of one field bit, and every other field a copy whose line 3 breaks off at word 100.
The bytes on txd must equal the model's frames byte for byte: tap 0's lines all from the field the first line
came from (field matching), line 4 and lines 10-11 (beyond the stream) sent as missing, the end frame; tap 1's
line 3 whole. fielddump.py must rebuild both fields exactly and write the PNGs. No byte is sent while the module
does not own the UART.

In the M6 top (sim/tb_top_pins.v, TOP = 6, built with DEVCMD, UART_BAUD and a dump of two lines; video stopped
early, so both lines are missing): the byte "D" on pin 70 starts the dump, the log line being sent ends first, the
three frames (two missing lines, the end frame) come whole on pin 69, then the log resumes and its next line shows
the command (echo 44h, count 1).

Negative controls: one changed data byte and one changed CRC byte in the received stream are each refused by
fielddump.py's CRC check (one CRC error, that line not in the picture); a copy of field_dump.v without field
matching fails the byte comparison.

Run: .venv/bin/python -m pytest -q gateware/sim/test_field_dump.py"""
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
import field_dump_ref as ref  # noqa: E402
import fielddump  # noqa: E402

N_LINES, NL, GONE, BROKEN = 12, 10, 4, 3
MUTANTS = {
    'no_field_matching': ([('if (!match) begin match <= 1\'b1; want_field <= sel ? got_field[1] : got_field[0]; end',
                            '')], 'bytes'),
}


def streams():
    tap0, tap1 = [], []
    lines0 = {(ln, f): ref.line_bytes(ln, f) for ln in range(NL) for f in (0, 1) if ln != GONE}
    lines1 = {(ln, 0): ref.line_bytes(ln, 0, seed=50) for ln in range(NL)}
    for f in (0, 1):                                  # tap 0: two fields, field bit 0 then 1
        for ln in range(NL):
            if ln == GONE:
                continue
            for i, w in enumerate(ref.words(lines0[(ln, f)])):
                gap = 255 if (ln == 0 and i == 0) else 60 if i == 0 else 3
                tap0.append((gap, f << 51 | ln << 41 | i << 32 | w))
    for copy in (0, 1):                               # tap 1: one field, then the same with line 3 broken off
        for ln in range(NL):
            for i, w in enumerate(ref.words(lines1[(ln, 0)])):
                if copy and ln == BROKEN and i == 100:
                    continue
                gap = 255 if (ln == 0 and i == 0) else 60 if i == 0 else 3
                tap1.append((gap, ln << 41 | i << 32 | w))
    return tap0, tap1, lines0, lines1


def run(name, mutant=None):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src_text = (GW / 'rtl' / 'field_dump.v').read_text()
    for old, new in MUTANTS[mutant][0] if mutant else []:
        assert src_text.count(old) == 1, (mutant, old)
        src_text = src_text.replace(old, new)
    (work / 'field_dump.v').write_text(src_text)
    tap0, tap1, lines0, lines1 = streams()
    for fname, entries in (('tap0.hex', tap0), ('tap1.hex', tap1)):
        (work / fname).write_text(''.join(f'{g:02x}{w:014x}\n' for g, w in entries))
    src = [HERE / 'tb_field_dump.v', GW / 'rtl' / 'uart_tx.v', GW / 'rtl' / 'dual_clock_ram.v', work / 'field_dump.v']
    subprocess.run(['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_field_dump',
                    f'-Ptb_field_dump.N_LINES={N_LINES}', *map(str, src)], cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True, capture_output=True,
                         text=True).stdout
    assert re.search(r'^END \d+$', out, re.M), out[-2000:]
    tx = [(int(t), int(b, 16)) for t, b in re.findall(r'^TX (\d+) ([0-9a-f]{2})$', out, re.M)]
    owns = [(int(t), int(v)) for t, v in re.findall(r'^OWNS (\d+) (\d)$', out, re.M)]
    return dict(tx=tx, owns=owns, lines0=lines0, lines1=lines1, work=work)


def split(data):
    """The two dumps: the bytes up to and including the first end frame, and the rest."""
    frames, bad, rest = fielddump.parse(data)
    assert not bad and not rest, ('bytes', bad, rest[:20])
    n_first = sum(1 for f in frames if f['kind'] == 'D')
    cut = 0
    for _ in range(n_first):
        n = (data[cut + 6] << 8) | data[cut + 7]
        cut += 10 + n
    return data[:cut], data[cut:]


def check(r):
    data = bytes(b for _, b in r['tx'])
    windows = list(zip(r['owns'][0::2], r['owns'][1::2]))
    assert [v for _, v in r['owns']] == [1, 0, 1, 0], ('owns', r['owns'])
    for t, _ in r['tx']:
        assert any(on[0] <= t <= off[0] for on, off in windows), ('a byte while not owning the UART', t)
    d0, d1 = split(data)
    field = d0[5] & ref.F_FIELD                       # the field bit of the first line that came
    want0 = ref.expected(N_LINES, r['lines0'], field, 'D')
    want1 = ref.expected(N_LINES, r['lines1'], 0, 'F')
    assert d0 == want0, ('bytes', 'tap 0', len(d0), len(want0), next((i for i, (a, b) in enumerate(zip(d0, want0))
                                                                     if a != b), None))
    assert d1 == want1, ('bytes', 'tap 1', len(d1), len(want1))
    return data, field


def test_field_dump_matches_the_model_and_rebuilds():
    r = run('tb_field_dump')
    data, field = check(r)
    d0, d1 = split(data)
    for part, lines, fb, name in ((d0, r['lines0'], field, 'a'), (d1, r['lines1'], 0, 'b')):
        frames, bad, _ = fielddump.parse(part)
        got, missing, n = fielddump.assemble(frames)
        assert (bad, n) == (0, N_LINES)
        assert got == {ln: d for (ln, f), d in lines.items() if f == fb}
        assert missing == sorted(set(range(N_LINES)) - set(got))
        s = fielddump.write(part, str(r['work'] / name))
        assert s['complete'] and s['crc_errors'] == 0 and len(s['png']) == 2
        assert (r['work'] / f'{name}_y.png').read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    assert fielddump.crc16(b'123456789') == ref.crc16(b'123456789') == 0x29B1   # the CRC catalogue's check value


@pytest.mark.parametrize('where', ['data', 'crc'])
def test_field_dump_negative_control_changed_byte(where):
    """One changed byte in a frame: fielddump.py refuses that frame (CRC), the line is not in the picture."""
    tap0, _, lines0, _ = streams()
    part = ref.expected(N_LINES, lines0, 0, 'D')
    frames, bad, _ = fielddump.parse(part)
    assert bad == 0
    pos = 8 + 700 if where == 'data' else 8 + ref.LEN        # inside line 0's data, or its CRC high byte
    broken = bytearray(part)
    broken[pos] ^= 0x10
    frames, bad, _ = fielddump.parse(bytes(broken))
    got, _, _ = fielddump.assemble(frames)
    assert bad == 1 and 0 not in got and 1 in got, (bad, sorted(got))


@pytest.mark.parametrize('mutant', sorted(MUTANTS))
def test_field_dump_negative_control(mutant):
    r = run(f'tb_field_dump_{mutant}', mutant)
    with pytest.raises(AssertionError, match=MUTANTS[mutant][1]):
        check(r)


TOP_BAUD = 33_750                                     # CLK_HZ 135 000 / 4: four board clocks per bit


def run_top(name):
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    work = HERE / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    src = [HERE / 'gowin_prim_stubs.v', HERE / 'i2c_slave_model.v', HERE / 'sdram_model.v', HERE / 'tb_top_pins.v',
           *sorted((GW / 'rtl').glob('*.v')), GW / 'top' / 'm6_puck_proto.v']
    params = dict(TOP=6, CLK_HZ=135_000, T_B_NS=300_000, T_LOCK_NS=0, T_END_NS=10_400_000, SDRAM=0)
    subprocess.run(['iverilog', '-g2012', '-I', str(GW / 'rtl'), '-o', 'sim.vvp', '-s', 'tb_top_pins',
                    '-DDEVCMD=1', f'-DUART_BAUD={TOP_BAUD}', '-DDUMP_LINES=2',
                    *[f'-Ptb_top_pins.{k}={v}' for k, v in params.items()], *map(str, src)],
                   cwd=work, env=env, check=True)
    out = subprocess.run(['vvp', '-n', 'sim.vvp', f'+vec={GW / "vectors" / "ntsc_clean_frame.hex"}',
                          '+pll_stop_ns=600000', '+cmd=44', '+cmd_ns=5050000'], cwd=work, env=env, check=True,
                         capture_output=True, text=True).stdout
    assert 'RESULT done' in out, out[-2000:]
    tx = [(int(t), int(b, 16)) for t, b in re.findall(r'^TXB (\d+) ([0-9a-f]{2})$', out, re.M)]
    cmd = [int(t) for t in re.findall(r'^CMD (\d+) 44$', out, re.M)]
    return tx, cmd


def test_m6_top_dump_path():
    tx, cmd = run_top('tb_field_dump_top')
    assert len(cmd) == 1, cmd
    t_cmd = cmd[0]
    data = bytes(b for _, b in tx)
    frames, bad, _ = fielddump.parse(data)
    assert bad == 0 and [(f['kind'], f['line'], f['missing'], f['end']) for f in frames] == [
        ('D', 0, True, False), ('D', 1, True, False), ('D', 2, False, True)], frames
    start = data.index(b'\xA5\x5A')
    end = start + 3 * 10
    assert data[start:end] == (ref.frame('D', 0, ref.F_MISSING) + ref.frame('D', 1, ref.F_MISSING)
                               + ref.frame('D', 2, ref.F_END)), data[start:end].hex()
    before, after = data[:start].decode('ascii'), data[end:].decode('ascii')
    assert before.endswith('\r\n') and after.startswith('S '), (before[-120:], after[:120])
    line_start = data.rindex(b'S ', 0, start)
    assert tx[line_start][0] < t_cmd < tx[start - 1][0] < tx[start][0], (
        'the command came during a log line; the line ended whole before the dump', tx[line_start][0], t_cmd,
        tx[start - 1][0], tx[start][0])
    lines_after = [ln for ln in after.split('\r\n') if ln.startswith('S ')]
    assert lines_after and lines_after[0].endswith('4401') and len(lines_after[0]) == 99, lines_after[:1]
