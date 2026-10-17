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
# RD_REG = 1 (registered read, block RAM; the mixer's input FIFOs): the same properties
prove async_fifo_rd_reg_depth4 fifo_props 20 "chparam -set RD_REG 1 fifo_props;" "$fifo" "$here/fifo_props.v" || status=1
prove async_fifo_rd_reg_depth8 fifo_props 30 "chparam -set AW 3 -set RD_REG 1 fifo_props;" "$fifo" "$here/fifo_props.v" || status=1
# negative control: a register loaded from the current read pointer instead of its next value
# still shows the popped word after a pop
sed 's/always @(posedge rclk) rd_q <= mem\[rd_next\];/always @(posedge rclk) rd_q <= mem[rbin[AW-1:0]];/' "$fifo" > rd_reg_late.v
grep -q 'rd_q <= mem\[rbin\[AW-1:0\]\];' rd_reg_late.v
must_fail async_fifo_rd_reg_late fifo_props 20 "chparam -set RD_REG 1 fifo_props;" "$work/rd_reg_late.v" "$here/fifo_props.v" || status=1
FLOW="chformal -lower;" prove genlock_timing genlock_props 130 "" "$here/../rtl/genlock_timing.v" "$here/genlock_props.v" || status=1
# negative controls: without the wait limit a frame can stall forever while locked; with two back-porch
# lines skipped a normal frame is shorter than V_TOTAL - 1; without the hold-off two cuts can follow each
# other; jumping straight to the last line loses sync; a sticky recovery flag allows later short frames
sed 's/wait_n == MAX_WAIT/1'"'"'b0/' "$here/../rtl/genlock_timing.v" > genlock_nolimit.v
! grep -q 'wait_n == MAX_WAIT' genlock_nolimit.v
FLOW="chformal -lower;" must_fail genlock_no_wait_limit genlock_props 130 "" "$work/genlock_nolimit.v" "$here/genlock_props.v" || status=1
sed "s/vc <= vc + 12'd2; /vc <= vc + 12'd3; /" "$here/../rtl/genlock_timing.v" > genlock_short.v
grep -q "vc + 12'd3" genlock_short.v
FLOW="chformal -lower;" must_fail genlock_short_frame genlock_props 130 "" "$work/genlock_short.v" "$here/genlock_props.v" || status=1
sed 's/early_n == JUMP_AFTER - 1 \&\& hold == 0/early_n == JUMP_AFTER - 1/' "$here/../rtl/genlock_timing.v" > genlock_nohold.v
! grep -q "hold == 0" genlock_nohold.v
FLOW="chformal -lower;" must_fail genlock_no_holdoff genlock_props 130 "" "$work/genlock_nohold.v" "$here/genlock_props.v" || status=1
sed 's/? V_SYNC_START :/? V_TOTAL - 1 :/' "$here/../rtl/genlock_timing.v" > genlock_nosync.v
grep -Fq '? V_TOTAL - 1 :' genlock_nosync.v
FLOW="chformal -lower;" must_fail genlock_cut_no_sync genlock_props 130 "" "$work/genlock_nosync.v" "$here/genlock_props.v" || status=1
sed 's/recover <= cut; cut <=/recover <= recover || cut; cut <=/' "$here/../rtl/genlock_timing.v" > genlock_sticky.v
grep -Fq 'recover <= recover || cut;' genlock_sticky.v
FLOW="chformal -lower;" must_fail genlock_sticky_recovery genlock_props 130 "" "$work/genlock_sticky.v" "$here/genlock_props.v" || status=1
# WAIT_BEFORE_VSYNC = 1: the same properties, and every frame ends with its full back porch after the sync
vb="chparam -set MODE 1 genlock_props;"
FLOW="chformal -lower;" prove genlock_timing_wait_before_vsync genlock_props 150 "$vb" "$here/../rtl/genlock_timing.v" "$here/genlock_props.v" || status=1
# negative controls: the natural frame skips a back-porch line instead of a front-porch line; the wait
# ends past the first sync line
sed -e 's/end else if (vc == V_ACTIVE - 1)/end else if (vc == V_SYNC_END - 1)/' -e 's/vc <= V_ACTIVE + 1;/vc <= V_SYNC_END + 1;/' \
    "$here/../rtl/genlock_timing.v" > genlock_vb_short_bp.v
grep -q 'vc <= V_SYNC_END + 1;' genlock_vb_short_bp.v
FLOW="chformal -lower;" must_fail genlock_wait_before_vsync_short_back_porch genlock_props 150 "$vb" "$work/genlock_vb_short_bp.v" "$here/genlock_props.v" || status=1
sed 's/vc <= V_SYNC_START; rel_trig <= pend || trig;/vc <= V_SYNC_START + 1; rel_trig <= pend || trig;/' \
    "$here/../rtl/genlock_timing.v" > genlock_vb_nosync.v
grep -q 'V_SYNC_START + 1; rel_trig' genlock_vb_nosync.v
FLOW="chformal -lower;" must_fail genlock_wait_before_vsync_lost_sync_line genlock_props 150 "$vb" "$work/genlock_vb_nosync.v" "$here/genlock_props.v" || status=1

# ---- clock domain crossings of fb_backend.v (rtl/cdc_sync.v, formal/README.md)
cdc="$here/../rtl/cdc_sync.v"
prove cdc_toggle toggle_props 12 "" "$cdc" "$here/toggle_props.v" || status=1
prove cdc_level level_props 40 "" "$cdc" "$here/level_props.v" || status=1
# the low-latency trigger's send side: flips 16 clocks apart, data held from flip to flip (toggle_props' conditions)
FLOW="chformal -lower;" prove cdc_toggle_tx toggle_tx_props 40 "" "$cdc" "$here/toggle_tx_props.v" || status=1
# line buffer slots: genlock_timing's own (separately proven) assertions are assumptions here
lb_flow="chformal -lower; chformal -assert -assert2assume a:src=*genlock_timing.v*;"
lb_src=("$here/../rtl/genlock_timing.v" "$cdc" "$here/ycbcr2rgb_stub.v" "$here/../rtl/vblend.v" "$here/linebuf_props.v")
FLOW="$lb_flow" prove fb_linebuf_slots linebuf_props 20 "" "${lb_src[@]}" "$here/../rtl/fb_display.v" || status=1
# VINTERP = 1 (Core #24): the same property over both read ports, under the request path's scale
# contract (assumed in linebuf_vi_props.v, with pub_lines held between flips of pub_toggle and ll
# held over a frame region). Negative control: the second line's prefetch asks for the slot the
# first port reads for the rest of the current line (the VI request into src_cur's slot).
vi_src=("$here/../rtl/genlock_timing.v" "$cdc" "$here/ycbcr2rgb_stub.v" "$here/../rtl/vblend.v" "$here/linebuf_vi_props.v")
FLOW="$lb_flow" prove fb_linebuf_vi_slots linebuf_vi_props 90 "" "${vi_src[@]}" "$here/../rtl/fb_display.v" || status=1
sed "s/fetch_slot   <= src_hi\[1:0\] + 2'd1;/fetch_slot   <= src_cur[1:0];/" "$here/../rtl/fb_display.v" > fb_display_vi_cur_slot.v
grep -q "fetch_slot   <= src_cur\[1:0\];" fb_display_vi_cur_slot.v
DEFS=-DFORMAL_NO_STRENGTHEN FLOW="$lb_flow" must_fail fb_linebuf_vi_cur_slot linebuf_vi_props 40 "" "${vi_src[@]}" "$work/fb_display_vi_cur_slot.v" || status=1
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
# a send side that flips at once on every request breaks the spacing
sed 's/wire         ready = since == GAP - 1;/wire         ready = 1'"'"'b1;/' "$cdc" > cdc_tx_noready.v
grep -q "ready = 1'b1;" cdc_tx_noready.v
FLOW="chformal -lower;" must_fail cdc_toggle_tx_no_gap toggle_tx_props 40 "" "$work/cdc_tx_noready.v" "$here/toggle_tx_props.v" || status=1
sed 's/assign q = s\[1\];/assign q = d;/' "$cdc" > cdc_level_nosync.v
grep -q "assign q = d;" cdc_level_nosync.v
must_fail cdc_level_no_sync level_props 20 "" "$work/cdc_level_nosync.v" "$here/level_props.v" || status=1
must_fail cdc_level_two_edges level_props 20 "chparam -set SETTLE 2 level_props;" "$cdc" "$here/level_props.v" || status=1
sed "s/fetch_slot <= src_next\[1:0\] + 2'd1;/fetch_slot <= src_next[1:0];/" "$here/../rtl/fb_display.v" > fb_display_same_slot.v
grep -q "fetch_slot <= src_next\[1:0\];" fb_display_same_slot.v
DEFS=-DFORMAL_NO_STRENGTHEN FLOW="$lb_flow" must_fail fb_linebuf_same_slot linebuf_props 30 "" "${lb_src[@]}" "$work/fb_display_same_slot.v" || status=1
exit $status
