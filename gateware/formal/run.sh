#!/usr/bin/env bash
# Formal proofs with yosys alone (no external SMT solver): every clock becomes
# a free input sampled by one global clock (clk2fflogic), all registers start
# at 0, and `sat -tempinduct` proves the assertions by k-induction.
#   gateware/formal/run.sh            # all harnesses
# Exit status 0 only if every proof closes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
bin="$here/../../.venv/bin"
work="$here/build"
mkdir -p "$work"
cd "$work"
export TMPDIR="$work"

check() {   # name, top, depth, extra yosys commands after reading, sources...
    # one clock: FLOW="chformal -lower;" makes every step one clock cycle; several clocks need clk2fflogic (the default)
    # DEFS="-D..." adds Verilog defines (FORMAL_NO_STRENGTHEN leaves out the induction strengthening)
    local name=$1 top=$2 depth=$3 extra=$4; shift 4
    "$bin/yowasp-yosys" -q -l "$name.log" -p "read_verilog -formal -DFORMAL ${DEFS-} $*; $extra prep -top $top; flatten; \
        memory_map; opt_clean; ${FLOW-clk2fflogic;} \
        sat -tempinduct -prove-asserts -set-assumes -set-init-zero -seq 1 -maxsteps $depth" >/dev/null 2>&1 || true
    grep -q "Induction step proven: SUCCESS" "$name.log"
}
prove() {
    if check "$@"; then echo "PROVEN  $1"; else echo "FAILED  $1 (see $work/$1.log)"; return 1; fi
}
must_fail() {   # negative control: a deliberately broken design must give a real counterexample from reset
    check "$@" || true
    if grep -q "model found for base case: FAIL" "$1.log"; then
        echo "CONTROL OK  $1 (counterexample from reset, as it must)"
    else
        echo "BROKEN CHECK  $1 found no counterexample although the design is wrong"; return 1
    fi
}

status=0
fifo="$here/../rtl/async_fifo.v"
prove async_fifo_depth4 fifo_props 20 "" "$fifo" "$here/fifo_props.v" || status=1
prove async_fifo_depth8 fifo_props 30 "chparam -set AW 3 fifo_props;" "$fifo" "$here/fifo_props.v" || status=1
# negative controls: a FIFO that never reports full must overflow, one that never reports empty must underflow
sed 's/^    assign full = .*/    assign full = 1'"'"'b0;/' "$fifo" > never_full.v
must_fail async_fifo_never_full fifo_props 20 "" "$work/never_full.v" "$here/fifo_props.v" || status=1
sed 's/^    assign empty = .*/    assign empty = 1'"'"'b0;/' "$fifo" > never_empty.v
must_fail async_fifo_never_empty fifo_props 20 "" "$work/never_empty.v" "$here/fifo_props.v" || status=1
FLOW="chformal -lower;" prove genlock_timing genlock_props 130 "" "$here/../rtl/genlock_timing.v" "$here/genlock_props.v" || status=1
# negative controls: without the wait limit a frame can stall forever while locked; with two back-porch
# lines skipped a frame is shorter than V_TOTAL - 1; without the hold-off two cut frames can follow each other
sed 's/wait_n == MAX_WAIT);/1'"'"'b0);/' "$here/../rtl/genlock_timing.v" > genlock_nolimit.v
grep -q "1'b0);" genlock_nolimit.v
FLOW="chformal -lower;" must_fail genlock_no_wait_limit genlock_props 130 "" "$work/genlock_nolimit.v" "$here/genlock_props.v" || status=1
sed "s/vc <= vc + 12'd2; /vc <= vc + 12'd3; /" "$here/../rtl/genlock_timing.v" > genlock_short.v
grep -q "vc + 12'd3" genlock_short.v
FLOW="chformal -lower;" must_fail genlock_short_frame genlock_props 130 "" "$work/genlock_short.v" "$here/genlock_props.v" || status=1
sed 's/early_n == JUMP_AFTER - 1 \&\& hold == 0/early_n == JUMP_AFTER - 1/' "$here/../rtl/genlock_timing.v" > genlock_nohold.v
! grep -q "hold == 0" genlock_nohold.v
FLOW="chformal -lower;" must_fail genlock_no_holdoff genlock_props 130 "" "$work/genlock_nohold.v" "$here/genlock_props.v" || status=1

# ---- clock domain crossings of fb_backend.v (rtl/cdc_sync.v, formal/README.md)
cdc="$here/../rtl/cdc_sync.v"
prove cdc_toggle toggle_props 12 "" "$cdc" "$here/toggle_props.v" || status=1
prove cdc_level level_props 40 "" "$cdc" "$here/level_props.v" || status=1
# Not proven (formal/README.md, "Öppet: s_ll_lines"): the low-latency line count is held only until the next
# field starts, which for a field that ends right after line 1 is one SDRAM clock after its trigger flips.
# The toggle proof with din held for one sender clock does not hold (compare cdc_toggle_data_early):
# prove cdc_toggle_ll_lines toggle_props 12 "chparam -set H 1 toggle_props;" "$cdc" "$here/toggle_props.v"
# line buffer slots: genlock_timing's own (separately proven) assertions are assumptions here
lb_flow="chformal -lower; chformal -assert -assert2assume a:src=*genlock_timing.v*;"
lb_src=("$here/../rtl/genlock_timing.v" "$cdc" "$here/ycbcr2rgb_stub.v" "$here/linebuf_props.v")
FLOW="$lb_flow" prove fb_linebuf_slots linebuf_props 20 "" "${lb_src[@]}" "$here/../rtl/fb_display.v" || status=1
# negative controls, without the induction strengthening so that the counterexample comes from the
# property itself: the toggle edge taken straight from the other domain (no synchroniser stage) delivers
# torn data; flips every 8 sender clocks lose events; data that changes 2 sender clocks after its flip
# arrives wrong; the mode bit used without its synchroniser changes between clock edges; a view is not
# settled two edges after a change (the first sample may resolve to the old value); a request into the
# slot being read (no one-line prefetch offset) hits the slot the display reads
sed 's/assign event_now = t\[2\] != t\[1\];/assign event_now = t[0] != tgl;/' "$cdc" > cdc_nosync.v
grep -q "t\[0\] != tgl" cdc_nosync.v
DEFS=-DFORMAL_NO_STRENGTHEN must_fail cdc_toggle_no_sync toggle_props 40 "" "$work/cdc_nosync.v" "$here/toggle_props.v" || status=1
DEFS=-DFORMAL_NO_STRENGTHEN must_fail cdc_toggle_too_often toggle_props 40 "chparam -set S 8 -set H 8 toggle_props;" "$cdc" "$here/toggle_props.v" || status=1
DEFS=-DFORMAL_NO_STRENGTHEN must_fail cdc_toggle_data_early toggle_props 40 "chparam -set H 2 toggle_props;" "$cdc" "$here/toggle_props.v" || status=1
sed 's/assign q = s\[1\];/assign q = d;/' "$cdc" > cdc_level_nosync.v
grep -q "assign q = d;" cdc_level_nosync.v
must_fail cdc_level_no_sync level_props 20 "" "$work/cdc_level_nosync.v" "$here/level_props.v" || status=1
must_fail cdc_level_two_edges level_props 20 "chparam -set SETTLE 2 level_props;" "$cdc" "$here/level_props.v" || status=1
sed "s/fetch_slot <= src_next\[1:0\] + 2'd1;/fetch_slot <= src_next[1:0];/" "$here/../rtl/fb_display.v" > fb_display_same_slot.v
grep -q "fetch_slot <= src_next\[1:0\];" fb_display_same_slot.v
DEFS=-DFORMAL_NO_STRENGTHEN FLOW="$lb_flow" must_fail fb_linebuf_same_slot linebuf_props 30 "" "${lb_src[@]}" "$work/fb_display_same_slot.v" || status=1
exit $status
