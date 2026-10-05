"""snowlog.py: parsing of the FPGA's log lines, a capture from a fake port and the summary table."""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snowlog  # noqa: E402


def test_parse():
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 MIX') == {
        'snow_a': 12345, 'snow_b': 2345, 'use_a': 40, 'use_b': 34, 'use_mix': 25,
        'channel': 'F4', 'mhz': 5800, 'mode': 'MIX', 'dropped': 0}
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 MIX -')['dropped'] == 0
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 A   !')['dropped'] == 1
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 MIX ?') is None
    assert snowlog.parse('S ------ 002345 000 100 000 A6 5765 B')['snow_a'] is None
    assert snowlog.parse('noise') is None
    assert snowlog.parse('S 01234? 002345 040 034 025 F4 5800 MIX') is None, 'a damaged digit is not a crash'


def test_log_skips_damaged_lines(tmp_path, monkeypatch, capsys):
    """Three lines arrive in odd-sized pieces, the middle one damaged. No serial port is opened."""
    data = [b'S 000100 000200 050 040 010 F4 58', b'00 MIX\r\nS 0001x0 000200 050 040 010 F4 5800 MIX\r\n',
            b'S 000300 ------ 100 000 000 F4 5800 A\r\n']
    monkeypatch.setattr(snowlog, 'open_serial', lambda path: 99)
    monkeypatch.setattr(snowlog.os, 'read', lambda fd, n: data.pop(0) if data else b'')
    monkeypatch.setattr(snowlog.os, 'close', lambda fd: None)
    out = tmp_path / 'log.csv'
    snowlog.log(argparse.Namespace(port='COM5', label='t', seconds=0.3, out=str(out)))
    with open(out) as fh:
        rows = list(csv.DictReader(fh))
    assert [(r['snow_a'], r['snow_b'], r['mode'], r['dropped']) for r in rows] == [('100', '200', 'MIX', '0'), ('300', '', 'A', '0')]
    assert '1 damaged lines skipped' in capsys.readouterr().out


def test_summary(tmp_path, capsys):
    p = tmp_path / 'log.csv'
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=snowlog.FIELDS)
        w.writeheader()
        for lab, a in (('hdmi_on', 900), ('hdmi_off', 600)):
            for i in range(5):
                mark = ' !' if lab == 'hdmi_on' and i == 3 else ' -'
                w.writerow({'time': i, 'label': lab, **snowlog.parse(f'S {a + i:06d} 002000 050 040 010 F4 5800 MIX{mark}')})
    snowlog.summary(p)
    out = capsys.readouterr().out
    assert 'hdmi_on' in out and '902' in out and '602' in out
    on, off = (next(l for l in out.splitlines() if l.startswith(lab)) for lab in ('hdmi_on', 'hdmi_off'))
    assert on.endswith('F4 !') and off.endswith('F4'), 'a run in which the mixer dropped lines is marked'
