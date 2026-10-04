"""snowlog.py: parsing of the FPGA's log lines and the summary table."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snowlog  # noqa: E402


def test_parse():
    assert snowlog.parse('S 012345 002345 040 034 025 F4 5800 MIX') == {
        'snow_a': 12345, 'snow_b': 2345, 'use_a': 40, 'use_b': 34, 'use_mix': 25,
        'channel': 'F4', 'mhz': 5800, 'mode': 'MIX'}
    assert snowlog.parse('S ------ 002345 000 100 000 A6 5765 B')['snow_a'] is None
    assert snowlog.parse('noise') is None


def test_summary(tmp_path, capsys):
    p = tmp_path / 'log.csv'
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=snowlog.FIELDS)
        w.writeheader()
        for lab, a in (('hdmi_on', 900), ('hdmi_off', 600)):
            for i in range(5):
                w.writerow({'time': i, 'label': lab, **snowlog.parse(f'S {a + i:06d} 002000 050 040 010 F4 5800 MIX')})
    snowlog.summary(p)
    out = capsys.readouterr().out
    assert 'hdmi_on' in out and '902' in out and '602' in out
