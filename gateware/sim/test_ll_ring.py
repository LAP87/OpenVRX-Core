"""Focused native simulation for fb_backend's shared LOW/BUF line-buffer mask."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GW = HERE.parent
PROJECT = GW.parent
sys_path = str(GW / 'model')
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)
import ll_ring_ref as ring  # noqa: E402


RTL = (
    'async_fifo.v', 'sdram_burst.v', 'field_phase.v', 'fb_sdram.v', 'dual_clock_ram.v',
    'genlock_timing.v', 'ycbcr2rgb.v', 'cdc_sync.v', 'fb_display.v', 'vblend.v', 'fb_backend.v',
)


def hexnum(value):
    try:
        return int(value, 16)
    except (TypeError, ValueError):
        return None


def run_bench(work, alter=None):
    work = Path(work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = dict(os.environ)
    iverilog_bin = PROJECT / '.tools' / 'iverilog' / 'bin'
    if iverilog_bin.exists():
        env['PATH'] = f'{iverilog_bin}{os.pathsep}' + env['PATH']
    rtl = [GW / 'rtl' / name for name in RTL]
    for name, (old, new) in (alter or {}).items():
        source = (GW / 'rtl' / name).read_text()
        assert source.count(old) == 1, f'{name}: expected one occurrence of {old!r}'
        altered = work / name
        altered.write_text(source.replace(old, new))
        rtl = [altered if path.name == name else path for path in rtl]
    subprocess.run(
        ['iverilog', '-g2012', '-o', 'sim.vvp', '-s', 'tb_ll_ring',
         *map(str, rtl), str(HERE / 'tb_ll_ring.v')],
        cwd=work, env=env, check=True, capture_output=True, text=True, timeout=30,
    )
    subprocess.run(
        ['vvp', '-n', 'sim.vvp'], cwd=work, env=env, check=True,
        capture_output=True, text=True, timeout=30,
    )
    events = []
    for line in (work / 'll_ring.txt').read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'RESET':
            events.append(('RESET', float(fields[1])))
        elif fields[0] == 'W':
            events.append(('W', float(fields[1]), int(fields[2]), hexnum(fields[3])))
        elif fields[0] == 'P':
            events.append(('P', float(fields[1]), int(fields[2]), hexnum(fields[3]),
                           hexnum(fields[4]), int(fields[5]), int(fields[6]), int(fields[7])))
        elif fields[0] == 'END':
            events.append(('END', int(fields[1])))
        else:
            raise AssertionError(f'unrecognized ll-ring trace row: {line}')
    return events


def check_trace(events):
    """Model accepted writes, reset, the two-flop mask CDC, RAM read and display input."""
    memory = ring.LineBuffer()
    pixel = ring.PixelReadPipeline()
    findings = []
    observed_writes = 0
    samples = []
    ops = [e for e in events if e[0] != 'END']
    ends = [e[1] for e in events if e[0] == 'END']
    for event in sorted(ops, key=lambda e: (e[1], 0 if e[0] == 'RESET' else 1)):
        kind = event[0]
        if kind == 'RESET':
            memory.reset()
            pixel.reset()
        elif kind == 'W':
            _, t_ns, address, data = event
            if data is None:
                findings.append(f'accepted write at {address} has unknown data')
                continue
            memory.accept_write(address, data, t_ns)
            observed_writes += 1
        elif kind == 'P':
            _, t_ns, address, raw, shown, low, prst, is_probe = event
            if prst:
                pixel.reset()
                continue
            pixel.posedge(memory, address, bool(low))
            expected_raw = pixel.data_q
            expected_display = pixel.display_input(memory)
            samples.append((address, raw, shown, expected_raw, expected_display, is_probe, t_ns))
            if raw != expected_raw:
                findings.append(f'address/data alignment at {address}: raw {raw}, model {expected_raw}')
            if shown != expected_display:
                findings.append(f'display input at {address}: got {shown}, model {expected_display}')
    if not ends:
        findings.append('trace has no END marker')
    elif len(ends) != 1 or ends[0] != observed_writes:
        findings.append(f'END says {ends}, trace has {observed_writes} accepted writes')
    return findings, samples


def test_shared_low_buf_line_buffer_mask_and_read_alignment(tmp_path):
    events = run_bench(tmp_path / 'normal')
    findings, samples = check_trace(events)
    assert not findings, findings
    probes = [sample for sample in samples if sample[5]]
    assert len(probes) >= 28, f'expected broad slot and first/last-word probes, got {len(probes)}'

    # The mid-line first LOW arrival reaches word 359 without making its slot valid.
    writes = [e for e in events if e[0] == 'W']
    write_addresses = [e[2] for e in writes]
    partial_start = write_addresses.index(9 * ring.SLOT_WORDS + 53)
    partial = write_addresses[partial_start:partial_start + 307]
    assert partial == list(range(9 * ring.SLOT_WORDS + 53, 9 * ring.SLOT_WORDS + 360))
    assert any(addr == 9 * ring.SLOT_WORDS + 52 and shown == ring.BLACK_WORD
               for addr, _, shown, _, _, _, _ in probes)
    assert any(addr == 9 * ring.SLOT_WORDS + 359 and shown == 0xA5000000 + 359
               for addr, _, shown, _, _, _, _ in probes)
    # At least one probe occurs after index 358 and before 359 is accepted.
    idx358_time = [e[1] for e in writes if e[2] == 9 * ring.SLOT_WORDS + 358][-1]
    idx359_time = [e[1] for e in writes if e[2] == 9 * ring.SLOT_WORDS + 359][-1]
    assert any(idx358_time < t < idx359_time and addr == 9 * ring.SLOT_WORDS + 52 and shown == ring.BLACK_WORD
               for addr, _, shown, _, _, _, t in probes)


MUTANTS = {
    'disabled_mask': (
        'fb_backend.v',
        "wire [31:0] lb_rdisplay = (linebuf_read_low && !linebuf_initialized_p2[linebuf_read_slot])\n"
        "                            ? LINEBUF_BLACK : lb_rdata;",
        'wire [31:0] lb_rdisplay = lb_rdata;',
    ),
    'all_black': (
        'fb_backend.v',
        "wire [31:0] lb_rdisplay = (linebuf_read_low && !linebuf_initialized_p2[linebuf_read_slot])\n"
        "                            ? LINEBUF_BLACK : lb_rdata;",
        'wire [31:0] lb_rdisplay = LINEBUF_BLACK;',
    ),
    'last_word_only': (
        'fb_backend.v',
        'end else if (lbw_we) begin',
        "end else if (lbw_we) begin\n"
        "            if (lbw_addr[8:0] == 9'd359)\n"
        "                linebuf_initialized_s[lbw_addr[12:9]] <= 1'b1;",
    ),
    'early_completion': (
        'fb_backend.v',
        "if (lbw_addr[8:0] == 9'd359) begin",
        "if (lbw_addr[8:0] == 9'd358) begin",
    ),
    'wrong_slot_alignment': (
        'fb_backend.v',
        'linebuf_read_slot <= lb_raddr[12:9];',
        "linebuf_read_slot <= lb_raddr[12:9] + 4'd1;",
    ),
    'wrong_data_address': (
        'fb_backend.v',
        '.rclk(pix_clk), .raddr(lb_raddr), .rdata(lb_rdata));',
        ".rclk(pix_clk), .raddr(lb_raddr + 13'd1), .rdata(lb_rdata));",
    ),
}


@pytest.mark.parametrize('name', sorted(MUTANTS))
def test_ring_checker_rejects_mask_completion_and_alignment_mutants(tmp_path, name):
    filename, old, new = MUTANTS[name]
    events = run_bench(tmp_path / name, alter={filename: (old, new)})
    findings, _ = check_trace(events)
    assert findings, (name, 'mutant unexpectedly passed')
    if name == 'early_completion':
        assert any('display input' in item for item in findings), findings
    elif name == 'wrong_data_address':
        assert any('address/data alignment' in item for item in findings), findings
    else:
        assert any('display input' in item for item in findings), findings
