# OpenVRX-Core

> Part of the [OpenVRX](https://github.com/LAP87/OpenVRX) family: FPGA gateware
> shared by every OpenVRX receiver variant.

Verilog for a Tang Nano 20K (Gowin GW2AR-18), built with a fully open
toolchain. Two TVP5150AM1 decoders deliver BT.656; the FPGA pairs their lines,
picks or blends the cleaner one per line, and outputs 720p over the board's
HDMI connector, either through an SDRAM field buffer or in a genlocked
low-latency mode. Also: RX5808 channel control over SPI, an OLED menu, an
on-screen display, a "snow meter" and a UART measurement log.

**Status (2026-10-10, accepted C3 display checker `79b1406`):** the frozen
regression has 566 passed outcomes across all 39 test files, with zero failures,
skips, xfails, xpasses or missing outcomes, in **1:21:34 (4893.875 s)**. All 157
frozen source-input hashes are unchanged. Formal checks passed 7 proofs and 14
negative-control counterexamples. Acceptance receipt SHA-256:
`a1944cc5b161fe12535cee25acb743a91455c3617d1260ff0bde3ce2e0746847`.

The display checker excludes a pre-switch frame only when its active picture
overlaps the switch, using the observed NTSC/PAL line timing. Fifty saved traces
pass; seed 1249 also passes a native replay with identical stimulus and traces.
Corrupted ring words and source mappings still fail. The suite's XML postprocessor
initially rejected a pure Python parameter name containing `/`; the separate
acceptance filters out non-cocotb candidates while retaining all 19 actual XML
report bindings. The completed tests were not rerun.

The M4 seed-0 and M6 seed-3 routing reports, M0 reference manifest and four HDMI
IOB-fuse checks remain the accepted `8d7b0e9` build evidence. Their existing M4/M6
input manifests (46/47 inputs) match the accepted 8d inputs byte-for-byte; `79b1406`
was not freshly routed. The 24 archived build artifacts are unchanged. See
[gateware/README.md](gateware/README.md) for the figures and limits.

The older 490-/447-pass suites and C1's M6 seed-2 routing failure remain historical.
The board default is still seed 2, and the accepted seed-3 report does not satisfy
C2's requirement for a new seed-2 build. A fresh 260-seed campaign on accepted final
main remains pending. No FPGA gateware has been verified on hardware.

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
.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools
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
