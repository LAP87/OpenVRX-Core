# OpenVRX-Core

> Part of the [OpenVRX](https://github.com/LAP87/OpenVRX) family: FPGA gateware
> shared by every OpenVRX receiver variant.

Verilog for a Tang Nano 20K (Gowin GW2AR-18), built with a fully open
toolchain. Two TVP5150AM1 decoders deliver BT.656; the FPGA pairs their lines,
picks or blends the cleaner one per line, and outputs 720p over the board's
HDMI connector, either through an SDRAM field buffer or in a genlocked
low-latency mode. Also: RX5808 channel control over SPI, an OLED menu, an
on-screen display, a "snow meter" and a UART measurement log.

**Status (2026-10-21, main after task 47, tested on `06d7522`, merged as `734ae58`):** 799 tests collected, all pass (1624 s). First hardware results on a Tang Nano 20K rev 3923: the HDMI test pattern, and the SDRAM memory test clean at read point 5 with one phase step of margin on each side, but only when the I/O-cell register option is off; with it on, flops with CE / SET / RESET packed into I/O cells misbehave, so the option is now off by default (`gateware/README.md`, "I/O-register i I/O-cellerna"). TVP decoders and receivers are still untested. Before it:  (2026-10-20, main after task 46, tested on `a169638`, merged as `61ec85b`): 799 tests collected, all pass (1654 s); M0 built from it. The first hardware run (home bench 2026-10-20) found the bouncing square wrapping at the left edge; fixed here with a regression test. Before it (main after task 35, tested on `52c2ffe`): 797 tests collected, all pass, run one
process per simulation test; the three strict xfail tests of the second review (Core #21-#23) are plain
tests now. M0, M4 and M6 built from `52c2ffe` with and without `HDMI=1`, all clocks over 75 MHz after
routing, the HDMI pairs packed as in M0 (M6 13190 LUT4, with `HDMI=1` 13544; 29 BSRAM). Nothing has
run on hardware.

Built with the open toolchain, figures after routing, every clock above its 75 MHz
requirement, HDMI pairs of M2, M2s, M4 and M6 packed as in M0. Root-accepted by Codex: M0, M4
and M6 with default options from `bf05ac0` (before the FIFO change below), and the
`HDMI=1`/`VINTERP=1` builds from `46a1e4f` and `bf05ac0`; the builds from `2c64672` and the M2,
M2s, M2a, M3, M1 and M1s builds have no root acceptance.

| Top | Built from | Seed | Note |
|---|---|---:|---|
| M0 | `52c2ffe` | 0 | reference for the HDMI pairs; 789 LUT4, with `HDMI=1` 950 |
| M2, M2s | `0da655d` | 0 | I/O registers in the I/O cells; the display changed since only behind VINTERP |
| M2a | `dc307bc` | 0 | memory test; the modules it uses are unchanged since |
| M3 | `94a2b32` | 0 | wiring probe; no BUFG flag on the decoder clocks |
| M4 | `52c2ffe` | 0 | 5 810 LUT4, lowest clock 115.06 MHz; with `HDMI=1` 5 993 LUT4, 123.00 MHz; with `HDMI=1 VINTERP=1` from `2c64672` (6 427 LUT4, 116.33 MHz); each option alone from `bf05ac0` (Codex) |
| M6 | `52c2ffe` | 2 | with RSSI, SCAN, the flash store (`--mspi_as_gpio`) and the HDMI range field: 13 190 LUT4, lowest clock 103.80 MHz; with `HDMI=1` 13 544 LUT4, 103.80 MHz; with `HDMI=1 VINTERP=1` from `c852cb9`, the same build inputs (13 997 LUT4, 33 BSRAM, 115.41 MHz); `VINTERP=1` alone from `bf05ac0` (Codex); seeds 0-3 from `94a2b32` |

M6 with both `HDMI=1` and `VINTERP=1` did not place until 2026-10-14: LUT positions ran out
(ALUs, LUT RAM and flip-flops without a LUT of their own share them). The mixer's two input
FIFOs moved from LUT RAM to block RAM (`async_fifo.v` `RD_REG`, same data on every clock,
proven formally); M4 and M6 lost about 2 400 LUT4 each. Details in gateware/README.md,
"M6 med HDMI och VINTERP".

What changed on 2026-10-12, with figures in [gateware/README.md](gateware/README.md):

- The decoder SCLK pins carry no BUFG flag. Three BUFGs competed for global wires, and
  some placements left `clocks.clk_27` unroutable in M6.
- M2, M2s, M2a, M4 and M6 are built with their I/O registers in the I/O cells (owner's
  decision), so the memory test on the board speaks for the picture builds.
- All 260 seeds of the C3 interference campaign have run: 257 pass with their original
  stimulus, three (1345, 1434, 1444) once four clean fields follow it. They found one RTL
  fault, fixed: the line the field store joins in the middle after LOW counted as stored.
  See [gateware/sim/FUZZ_2026-10-07.md](gateware/sim/FUZZ_2026-10-07.md).
- The two timing assumptions the formal proofs leave open (frame_low/ll_low before line 0,
  a line-buffer slot written before it is read) are checked in every field-store and chain
  simulation, with negative controls.
- Vertical interpolation (two source lines per output line in BUF) is the build option
  `VINTERP=1`, off by default: about 500 LUT4 and 4 BSRAM more in M4 and M6.
- The output stays DVI by default. `HDMI=1` sends HDMI with an AVI InfoFrame (RGB, VIC 4 or
  19), simulated against a decoder; no real sink has seen it. Since 2026-10-18 the range is a
  choice in the M6 menu: `FULL` (default, as before) or `LTD`, which scales the pixels to 16-235
  and says so in the InfoFrame (Core #23). The board cannot read the screen's EDID, so which one
  shows black right is decided on the bench (hub `docs/MATPROTOKOLL.md`, sheet 16).
- In LOW the varying line of each output frame can be placed before vsync instead of after
  it (`WAIT_BEFORE_VSYNC` in `genlock_timing.v`, default 0), so that vsync-to-picture is the
  same in every frame. Proven formally and simulated, but at 720p it shows each line 0.56 ms
  later, more than the 16-line LOW ring holds at the bottom of the picture; see gateware/README.md.

M6 has a TV/VCR filter field for both decoders and an HDMI range field (`FULL`/`LTD`); the
UART row shows the requested filter as `T` or `V` and the range as `F` or `L`. Which filter
mode holds lock and picture better is not measured.
M6 also reads both receivers' RSSI from the Puck rev A board's ADS1115 once per field
(`rssi_adc.v`), with a calibration page in the menu and RSSI in the UART row (87 bytes since the
HDMI range, 85 before it, 62 before RSSI).
A receiver whose calibrated RSSI stays low while the other's does not loses the mixer's
pairs before its picture breaks up; its lines are never left out for it. Simulated against
a model of the ADC; thresholds are set on the bench. A menu SCAN steps all 48 channels and
keeps the one where a decoder locks with the least noise (no RSSI needed), and band,
channel, modes, filter, HDMI range and RSSI calibration are saved in the board's SPI flash and loaded
at start (a record only after a change has stood still for 3 s; simulated against a flash
model, not tried on the board).
Earlier acceptance receipts (C1, C2, C3) are kept in [gateware/README.md](gateware/README.md).

Most of this code was written with heavy AI assistance (Claude) and reviewed
by the project owner; see the hub's
[REVIEW.md](https://github.com/LAP87/OpenVRX/blob/main/REVIEW.md) for what to
attack first.

## Layout

| Path | What |
|---|---|
| `gateware/rtl/` | Modules (see `gateware/README.md` for the full table) |
| `gateware/top/` | Milestone top levels: `m0` test pattern, `m2a_memtest` (SDRAM memory test), `m3_probe` (wiring check) ... `m4_dual_mix` (two decoders + mixer), `m6_puck_proto` (puck step 1) |
| `gateware/boards/` | Tang Nano 20K pin constraints per top |
| `gateware/sim/` | cocotb testbenches |
| `gateware/model/` | Python reference models (BT.656, line mixer, field store and display mapping, channel table, font) and vector generator |
| `gateware/vectors/` | Generated BT.656 test vectors with expected results |
| `gateware/tools/` | `snowlog.py` (UART log to CSV), `build_manifest.py` (checks build hashes), `tmds_fuses.py` (compares built HDMI pairs), I/O bank guards and formal proof tests |
| `mixer/` | Original floating-point mixer prototype (Python, OpenCV) |
| `tests/latency/` | Glass-to-glass latency analysis from a high-speed video |

## Setup

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Icarus Verilog 12 must be on `PATH`, or built into `.tools/iverilog/` (the
testbenches look there first).

## Run

```sh
.venv/bin/python gateware/tools/run_suite.py --quick   # before every commit: the tests in gateware/tools/quick_tests.txt
.venv/bin/python gateware/tools/run_suite.py       # before every merge: whole suite, one process per simulation test, ten at a time
.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools   # same tests in one process (over 90 min)
gateware/build.sh m6_puck_proto                   # seed from boards/m6_puck_proto.seed -> gateware/build/m6_puck_proto.fs
.venv/bin/python gateware/tools/build_manifest.py verify gateware/build/m6_puck_proto.build.json --root .
openFPGALoader -b tangnano20k gateware/build/m6_puck_proto.fs
```

The quick list is chosen from the measured times of a full run (`run_suite.py --pick-quick 300`):
the fastest test of every file, then the fastest of the rest. `--quick` refuses (exit status 2) when the
list names a test that is no longer collected; pick a new list after the next full run. The list of
2026-10-18 holds 720 of the 797 tests (204 s in a fresh copy); the formal proofs and 76 simulations of
40-314 s each, `test_puck_ui` among them, run only in the full suite.

Each build uses a frozen source copy and writes a manifest with source and
artifact hashes, tool versions, options and clock timing. A failed build leaves
no bitstream at the normal output path; previous results stay in
`gateware/build/previous/`. Diagnostic files stay in the failed run's directory.

Detailed documentation (wiring per milestone, mixer rules, menu, buffered and
low-latency mode, toolchain pitfalls) is in [gateware/README.md](gateware/README.md),
in Swedish for now. Bring-up on hardware, step by step: [gateware/BRINGUP.md](gateware/BRINGUP.md).

## License

[CERN-OHL-S-2.0](https://ohwr.org/cern_ohl_s_v2.txt), see [LICENSE](LICENSE).
