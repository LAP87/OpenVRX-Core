#!/usr/bin/env bash
# Build a Tang Nano 20K bitstream with the open toolchain from the project venv
# (yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, gowin_pack from apycula).
#   gateware/build.sh m0_testpattern
#   PULL=UP gateware/build.sh m3_probe      # weak pull-ups (or DOWN) on the decoder data pins: pull test
#   SDRAM_PHASE=12 gateware/build.sh m2a_memtest   # SDRAM clock phase in sixteenths of a period (clocks_sdram.v)
#   SEED=3 gateware/build.sh m6_puck_proto  # place-and-route seed (default: boards/<top>.seed if there is one, else 0)
#   IOREG=0 gateware/build.sh m4_dual_mix   # I/O registers in the I/O cells: 1 or 0 (default: 1 for the SDRAM tops)
#   VINTERP=1 gateware/build.sh m6_puck_proto  # blend two source lines per output line in BUF (fb_display.v; default 0)
#   HDMI=1 gateware/build.sh m0_testpattern    # HDMI with an AVI InfoFrame instead of DVI (tmds_link.v; default 0)
# Output: gateware/build/<top>.fs + <top>.build.json (same suffixes for PULL / SDRAM_PHASE / VINTERP / HDMI /
# an IOREG other than the top's default).
# Failed builds leave no bitstream at that path; previous outputs are saved in build/previous/.
# — flash with openFPGALoader -b tangnano20k <file>
set -euo pipefail
top="${1:?usage: build.sh <top module name>}"
here="$(cd "$(dirname "$0")" && pwd)"
bin="$here/../.venv/bin"
out="$here/build"
manifest="$here/tools/build_manifest.py"
[[ "$top" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -f "$here/top/$top.v" ] || {
  echo "unknown top module: $top" >&2; exit 1;
}
out_fs="$top.fs"
if [ -n "${PULL:-}" ]; then
  case "$PULL" in UP|DOWN) ;; *) echo "PULL must be UP or DOWN" >&2; exit 1 ;; esac
  out_fs="${top}_pull${PULL,,}.fs"
fi
# optional Verilog define: another SDRAM clock phase than the default of clocks_sdram.v
defs=""
if [ -n "${SDRAM_PHASE:-}" ]; then
  case "$SDRAM_PHASE" in [0-9]|1[0-5]) ;; *) echo "SDRAM_PHASE must be 0..15" >&2; exit 1 ;; esac
  defs="-DSDRAM_PHASE=$SDRAM_PHASE"
  out_fs="${out_fs%.fs}_phase$SDRAM_PHASE.fs"
fi
# optional: vertical interpolation in the field store's display (fb_backend.v VINTERP, default 0)
vinterp="${VINTERP:-0}"
case "$vinterp" in 0|1) ;; *) echo "VINTERP must be 0 or 1" >&2; exit 1 ;; esac
if [ "$vinterp" = 1 ]; then
  defs="$defs -DVINTERP=1"
  out_fs="${out_fs%.fs}_vinterp.fs"
fi
# optional: HDMI with an AVI InfoFrame instead of DVI (tmds_link.v HDMI, default 0)
hdmi="${HDMI:-0}"
case "$hdmi" in 0|1) ;; *) echo "HDMI must be 0 or 1" >&2; exit 1 ;; esac
if [ "$hdmi" = 1 ]; then
  defs="$defs -DHDMI=1"
  out_fs="${out_fs%.fs}_hdmi.fs"
fi
# I/O registers in the I/O cells (nextpnr --vopt ireg_in_iob / oreg_in_iob / ioreg_in_iob), on by default for
# the tops with SDRAM: the SDRAM read and write timing then does not depend on where the placer puts the
# registers, so the memory test on the board (m2a_memtest) speaks for the picture builds. Owner's decision
# 2026-10-12; README section "I/O-register i I/O-cellerna".
case " m2_moneagle_color m2s_moneagle_color_sync m2a_memtest m4_dual_mix m6_puck_proto " in
  *" $top "*) ioreg_default=1 ;;
  *) ioreg_default=0 ;;
esac
ioreg="${IOREG:-$ioreg_default}"
case "$ioreg" in 0|1) ;; *) echo "IOREG must be 0 or 1" >&2; exit 1 ;; esac
ioreg_opts=()
if [ "$ioreg" = 1 ]; then ioreg_opts=(--vopt ireg_in_iob --vopt oreg_in_iob --vopt ioreg_in_iob); fi
if [ "$ioreg" != "$ioreg_default" ]; then out_fs="${out_fs%.fs}_ioreg$ioreg.fs"; fi
# The onboard SPI flash's MSPI pins (57, 59-62) as user I/O after configuration, for the tops that keep
# settings there (flash_store.v): gowin_pack --mspi_as_gpio. Without it they stay configuration pins.
case " m6_puck_proto " in
  *" $top "*) mspi=1 ;;
  *) mspi=0 ;;
esac
pack_opts=()
if [ "$mspi" = 1 ]; then pack_opts=(--mspi_as_gpio); fi
# Place-and-route seed (boards/<top>.seed keeps the one a top was built with). "Can't route the <clock> net"
# came from BUFG cells competing for global wires (README, "Klockroutningen, 2026-10-12"); another seed is a
# way out, not a fix.
seed="${SEED:-}"
if [ -z "$seed" ] && [ -f "$here/boards/$top.seed" ]; then seed="$(tr -d '[:space:]' < "$here/boards/$top.seed")"; fi
seed="${seed:-0}"
[[ "$seed" =~ ^[0-9]+$ ]] || { echo "SEED must be a nonnegative integer" >&2; exit 1; }
freq="${FREQ_MHZ:-75}"
[[ "$freq" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v f="$freq" 'BEGIN {exit !(f > 0)}' || {
  echo "FREQ_MHZ must be positive" >&2; exit 1;
}
for tool in python yowasp-yosys yowasp-nextpnr-himbaechel-gowin gowin_pack; do
  [ -x "$bin/$tool" ] || { echo "missing tool: $bin/$tool" >&2; exit 1; }
done

mkdir -p "$out"
exec 9>"$out/.build.lock"
flock 9                         # do not publish two builds into the same directory at once
prefix="${out_fs%.fs}"
work="$(mktemp -d "$out/.${prefix}.XXXXXX")"
attempt=0
cleanup() {
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then
    if [ "$attempt" -eq 1 ]; then rm -f "$out/$out_fs" "$out/$prefix.build.json"; fi
    echo "build failed; diagnostics: $work" >&2
  else
    rm -rf "$work"
  fi
  exit "$rc"
}
trap cleanup EXIT
"$bin/python" "$manifest" snapshot "$here/.." "$top" "$work/inputs.json" \
  --freq "$freq" --seed "$seed" --pull "${PULL:-}" --phase "${SDRAM_PHASE:-}" --ioreg "$ioreg" --vinterp "$vinterp" --hdmi "$hdmi" --mspi "$mspi" --copy-to "$work/source"
source_here="$work/source/gateware"
manifest="$source_here/tools/build_manifest.py"
# Remove the old result from the flash path before starting, while keeping it recoverable.
previous=""
for ext in fs build.json cst sdc synth.json stat.txt yosys.log pnr.json pnr.log; do
  if [ -e "$out/$prefix.$ext" ]; then
    if [ -z "$previous" ]; then
      mkdir -p "$out/previous"
      previous="$(mktemp -d "$out/previous/${prefix}.XXXXXX")"
    fi
    mv "$out/$prefix.$ext" "$previous/"
  fi
done
attempt=1
cd "$work"
export TMPDIR="$work"           # yowasp/ABC need a temp directory visible to WASI
srcs=("$source_here"/rtl/*.v "$source_here/top/$top.v")
cat "$source_here/boards/tangnano20k.cst" > "$prefix.cst"
if [ -f "$source_here/boards/$top.cst" ]; then cat "$source_here/boards/$top.cst" >> "$prefix.cst"; fi
if [ -n "${PULL:-}" ]; then
  sed -i -E "/IO_PORT \"tvp[ab]_d\[[0-6]\]/ s/PULL_MODE=NONE/PULL_MODE=$PULL/" "$prefix.cst"   # not d[7]: YOUT7 is the I2C address strap
fi
"$bin/yowasp-yosys" -q -l "$prefix.yosys.log" \
  -p "read_verilog -I$source_here/rtl $defs ${srcs[*]}; synth_gowin -top $top -family gw2a -json $prefix.synth.json; tee -o $prefix.stat.txt stat"
sdc=()
if [ -f "$source_here/boards/$top.sdc" ]; then cp "$source_here/boards/$top.sdc" "$prefix.sdc"; sdc=(--sdc "$prefix.sdc"); fi
"$bin/yowasp-nextpnr-himbaechel-gowin" --json "$prefix.synth.json" --write "$prefix.pnr.json" \
  --device GW2AR-LV18QN88C8/I7 --vopt family=GW2A-18C --vopt cst="$work/$prefix.cst" \
  --freq "$freq" "${sdc[@]}" --seed "$seed" "${ioreg_opts[@]}" --log "$prefix.pnr.log" --quiet || {
    grep -E "^ERROR" "$prefix.pnr.log" >&2 || true
    if grep -q "Can't route the .* net" "$prefix.pnr.log"; then echo "clock routing failed with seed $seed: try SEED=<n> $0 $top" >&2; fi
    exit 1
  }
"$bin/python" "$manifest" route "$prefix.pnr.log"
"$bin/gowin_pack" -c -d GW2A-18C "${pack_opts[@]}" -o "$out_fs" "$prefix.pnr.json"
"$bin/python" "$manifest" finish "$here/.." inputs.json "$prefix" "$prefix.build.json"
# The bitstream is published last, after its logs, hashes and manifest are ready.
for ext in cst sdc synth.json stat.txt yosys.log pnr.json pnr.log build.json; do
  if [ -f "$prefix.$ext" ]; then mv "$prefix.$ext" "$out/"; fi
done
mv "$out_fs" "$out/"
echo "built $out/$out_fs"
echo "manifest $out/$prefix.build.json"
# nextpnr prints the clock table twice: an estimate after placement, then the result after routing. Show the last.
grep -E "(LUT4|DFF|OSER10|rPLL|BSRAM):[[:space:]]+[0-9]+/" "$out/$prefix.pnr.log" || true
awk '/Max frequency for clock/ { if (!in_table) table=""; table=table $0 ORS; in_table=1; next } { in_table=0 } END { printf "%s", table }' "$out/$prefix.pnr.log"
