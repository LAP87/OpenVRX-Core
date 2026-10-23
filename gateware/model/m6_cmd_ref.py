"""Reference model of M6's development command channel (rtl/puck_ui.v, DEVCMD = 1).

One byte per command, each setting a value; the log line then carries the state and an echo, and "?" asks for a
status line. sim/test_m6_cmd.py drives puck_ui with bytes and compares every log line, the status line and the
module's outputs with this model.

    state = initial()
    state = apply(state, ord('L'))            # latency LOW
    suffix(state)                             # ' LOW -A 4C01'
"""
from dataclasses import dataclass, replace

from vtx_channels import BANDS

COMMANDS = {
    ord('B'): 'latency BUF', ord('L'): 'latency LOW',
    ord('T'): 'filter TV', ord('V'): 'filter VCR',
    ord('m'): 'mode MIX', ord('a'): 'force A', ord('b'): 'force B',
    ord('H'): 'HOLD on', ord('h'): 'HOLD off',
    ord('+'): 'channel up', ord('-'): 'channel down',
    ord('O'): 'OSD on', ord('o'): 'OSD off', ord('*'): 'OSD as the buttons decide',
    ord('?'): 'status line', ord('D'): 'dump decoder A', ord('F'): 'dump field store',
}
N_BANDS, N_CH = len(BANDS), 8
CMD_LEN, BASE_LEN, Q_LEN = 12, 87, 52


@dataclass(frozen=True)
class State:
    band: int = 3                 # F
    ch: int = 3                   # F4 5800
    mode: int = 0                 # 0 MIX, 1 A, 2 B
    low_lat: int = 0
    filter_vcr: int = 0
    hold: int = 0
    osd_force: int = 0            # 0 buttons, 1 on, 2 off
    last: int = 0
    count: int = 0
    filter_req: int = 0           # filter_changed pulses so far
    spi_writes: int = 0           # channel steps that write the RX5808 at once
    q_req: int = 0                # status lines asked for
    dumps: tuple = ()             # dump requests: 'D' or 'F'


def initial(**kw):
    return State(**kw)


def step(band, ch, up):
    i = band * N_CH + ch
    i = (i + (1 if up else -1)) % (N_BANDS * N_CH)
    return divmod(i, N_CH)


def apply(s, byte, scan_busy=False, devcmd=True):
    """The state after one received byte. Bytes that are not commands change nothing, not even the count."""
    if not devcmd or byte not in COMMANDS:
        return s
    c = chr(byte)
    s = replace(s, last=byte, count=(s.count + 1) & 0xFF)
    if c in 'BL':
        s = replace(s, low_lat=int(c == 'L'))
    elif c in 'TV':
        s = replace(s, filter_vcr=int(c == 'V'), filter_req=s.filter_req + 1)
    elif c in 'mab':
        s = replace(s, mode='mab'.index(c))
    elif c in 'Hh':
        s = replace(s, hold=int(c == 'H'))
    elif c in '+-':
        if not s.hold and not scan_busy:
            band, ch = step(s.band, s.ch, c == '+')
            s = replace(s, band=band, ch=ch, spi_writes=s.spi_writes + 1)
    elif c in 'Oo*':
        s = replace(s, osd_force={'O': 1, 'o': 2, '*': 0}[c])
    elif c == '?':
        s = replace(s, q_req=s.q_req + 1)
    else:
        s = replace(s, dumps=s.dumps + (c,))
    return s


def channel(s):
    """('F4', 5800)"""
    letter, freqs = BANDS[s.band]
    return f'{letter}{s.ch + 1}', freqs[s.ch]


def suffix(s):
    """The 12 bytes DEVCMD = 1 adds before CR LF."""
    osd = {0: 'A', 1: 'O', 2: '-'}[s.osd_force]
    return f" {'LOW' if s.low_lat else 'BUF'} {'H' if s.hold else '-'}{osd} {s.last:02X}{s.count:02X}"


def log_fields(s):
    """The parts of the 89-byte line the commands set: channel, MHz, mode, filter."""
    name, mhz = channel(s)
    return {'channel': name, 'mhz': mhz, 'mode': ('MIX', 'A', 'B')[s.mode], 'filter': 'V' if s.filter_vcr else 'T'}


def osd_on(s, auto):
    """OSD visible, given what the buttons and pages alone would show (`auto`)."""
    return s.osd_force == 1 or (s.osd_force != 2 and auto)


def force_bad(s):
    """puck_ui force_bad: {mark B bad, mark A bad}."""
    return (int(s.mode == 1) << 1) | int(s.mode == 2)


def q_line(dec, sdram='2', hdmi_build=False, tvp_first=0x5C, baud=115200):
    """The status line without CR LF. dec: two dicts with init, err, alt, valid, st (16 bits), misc_ok, misc, ri."""
    def one(d):
        if not d['init']:
            addr = '--'
        elif d['err']:
            addr = 'NA'
        else:
            addr = '5D' if (d['alt'] ^ (tvp_first & 1)) else '5C'
        st = f"{d['st']:04X}" if d['valid'] else '----'
        misc = f"{d['misc']:02X}" if d['misc_ok'] else '--'
        return f"{addr} {st} {misc} {d['ri']:02X}"
    return (f"Q A {one(dec[0])} B {one(dec[1])} T {sdram} {'H' if hdmi_build else 'D'} "
            f"{'5D' if tvp_first & 1 else '5C'} {baud:07d}")

