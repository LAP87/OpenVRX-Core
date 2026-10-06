"""Source contract for the three Tang LED pins that the decoder board uses as header pins.

The decoder board (OpenVRX-Puck, design/rev_a/dekoderkort.py) takes RESETB from J6-18 (FPGA pin
18) and the RX5808 SPI DATA and SEL from J6-17 and J6-16 (pins 19 and 20). A pin number in the
constraint file is not enough to know that the bitstream drives those signals there: this checks,
for a top-level source and its constraint files, that
  * the top has output ports tvp_resetb, rx_spi_data and rx_spi_sel_n,
  * tvp_resetb is driven by the TVP controller (`.tvp_resetb(tvp_resetb)` on a tvp_ctrl instance),
  * the SPI ports are driven by the RX5808 logic (rx5808_tune or puck_ui),
  * the constraint files put them on pins 18, 19 and 20 and nothing else on those pins.
It reads the documented wiring style of the tops in this repository; it is a source check, not a
Verilog parser or an electrical proof. The Puck schematic test imports `shared_output_problems`.
"""
import re

PINS = {'tvp_resetb': 18, 'rx_spi_data': 19, 'rx_spi_sel_n': 20}


def shared_output_problems(source, top, cst=None):
    """Problems (strings) with top-level source `source` of module `top`; [] when all is well.
    cst: the text of the constraint files (board + top) if they are to be checked too."""
    src = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    problems = []
    for port in PINS:
        if not re.search(r'\boutput\s+(?:wire\s+)?' + port + r'\b', src):
            problems.append(f'{top}: no output port {port}')
    if len(re.findall(r'\btvp_ctrl\b', src)) < 1 or len(re.findall(r'\.tvp_resetb\s*\(\s*tvp_resetb\s*\)', src)) != 1:
        problems.append(f'{top}: tvp_resetb must be driven by the tvp_ctrl instance, once')
    if not re.search(r'\.spi_data\s*\(\s*rx_spi_data\s*\)|\.rx_spi_data\s*\(\s*rx_spi_data\s*\)', src):
        problems.append(f'{top}: rx_spi_data must come from rx5808_tune or puck_ui')
    if len(re.findall(r'\bassign\s+rx_spi_sel_n\s*=\s*sel_n\s*\[\s*0\s*\]\s*;', src)) != 1:
        problems.append(f'{top}: rx_spi_sel_n must be sel_n[0] of the RX5808 logic')
    for port in PINS:
        if re.search(r'\bassign\s+' + port + r'\s*=', src) and port != 'rx_spi_sel_n':
            problems.append(f'{top}: {port} is driven by an assign, not by the module that owns it')
    if cst is not None:
        loc = {}
        for name, pin in re.findall(r'IO_LOC\s+"([^"]+)"\s+(\d+);', cst):
            loc.setdefault(name, []).append(int(pin))
        for port, pin in PINS.items():
            if loc.get(port) != [pin]:
                problems.append(f'{top}: {port} must be on pin {pin}, constraints say {loc.get(port)}')
            others = [n for n, pins in loc.items() if pin in pins and n != port and not n.startswith('led[')]
            if others:
                problems.append(f'{top}: pin {pin} also carries {others}')
    return problems
