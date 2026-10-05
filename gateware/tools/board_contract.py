"""Source contract for the Tang LED pins reused by the decoder board.

Require a direct, unambiguous assignment, not just an IO_LOC with a plausible
port name. This intentionally accepts only the documented top-level wiring
style; it is a source check, not a general Verilog parser or electrical proof.
"""
import re


def shared_output_problems(source, top):
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    expected = {3: 'tvp_resetb', 4: 'spi_data',
                5: 'sel_n[0]' if top == 'm6_puck_proto' else 'spi_sel_n'}
    drivers = {bit: [] for bit in expected}
    for select, expr in re.findall(r'\bassign\s+led\s*(\[[^\]]+\])?\s*=\s*([^;]+);', source):
        if not select:
            bits = range(6)
        else:
            ends = [int(n) for n in select[1:-1].split(':')]
            bits = range(min(ends), max(ends) + 1)
        for bit in bits:
            if bit in drivers:
                drivers[bit].append(re.sub(r'\s+', '', expr))
    problems = [f'{top}: led[{bit}] must have the single direct driver {want}; got {drivers[bit]}'
                for bit, want in expected.items() if drivers[bit] != [want]]
    if not re.search(r'\btvp_ctrl\b', source) or len(re.findall(r'\.tvp_resetb\s*\(\s*tvp_resetb\s*\)', source)) != 1:
        problems.append(f'{top}: tvp_resetb must connect to the TVP controller reset output')
    return problems
