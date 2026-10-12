# OpenVRX-Core

> Part of the [OpenVRX](https://github.com/LAP87/OpenVRX) family: FPGA gateware
> shared by every OpenVRX receiver variant.

Verilog for a Tang Nano 20K (Gowin GW2AR-18), built with a fully open
toolchain. Two TVP5150AM1 decoders deliver BT.656; the FPGA pairs their lines,
picks or blends the cleaner one per line, and outputs 720p over the board's
HDMI connector, either through an SDRAM field buffer or in a genlocked
low-latency mode. Also: RX5808 channel control over SPI, an OLED menu, an
on-screen display, a "snow meter" and a UART measurement log.

**Status (2026-10-12, accepted C2 source `c3fda21`):** the frozen regression
passed all 604 tests in 39 files, with no failures, skips, xfails, xpasses or
missing outcomes, in **1:30:11 (5411.439 s)**. All 157 source-input hashes are
unchanged, and all 570 prior test nodes remain. Root reviewed 19 cocotb report
bindings, 7 formal proofs and 14 actual negative-control counterexamples.
Acceptance receipt SHA-256:
`c783407e79a31e9a09f3bc82f76debff1160aebee80091c25368d261d1c09bfc`.

2026-10-12, Fable: on main 2dca245 the suite collects 651 tests; run one process per
simulation test, ten at a time, all 651 pass (18 min). Two parametrised mixer tests shared a
build directory and raced in that runner; they now build apart. Nothing has run on hardware.

2026-10-12, `gateware/tools/run_suite.py` runs the suite that way and audits that no two
tests share a build directory or cocotb results file: 658 tests pass, nothing shared
(633 s, ten at a time). The audit found three more shared directories, now separate.

M6 has a TV/VCR filter menu for both decoders. An in-flight I2C write retains
its value and SDA lane; NACK retries follow paired polling. The OLED, OSD and
62-byte UART row show the requested menu mode, rather than a register readback.
The parser retains legacy rows. Focused verification passed 56 tests and two
subtests, with nine old-guard cases rejected for their intended semantic faults.

Fresh M0 seed-0, M4 seed-0 and M6 seed-2 builds pass the 75 MHz requirement on
all reported clocks. The five M4/M6 domains, source manifests, 24 archived
artifacts and four TMDS pairs were reviewed. See
[gateware/README.md](gateware/README.md) for clock figures and build hashes.
Older suite and build receipts remain historical; the new seed-2 result does
not erase earlier routing failures.

The prior visible-field boundary and display-checker corrections remain.
The last campaign stopped at 200 of 260 seeds: 199 PASS, 1 FAIL, 60 not run.
Seed 1345 has 72 checked lines against the unchanged minimum of 144; only one
complete eligible active frame arrived before source input ended. A longer
stimulus requires a new source and parameter contract. This campaign is not
accepted, and no FPGA gateware or TV/VCR picture difference is verified on
hardware.

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
.venv/bin/python gateware/tools/run_suite.py       # whole suite, one process per simulation test, ten at a time
.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools   # same tests in one process (over 90 min)
SEED=3 FREQ_MHZ=75 gateware/build.sh m6_puck_proto  # accepted C3 source, seed 3 -> gateware/build/m6_puck_proto.fs
.venv/bin/python gateware/tools/build_manifest.py verify gateware/build/m6_puck_proto.build.json --root .
openFPGALoader -b tangnano20k gateware/build/m6_puck_proto.fs
```

Each build uses a frozen source copy and writes a manifest with source and
artifact hashes, tool versions, options and clock timing. A failed build leaves
no bitstream at the normal output path; previous results stay in
`gateware/build/previous/`. Diagnostic files stay in the failed run's directory.

Detailed documentation (wiring per milestone, mixer rules, menu, buffered and
low-latency mode, toolchain pitfalls) is in [gateware/README.md](gateware/README.md),
in Swedish for now. Bring-up on hardware, step by step: [gateware/BRINGUP.md](gateware/BRINGUP.md).

## License

[CERN-OHL-S-2.0](https://ohwr.org/cern_ohl_s_v2.txt), see [LICENSE](LICENSE).
