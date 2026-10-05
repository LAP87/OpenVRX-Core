#!/usr/bin/env bash
# Build a Tang Nano 20K bitstream with the open toolchain from the project venv
# (yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, gowin_pack from apycula).
#   gateware/build.sh m0_testpattern
#   PULL=UP gateware/build.sh m3_probe      # weak pull-ups (or DOWN) on the decoder data pins: pull test
#   SDRAM_PHASE=12 gateware/build.sh m2a_memtest   # SDRAM clock phase in sixteenths of a period (clocks_sdram.v)
# Output: gateware/build/<top>.fs (with PULL: <top>_pullup.fs / _pulldown.fs; with SDRAM_PHASE: <top>_phase12.fs)
# — flash with openFPGALoader -b tangnano20k <file>
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
out_fs="$top.fs"
if [ -n "${PULL:-}" ]; then
  case "$PULL" in UP|DOWN) ;; *) echo "PULL must be UP or DOWN" >&2; exit 1 ;; esac
  sed -i -E "/IO_PORT \"tvp[ab]_d\[[0-6]\]/ s/PULL_MODE=NONE/PULL_MODE=$PULL/" "$top.cst"   # not d[7]: YOUT7 is the I2C address strap
  out_fs="${top}_pull$(echo "$PULL" | tr 'A-Z' 'a-z').fs"
fi
# optional Verilog define: another SDRAM clock phase than the default of clocks_sdram.v
defs=""
if [ -n "${SDRAM_PHASE:-}" ]; then
  case "$SDRAM_PHASE" in [0-9]|1[0-5]) ;; *) echo "SDRAM_PHASE must be 0..15" >&2; exit 1 ;; esac
  defs="-DSDRAM_PHASE=$SDRAM_PHASE"
  out_fs="${out_fs%.fs}_phase$SDRAM_PHASE.fs"
fi
"$bin/yowasp-yosys" -q -l "$top.yosys.log" \
  -p "read_verilog -I$here/rtl $defs ${srcs[*]}; synth_gowin -top $top -family gw2a -json $top.synth.json; tee -o $top.stat.txt stat"
# optional per-clock constraints (boards/<top>.sdc); --freq covers clocks it does not name
sdc=()
if [ -f "$here/boards/$top.sdc" ]; then cp "$here/boards/$top.sdc" "$top.sdc"; sdc=(--sdc "$top.sdc"); fi
"$bin/yowasp-nextpnr-himbaechel-gowin" --json "$top.synth.json" --write "$top.pnr.json" \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst="$out/$top.cst" \
  --freq "${FREQ_MHZ:-75}" "${sdc[@]}" --log "$top.pnr.log" --quiet
"$bin/gowin_pack" -c -d GW2A-18C -o "$out_fs" "$top.pnr.json"
echo "built $out/$out_fs"
grep -E "Max frequency for clock|Device utilisation|LUT4|DFF|OSER10|rPLL|BSRAM" "$top.pnr.log" | head -20 || true
