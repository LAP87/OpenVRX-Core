"""Guard against an Apicula packing bug seen in otanl/CVBS2HDMI (MIT, 2026-09-25):
there, single-ended inputs in a bank that also holds a true-LVDS output
(the HDMI lanes) were packed with the bank's IO_TYPE, i.e. as LVDS receivers
comparing each A/B pin pair. Our decoder A bus uses pins 26..31 in that bank
(bank 5, beside the HDMI clock lane on 33/34).

Builds two tiny designs that read pins 27..30 (LVCMOS33): one with an LVDS
output on 33/34, one without. The input IOBs' configuration fuses (every fuse
that belongs to an IOBA/IOBB attribute; routing excluded) must be identical.
Negative control: a real LVDS receiver (TLVDS_IBUF) on 27/28 must change them.
True for apycula 0.32 (checked 2026-10-04). If an Apicula upgrade fails this,
pack through a wrapper like CVBS2HDMI's scripts/gowin_pack_io.py.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
BIN = GW.parent / '.venv' / 'bin'

DESIGNS = '''
module probe_lvds (input wire clk, input wire [3:0] din, output wire [3:0] led, output wire tmds_clk_p, tmds_clk_n);
    reg [23:0] c; always @(posedge clk) c <= c + 1'b1;
    reg [3:0] q; always @(posedge clk) q <= din;
    assign led = ~q;
    TLVDS_OBUF ob (.I(c[3]), .O(tmds_clk_p), .OB(tmds_clk_n));
endmodule
module probe_plain (input wire clk, input wire [3:0] din, output wire [3:0] led);
    reg [3:0] q; always @(posedge clk) q <= din;
    assign led = ~q;
endmodule
module probe_rx (input wire clk, input wire din_p, din_n, output wire [3:0] led);
    wire d; reg q;
    TLVDS_IBUF ib (.I(din_p), .IB(din_n), .O(d));
    always @(posedge clk) q <= d;
    assign led = {3'b111, ~q};
endmodule
'''
PINS = ''.join(f'IO_LOC "led[{i}]" {15 + i};\n' for i in range(4)) + 'IO_LOC "clk" 4;\n' + ''.join(
    f'IO_LOC "din[{i}]" {27 + i};\nIO_PORT "din[{i}]" IO_TYPE=LVCMOS33 PULL_MODE=NONE;\n' for i in range(4))
LVDS_PINS = ('IO_LOC "tmds_clk_p" 33;\nIO_PORT "tmds_clk_p" IO_TYPE=LVDS25 PULL_MODE=NONE;\n'
             'IO_LOC "tmds_clk_n" 34;\nIO_PORT "tmds_clk_n" IO_TYPE=LVDS25 PULL_MODE=NONE;\n')


def build(tmp, top, cst):
    env = dict(os.environ, TMPDIR=str(tmp))      # yowasp only sees the working directory
    run = lambda *a: subprocess.run(a, cwd=tmp, env=env, check=True, capture_output=True)
    run(str(BIN / 'yowasp-yosys'), '-q', '-p', f'read_verilog probe.v; synth_gowin -top {top} -family gw2a -json {top}.json')
    run(str(BIN / 'yowasp-nextpnr-himbaechel-gowin'), '--json', f'{top}.json', '--write', f'{top}.pnr.json',
        '--device', 'GW2AR-LV18QN88C8/I7', '--vopt', 'family=GW2A-18C', '--vopt', f'cst={cst}', '--quiet')
    run(str(BIN / 'gowin_pack'), '-c', '-d', 'GW2A-18C', '-o', f'{top}.fs', f'{top}.pnr.json')
    return tmp / f'{top}.fs'


@pytest.mark.skipif(not (BIN / 'gowin_pack').exists(), reason='open toolchain not installed')
def test_inputs_beside_lvds_keep_their_own_io_type(tmp_path):
    from apycula import chipdb
    from apycula.bslib import read_bitstream
    (tmp_path / 'probe.v').write_text(DESIGNS)
    (tmp_path / 'plain.cst').write_text(PINS)
    (tmp_path / 'lvds.cst').write_text(PINS + LVDS_PINS)
    fs_lvds = build(tmp_path, 'probe_lvds', 'lvds.cst')
    fs_plain = build(tmp_path, 'probe_plain', 'plain.cst')
    (tmp_path / 'rx.cst').write_text(''.join(f'IO_LOC "led[{i}]" {15 + i};\n' for i in range(4)) +
                                     'IO_LOC "clk" 4;\nIO_LOC "din_p" 27;\nIO_PORT "din_p" IO_TYPE=LVDS25;\n'
                                     'IO_LOC "din_n" 28;\nIO_PORT "din_n" IO_TYPE=LVDS25;\n')
    fs_rx = build(tmp_path, 'probe_rx', 'rx.cst')

    db = chipdb.load_chipdb(os.path.join(os.path.dirname(chipdb.__file__), 'GW2A-18C.msgpack.xz'))
    bms = [chipdb.tile_bitmap(db, read_bitstream(str(f))[0]) for f in (fs_lvds, fs_plain, fs_rx)]
    # the IOB tiles of pins 27..30 (bottom row): find them from the placed design's bels
    cells = next(iter(json.load(open(tmp_path / 'probe_lvds.pnr.json'))['modules'].values()))['cells']
    tiles = set()
    for c in cells.values():
        bel = c.get('attributes', {}).get('NEXTPNR_BEL', '')
        if c['type'] == 'IBUF' and bel.startswith('X') and 'Y54/' in bel:
            x, y = bel.split('/')[0][1:].split('Y')
            tiles.add((int(y), int(x)))
    assert len(tiles) == 2, tiles                                 # 27/28 and 29/30 pairs
    for rc in sorted(tiles):
        ttyp = db[rc].ttyp
        mask = {f for tbl in ('IOBA', 'IOBB') for fuses in db.longval[ttyp][tbl].values()
                for f in fuses if isinstance(f, tuple)}
        on = [{(r, c) for r, line in enumerate(bm[rc]) for c, v in enumerate(line) if v} & mask for bm in bms]
        assert on[0] == on[1], f'tile {rc}: IOB fuses differ with an LVDS output in the bank: ' \
                               f'only with LVDS {sorted(on[0] - on[1])}, only without {sorted(on[1] - on[0])}'
    rx_tile = (54, 7)                                             # pins 27/28 (IOB7A/B)
    assert rx_tile in tiles
    ttyp = db[rx_tile].ttyp
    mask = {f for tbl in ('IOBA', 'IOBB') for fuses in db.longval[ttyp][tbl].values()
            for f in fuses if isinstance(f, tuple)}
    rx_on, plain_on = [{(r, c) for r, line in enumerate(bms[i][rx_tile]) for c, v in enumerate(line) if v} & mask
                       for i in (2, 1)]
    assert rx_on != plain_on, 'the check cannot tell an LVDS receiver from LVCMOS33 inputs'
