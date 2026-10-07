# OpenVRX-Core

> Part of the [OpenVRX](https://github.com/LAP87/OpenVRX) family: FPGA gateware
> shared by every OpenVRX receiver variant.

Verilog for a Tang Nano 20K (Gowin GW2AR-18), built with a fully open
toolchain. Two TVP5150AM1 decoders deliver BT.656; the FPGA pairs their lines,
picks or blends the cleaner one per line, and outputs 720p over the board's
HDMI connector, either through an SDRAM field buffer or in a genlocked
low-latency mode. Also: RX5808 channel control over SPI, an OLED menu, an
on-screen display, a "snow meter" and a UART measurement log.

**Status:** the regression suite has 372 tests, including simulations against
Python models and build failure controls. Milestone tops build with timing met. **Nothing has run on
hardware yet.** Most of this code was written with heavy AI assistance
(Claude) and reviewed by the project owner; see the hub's
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
.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools
gateware/build.sh m6_puck_proto        # -> gateware/build/m6_puck_proto.fs
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
