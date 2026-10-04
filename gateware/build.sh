#!/usr/bin/env bash
# Build a Tang Nano 20K bitstream with the open toolchain from the project venv
# (yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, gowin_pack from apycula).
#   gateware/build.sh m0_testpattern
# Output: gateware/build/<top>.fs  — flash with openFPGALoader -b tangnano20k <file>
set -euo pipefail
top="${1:?usage: build.sh <top module name>}"
here="$(cd "$(dirname "$0")" && pwd)"
bin="$here/../.venv/bin"
out="$here/build"
mkdir -p "$out"
cd "$out"
export TMPDIR="$out"     # yowasp (WASI) only sees the working directory; ABC needs a temp dir there

srcs=("$here"/rtl/*.v "$here/top/$top.v")
# board pins + optional per-design pins (boards/<top>.cst)
cat "$here/boards/tangnano20k.cst" > "$top.cst"
if [ -f "$here/boards/$top.cst" ]; then cat "$here/boards/$top.cst" >> "$top.cst"; fi
"$bin/yowasp-yosys" -q -l "$top.yosys.log" \
  -p "read_verilog ${srcs[*]}; synth_gowin -top $top -family gw2a -json $top.synth.json; tee -o $top.stat.txt stat"
# optional per-clock constraints (boards/<top>.sdc); --freq covers clocks it does not name
sdc=()
if [ -f "$here/boards/$top.sdc" ]; then cp "$here/boards/$top.sdc" "$top.sdc"; sdc=(--sdc "$top.sdc"); fi
"$bin/yowasp-nextpnr-himbaechel-gowin" --json "$top.synth.json" --write "$top.pnr.json" \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst="$out/$top.cst" \
  --freq "${FREQ_MHZ:-75}" "${sdc[@]}" --log "$top.pnr.log" --quiet
"$bin/gowin_pack" -c -d GW2A-18C -o "$top.fs" "$top.pnr.json"
echo "built $out/$top.fs"
grep -E "Max frequency for clock|Device utilisation|LUT4|DFF|OSER10|rPLL|BSRAM" "$top.pnr.log" | head -20 || true
