"""Guard: no single-ended output or inout in the I/O banks of the TMDS pairs.

Apicula 0.32 sets BANK_VCCIO for every IOB of a bank from the bank's first
single-ended output or inout (gowin_pack.py, second IO pass; 1.2 V when there is
none). With RESETB on pin 25 the TMDS clock pair on 33/34 was packed with two
IOB fuses less in M4 and M6 than in M0, where bank 5 only has inputs. Whether a
screen minds is not known, so the rule is: the tops that drive TMDS constrain
nothing but inputs and the TMDS pairs themselves to pins 25-42 (banks 5 and 4).

1. Static: the ports of every such top against the cst files it is built with.
   Controls: the same check on a pin plan with RESETB back on pin 25, or SCL
   (an inout) on pin 30, must report it; M1s has an input on pin 25 and passes.
2. Fuses: a small design with a TMDS clock pair on 33/34 and a data pair on
   35/36. An LVCMOS33 output on pin 18 (where RESETB now is) leaves the IOB
   fuses of both pairs as they are without it. Negative controls: the same
   output on pin 25, or an inout there, changes the clock pair; on pin 41 it
   changes the data pair.

tools/tmds_fuses.py compares the pairs of real, built bitstreams the same way.
True for apycula 0.32 (2026-10-05). Run again after any Apicula upgrade.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

GW = Path(__file__).resolve().parent.parent
BIN = GW.parent / '.venv' / 'bin'
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmds_fuses  # noqa: E402

TMDS_BANK_PINS = range(25, 43)          # QN88 pins 25-34 are bank 5, 35-42 bank 4


# ---- 1. static: top-level ports against the constraints -------------------------------------------

def top_ports(text, top):
    """{port: direction} from the ANSI port list of module `top`."""
    text = re.sub(r'//[^\n]*', '', text)
    start = re.search(rf'\bmodule\s+{top}\b', text).end()
    header = text[start:text.index(';', start)]
    depth, groups, begin = 0, [], None
    for i, ch in enumerate(header):
        if ch == '(':
            if depth == 0:
                begin = i + 1
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                groups.append(header[begin:i])
    ports, direction = {}, None
    for item in groups[-1].split(','):              # the last group is the port list (after #(parameters))
        words = re.sub(r'\[[^\]]*\]', ' ', item).split()
        if words and words[0] in ('input', 'output', 'inout'):
            direction = words[0]
        ports[words[-1]] = direction
    return ports


def constraints(cst_text):
    """[(port, bit-level name, location, io type)] of a cst file."""
    types = {name: re.search(r'IO_TYPE=(\w+)', attrs)
             for name, attrs in re.findall(r'^\s*IO_PORT\s+"([^"]+)"\s+([^;]*);', cst_text, re.M)}
    out = []
    for name, loc in re.findall(r'^\s*IO_LOC\s+"([^"]+)"\s+(\w+)\s*;', cst_text, re.M):
        io_type = types.get(name)
        out.append((name.split('[')[0], name, loc, io_type[1] if io_type else ''))
    return out


def outputs_in_tmds_banks(top_text, top, cst_text):
    """Constrained outputs and inouts of `top` on pins 25-42 that are not LVDS."""
    ports = top_ports(top_text, top)
    bad = []
    for port, name, loc, io_type in constraints(cst_text):
        in_bank = (loc.isdigit() and int(loc) in TMDS_BANK_PINS) or re.fullmatch(r'IOB\d+[AB]', loc)
        if in_bank and ports.get(port) in ('output', 'inout') and not io_type.startswith('LVDS'):
            bad.append((name, loc))
    return bad


def build_cst(top):
    """The constraints build.sh uses: the board file plus the top's own."""
    own = GW / 'boards' / f'{top}.cst'
    return (GW / 'boards' / 'tangnano20k.cst').read_text() + (own.read_text() if own.exists() else '')


def tmds_tops():
    tops = {}
    for path in sorted((GW / 'top').glob('*.v')):
        text = path.read_text()
        if 'tmds_clk_p' in top_ports(text, path.stem):
            tops[path.stem] = text
    return tops


def test_no_single_ended_output_in_the_tmds_banks():
    tops = tmds_tops()
    assert {'m0_testpattern', 'm4_dual_mix', 'm6_puck_proto'} <= set(tops), sorted(tops)
    for top, text in tops.items():
        assert outputs_in_tmds_banks(text, top, build_cst(top)) == [], top
        # the pairs themselves are found on their pins, so the parsing sees this top's ports
        pairs = {loc for port, _, loc, io_type in constraints(build_cst(top))
                 if port.startswith('tmds_') and port in top_ports(text, top) and io_type == 'LVDS25'}
        assert pairs == {str(p) for p in range(33, 41)}, (top, pairs)


def test_static_check_sees_an_output_or_inout_on_those_pins():
    text = (GW / 'top' / 'm4_dual_mix.v').read_text()
    cst = build_cst('m4_dual_mix')
    assert '"tvp_resetb" 18;' in cst and '"i2c_scl" 75;' in cst
    old = cst.replace('"tvp_resetb" 18;', '"tvp_resetb" 25;')
    assert outputs_in_tmds_banks(text, 'm4_dual_mix', old) == [('tvp_resetb', '25')]
    scl = cst.replace('"i2c_scl" 75;', '"i2c_scl" 30;')
    assert outputs_in_tmds_banks(text, 'm4_dual_mix', scl) == [('i2c_scl', '30')]
    # an input on pin 25 is allowed: M1s has AVID there
    m1s = (GW / 'top' / 'm1s_moneagle_view_sync.v').read_text()
    assert ('tvp_avid', 'tvp_avid', '25', 'LVCMOS33') in constraints(build_cst('m1s_moneagle_view_sync'))
    assert top_ports(m1s, 'm1s_moneagle_view_sync')['tvp_avid'] == 'input'
    assert outputs_in_tmds_banks(m1s, 'm1s_moneagle_view_sync', build_cst('m1s_moneagle_view_sync')) == []


# ---- 2. fuses: what an output beside the pairs does to them ---------------------------------------

DESIGNS = '''
module probe_base (input wire clk, output wire [1:0] led,
                   output wire tmds_clk_p, tmds_clk_n, tmds_d_p, tmds_d_n);
    reg [23:0] c; always @(posedge clk) c <= c + 1'b1;
    assign led = c[23:22];
    TLVDS_OBUF tmds_clk_buf (.I(c[3]), .O(tmds_clk_p), .OB(tmds_clk_n));
    TLVDS_OBUF tmds_d_buf (.I(c[4]), .O(tmds_d_p), .OB(tmds_d_n));
endmodule
module probe_out (input wire clk, output wire [1:0] led,
                  output wire tmds_clk_p, tmds_clk_n, tmds_d_p, tmds_d_n, output wire extra);
    reg [23:0] c; always @(posedge clk) c <= c + 1'b1;
    assign led = c[23:22];
    assign extra = c[20];
    TLVDS_OBUF tmds_clk_buf (.I(c[3]), .O(tmds_clk_p), .OB(tmds_clk_n));
    TLVDS_OBUF tmds_d_buf (.I(c[4]), .O(tmds_d_p), .OB(tmds_d_n));
endmodule
module probe_io (input wire clk, output wire [1:0] led,
                 output wire tmds_clk_p, tmds_clk_n, tmds_d_p, tmds_d_n, inout wire extra);
    reg [23:0] c; always @(posedge clk) c <= c + 1'b1;
    reg q; always @(posedge clk) q <= extra;
    assign led = {q, c[23]};
    assign extra = c[20] ? 1'b0 : 1'bz;
    TLVDS_OBUF tmds_clk_buf (.I(c[3]), .O(tmds_clk_p), .OB(tmds_clk_n));
    TLVDS_OBUF tmds_d_buf (.I(c[4]), .O(tmds_d_p), .OB(tmds_d_n));
endmodule
'''
PINS = ('IO_LOC "clk" 4;\n'
        + ''.join(f'IO_LOC "led[{i}]" {15 + i};\nIO_PORT "led[{i}]" IO_TYPE=LVCMOS33 PULL_MODE=NONE;\n' for i in range(2))
        + ''.join(f'IO_LOC "{name}" {pin};\nIO_PORT "{name}" IO_TYPE=LVDS25 PULL_MODE=NONE;\n'
                  for name, pin in (('tmds_clk_p', 33), ('tmds_clk_n', 34), ('tmds_d_p', 35), ('tmds_d_n', 36))))


def extra_on(pin):
    return PINS + f'IO_LOC "extra" {pin};\nIO_PORT "extra" IO_TYPE=LVCMOS33 PULL_MODE=NONE;\n'


def build(tmp, top, name, cst_text):
    env = dict(os.environ, TMPDIR=str(tmp))      # yowasp only sees the working directory
    (tmp / f'{name}.cst').write_text(cst_text)

    def run(*a):
        r = subprocess.run(a, cwd=tmp, env=env, capture_output=True, text=True)
        assert r.returncode == 0, f'{Path(a[0]).name} failed for {name}: {(r.stderr or r.stdout)[-800:]}'
    run(str(BIN / 'yowasp-yosys'), '-q', '-p', f'read_verilog probe.v; synth_gowin -top {top} -family gw2a -json {name}.json')
    run(str(BIN / 'yowasp-nextpnr-himbaechel-gowin'), '--json', f'{name}.json', '--write', f'{name}.pnr.json',
        '--device', 'GW2AR-LV18QN88C8/I7', '--vopt', 'family=GW2A-18C', '--vopt', f'cst={name}.cst', '--quiet')
    run(str(BIN / 'gowin_pack'), '-c', '-d', 'GW2A-18C', '-o', f'{name}.fs', f'{name}.pnr.json')
    return tmp / f'{name}.fs'


@pytest.mark.skipif(not (BIN / 'gowin_pack').exists(), reason='open toolchain not installed')
def test_output_on_pin_18_leaves_the_tmds_pairs_alone(tmp_path):
    (tmp_path / 'probe.v').write_text(DESIGNS)
    fs = {'base': build(tmp_path, 'probe_base', 'base', PINS),
          'out18': build(tmp_path, 'probe_out', 'out18', extra_on(18)),
          'out25': build(tmp_path, 'probe_out', 'out25', extra_on(25)),
          'io25': build(tmp_path, 'probe_io', 'io25', extra_on(25)),
          'out41': build(tmp_path, 'probe_out', 'out41', extra_on(41))}
    db = tmds_fuses.load_db()
    tiles = tmds_fuses.io_tiles(tmp_path / 'base.pnr.json')
    clk = next(rc for rc, names in tiles.items() if any('tmds_clk' in n for n in names))
    data = next(rc for rc, names in tiles.items() if any('tmds_d' in n for n in names))
    assert len(tiles) == 2 and clk != data, tiles
    fuses = {name: {rc: tmds_fuses.iob_fuses(db, bitmaps, rc) for rc in (clk, data)}
             for name, bitmaps in ((name, tmds_fuses.tile_bitmaps(db, path)) for name, path in fs.items())}
    base = fuses['base']
    assert base[clk] and base[data]
    assert fuses['out18'] == base, 'an output on pin 18 changes the IOB fuses of a TMDS pair: ' \
        f'clock pair {sorted(fuses["out18"][clk] ^ base[clk])}, data pair {sorted(fuses["out18"][data] ^ base[data])}'
    # negative controls: the method sees an output or inout in the pair's own bank
    assert fuses['out25'][clk] != base[clk] and fuses['out25'][data] == base[data]      # bank 5: clock pair
    assert fuses['io25'][clk] != base[clk] and fuses['io25'][data] == base[data]
    assert fuses['out41'][data] != base[data] and fuses['out41'][clk] == base[clk]      # bank 4: data pairs
