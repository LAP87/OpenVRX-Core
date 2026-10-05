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
    local name=$1 top=$2 depth=$3 extra=$4; shift 4
    "$bin/yowasp-yosys" -q -l "$name.log" -p "read_verilog -formal -DFORMAL $*; $extra prep -top $top; flatten; \
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
exit $status
