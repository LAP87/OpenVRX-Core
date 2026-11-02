// Pair alignment for the C5VRX sample bus: 6-bit samples at 40 MS/s in identical pairs [D, D] (20 MS/s of
// unique samples). Bench 2026-10-27/28 (17 captures): the first sample of a pair could lack a bit whose rising
// edge arrived up to one clock late (bit 2 in 41-66 % of its rising edges, never the second sample), and every
// isolated code-0 sample sat in the first position; the other bits never differed within a pair. The second
// sample is the settled one. This stage finds the pair phase (the parity, as the clock count's LSB since
// reset, whose consecutive samples differ least) and replaces the first sample of every pair with the second:
// q is d one clock late with every pair made identical. Bit-exact counterpart of model/pair_align_ref.py,
// where the rules are written out. In mixer2.v (B_DIGITAL, B_PAIR) in front of cvbs_capture, and in
// top/m7_digin_probe.v in front of the capture of the statistics line (the dump stays the raw bus).
`default_nettype none
module pair_align #(
    parameter WIN_LOG2 = 12,          // decision window: 2^WIN_LOG2 clocks (4 096 = 102 us at 40 MHz)
    parameter HOLD_MIN = 16           // the phase moves only when the chosen parity differed this often in a window
) (
    input  wire                clk,   // the bus clock, 40 MHz
    input  wire                rst,
    input  wire [5:0]          d,
    output reg  [5:0]          q,     // d one clock late, pairs made identical
    output reg                 phase, // parity of a pair's second sample
    output reg  [WIN_LOG2-1:0] mism   // the chosen parity's mismatching pairs in the last window
);
    reg  [WIN_LOG2-1:0] cnt;          // clocks since reset; cnt[0] is the parity of d
    reg                 started;      // a clock has passed since reset: cnt == 0 is a window end
    reg  [5:0]          d1;           // the previous sample
    reg  [WIN_LOG2-1:0] c01, c10;     // mismatching (even, odd) and (odd, even) comparisons in the window
    wire                par  = cnt[0];
    wire                diff = d != d1;
    wire [WIN_LOG2-1:0] cur  = phase ? c01 : c10;
    wire [WIN_LOG2-1:0] oth  = phase ? c10 : c01;
    wire                win_end = started && cnt == {WIN_LOG2{1'b0}};
    always @(posedge clk) begin
        if (rst) begin
            cnt <= 0; started <= 1'b0; d1 <= 6'd0; q <= 6'd0; phase <= 1'b0;
            c01 <= 0; c10 <= 0; mism <= 0;
        end else begin
            cnt     <= cnt + 1'b1;
            started <= 1'b1;
            d1      <= d;
            q       <= (par == phase) ? d : d1;       // the window's decision below applies from the next sample
            if (win_end) begin
                mism <= cur;
                if (cur >= HOLD_MIN && oth < (cur >> 1)) phase <= ~phase;
                c01 <= 0;
                c10 <= {{(WIN_LOG2-1){1'b0}}, diff};  // this comparison opens the new window (par is 0 here)
            end else if (par) begin
                c01 <= c01 + {{(WIN_LOG2-1){1'b0}}, diff};
            end else begin
                c10 <= c10 + {{(WIN_LOG2-1){1'b0}}, diff};
            end
        end
    end
endmodule
`default_nettype wire
