"""snowlog.py: parsing of the FPGA's log lines, a capture from a fake port and the summary table."""
import argparse
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snowlog  # noqa: E402


def test_parse():
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX - L?') == {
        'snow_a': 12345, 'snow_b': 2345, 'noise_a': 17, 'noise_b': 654321, 'use_a': 40, 'use_b': 34,
        'use_mix': 25, 'channel': 'F4', 'mhz': 5800, 'mode': 'MIX', 'filter': None,
        'dropped': 0, 'lost_a': 1, 'lost_b': None}
    r = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 A   ! -L')
    assert (r['dropped'], r['lost_a'], r['lost_b'], r['mode'], r['filter']) == (1, 0, 1, 'A', None)
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX - LX') is None
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX - L') is None
    # bitstreams before the lost-lock field
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX -') == {
        'snow_a': 12345, 'snow_b': 2345, 'noise_a': 17, 'noise_b': 654321, 'use_a': 40, 'use_b': 34,
        'use_mix': 25, 'channel': 'F4', 'mhz': 5800, 'mode': 'MIX', 'filter': None,
        'dropped': 0, 'lost_a': None, 'lost_b': None}
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 A   !')['dropped'] == 1
    r = snowlog.parse('S ------ 002345 ------ 000000 000 100 000 A6 5765 B   -')
    assert (r['snow_a'], r['noise_a'], r['noise_b']) == (None, None, 0)
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX ?') is None
    assert snowlog.parse('S 012345 002345 00001? 654321 040 034 025 F4 5800 MIX -') is None
    assert snowlog.parse('S 012345 002345 000017 040 034 025 F4 5800 MIX -') is None, 'one noise value lost'
    # older bitstreams: no noise values, with or without the dropped-line field
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 MIX') == {
        'snow_a': 12345, 'snow_b': 2345, 'noise_a': None, 'noise_b': None, 'use_a': 40, 'use_b': 34,
        'use_mix': 25, 'channel': 'F4', 'mhz': 5800, 'mode': 'MIX', 'filter': None,
        'dropped': 0, 'lost_a': None, 'lost_b': None}
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 A   !')['dropped'] == 1
    assert snowlog.parse('S ------ 002345 000 100 000 A6 5765 B')['snow_a'] is None
    assert snowlog.parse('noise') is None
    assert snowlog.parse('') is None
    assert snowlog.parse('S 01234? 002345 040 034 025 F4 5800 MIX') is None, 'a damaged digit is not a crash'

    # New noise-era rows: T/V is validated before the dropped/lost tokens are assigned.
    tv = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX T -')
    assert (tv['filter'], tv['dropped'], tv['lost_a'], tv['lost_b']) == ('T', 0, None, None)
    vcr = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX V ! L?')
    assert (vcr['filter'], vcr['dropped'], vcr['lost_a'], vcr['lost_b']) == ('V', 1, 1, None)
    tv_lost = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 A   T ! -L')
    assert (tv_lost['filter'], tv_lost['dropped'], tv_lost['lost_a'], tv_lost['lost_b']) == ('T', 1, 0, 1)
    vcr_no_lost = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 B   V -')
    assert (vcr_no_lost['filter'], vcr_no_lost['dropped'], vcr_no_lost['lost_a'], vcr_no_lost['lost_b']) == (
        'V', 0, None, None)
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX X -') is None
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX TV -') is None
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX  -') is None
    assert snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX  - L?') is None
    # Removing the T/V token and its separator can produce a byte-identical legacy row.
    # Compatibility wins for that indistinguishable shape, which remains filter=None.
    indistinguishable = snowlog.parse('S 012345 002345 000017 654321 040 034 025 F4 5800 MIX - L?')
    assert indistinguishable is not None and indistinguishable['filter'] is None


def fake_port(monkeypatch, data):
    monkeypatch.setattr(snowlog, 'open_serial', lambda path: 99)
    monkeypatch.setattr(snowlog.os, 'read', lambda fd, n: data.pop(0) if data else b'')
    monkeypatch.setattr(snowlog.os, 'close', lambda fd: None)


def _erased_filter_rows():
    prefix = 'S 012345 002345 000017 654321 040 034 025 F4 5800 '
    valid = (
        prefix + 'MIX T - L?', prefix + 'MIX T -',
        prefix + 'A   T ! -L', prefix + 'A   T -',
        prefix + 'B   V ! -L', prefix + 'B   V -',
    )
    damaged = []
    for row, value in zip(valid, ('T', 'T', 'T', 'T', 'V', 'V')):
        marker = f' {value} '
        index = row.index(marker) + 1
        erased = row[:index] + ' ' + row[index + 1:]
        assert len(erased) == len(row)
        assert sum(a != b for a, b in zip(row, erased)) == 1
        damaged.append(erased)
    return valid, damaged


def test_log_skips_damaged_lines(tmp_path, monkeypatch, capsys):
    """Three lines arrive in odd-sized pieces, the middle one damaged. No serial port is opened."""
    fake_port(monkeypatch, [b'S 000100 000200 000003 000000 050 040 010 F4 58',
                            b'00 MIX - --\r\nS 0001x0 000200 000003 000000 050 040 010 F4 5800 MIX - --\r\n',
                            b'S 000300 ------ 000012 ------ 100 000 000 F4 5800 A   - L?\r\n',
                            b'S 000400 000500 000013 000000 060 030 010 F4 5800 B   V ! L-\r\n',
                            b'S 000500 000600 000014 000000 060 030 010 F4 5800 MIX X - L?\r\n'])
    out = tmp_path / 'log.csv'
    snowlog.log(argparse.Namespace(port='COM5', label='t', seconds=0.3, out=str(out)))
    with open(out) as fh:
        rows = list(csv.DictReader(fh))
    assert [(r['snow_a'], r['snow_b'], r['noise_a'], r['noise_b'], r['mode'], r['filter'],
             r['dropped'], r['lost_a'], r['lost_b']) for r in rows] == [
                 ('100', '200', '3', '0', 'MIX', '', '0', '0', '0'),
                 ('300', '', '12', '', 'A', '', '0', '1', ''),
                 ('400', '500', '13', '0', 'B', 'V', '1', '1', '0')]
    assert '2 damaged lines skipped' in capsys.readouterr().out


def test_erased_filter_byte_is_damaged_in_log(tmp_path, monkeypatch, capsys):
    """Fake log framing keeps two valid records (current and legacy) and drops six damaged ones."""
    valid, damaged = _erased_filter_rows()
    assert all(snowlog.parse(row) is not None for row in valid)
    assert all(snowlog.parse(row) is None for row in damaged)
    legacy = 'S 012345 002345 000017 654321 040 034 025 F4 5800 MIX - L?'
    assert snowlog.parse(legacy)['filter'] is None

    payload = (valid[0] + '\r\n' + legacy + '\r\n'
               + ''.join(row + '\r\n' for row in damaged)).encode('ascii')
    fake_port(monkeypatch, [payload])
    out = tmp_path / 'erased-filter.csv'
    snowlog.log(argparse.Namespace(port='COM5', label='t', seconds=0.3, out=str(out)))
    with open(out, newline='') as fh:
        rows = list(csv.DictReader(fh))
    assert [(row['mode'], row['filter']) for row in rows] == [('MIX', 'T'), ('MIX', '')]
    output = capsys.readouterr().out
    assert '2 lines ->' in output
    # All six damaged records are counted; the valid legacy record retains filter=None.
    assert '6 damaged lines skipped' in output


def test_log_refuses_a_csv_with_other_columns(tmp_path, monkeypatch):
    """Appending the new columns to a file written with the old ones would shift every value."""
    out = tmp_path / 'old.csv'
    out.write_text('time,label,snow_a,snow_b,use_a,use_b,use_mix,channel,mhz,mode,dropped\n1,x,1,2,3,4,5,F4,5800,MIX,0\n')
    fake_port(monkeypatch, [b'S 000100 000200 000003 000000 050 040 010 F4 5800 MIX -\r\n'])
    with pytest.raises(SystemExit, match='other columns'):
        snowlog.log(argparse.Namespace(port='COM5', label='t', seconds=0.3, out=str(out)))
    assert out.read_text().count('\n') == 2, 'the old file is left as it was'


def test_summary(tmp_path, capsys):
    p = tmp_path / 'log.csv'
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=snowlog.FIELDS)
        w.writeheader()
        for lab, a, n in (('hdmi_on', 900, 4000), ('hdmi_off', 600, 7000)):
            for i in range(5):
                mark = '!' if lab == 'hdmi_on' and i == 3 else '-'
                ll = 'L-' if lab == 'hdmi_on' and i in (1, 2) else '--'
                w.writerow({'time': i, 'label': lab,
                            **snowlog.parse(f'S {a + i:06d} 002000 {n + i:06d} 000000 050 040 010 F4 5800 MIX {mark} {ll}')})
    snowlog.summary(p)
    out = capsys.readouterr().out
    assert 'hdmi_on' in out and '902' in out and '602' in out and '4002' in out and '7002' in out
    on, off = (next(l for l in out.splitlines() if l.startswith(lab)) for lab in ('hdmi_on', 'hdmi_off'))
    assert on.endswith('F4 !') and off.endswith('F4'), 'a run in which the mixer dropped lines is marked'
    assert on.split()[-4:-2] == ['2', '0'] and off.split()[-3:-1] == ['0', '0'], 'lines with lost lock per decoder'
