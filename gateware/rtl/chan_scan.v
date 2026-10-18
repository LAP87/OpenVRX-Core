// Channel scan without RSSI (M6 menu, SCAN): steps through all N_CH channels (index =
// band * 8 + channel, as vtx_channels.vh) and keeps the one where a decoder locks with the
// lowest noise count (noise_stats.v: luma samples outside 16..235 per 1024 lines).
// Model: model/chan_scan_ref.py. Testbench: sim/tb_chan_scan.v.
//
// Per channel: `tune` pulses with the channel in `idx` (the menu reprograms both RX5808),
// SETTLE_MS for the synthesiser and the decoders, then two noise windows per receiver: the
// first may still hold lines of the previous channel, the second is all from this one. The
// channel is decided when both receivers have had their second window, or MAX_MS after the
// settling; a receiver counts on it if it had its second window and its decoder is locked at
// that moment. The channel's score is the lower noise (second window) of the counting
// receivers. With 1024 lines per window that is
// about 100-160 ms per channel, 5-8 s for 48.
//
// The lowest score wins; on a tie the channel the scan started from, else the earlier channel
// (clean transmitters all score 0, and the pilot's own channel must not lose to a lower table
// entry: review 2026-10-14, SC-1, Core #22). When no channel had a locked decoder
// the scan ends on the channel it started from (found = 0). `abort` (any button) ends the
// scan at once on the starting channel. `done` pulses once with the channel to keep in `idx`,
// and `tune` pulses with it in the same clock.
`default_nettype none
module chan_scan #(
    parameter CLK_HZ = 27_000_000,
    parameter N_CH = 48,
    parameter SETTLE_MS = 30,
    parameter MAX_MS = 200
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,             // one clock
    input  wire        abort,             // one clock
    input  wire [5:0]  cur_idx,           // the channel before the scan
    input  wire [1:0]  locked,            // per decoder: answers and reports H + V lock (this clock domain)
    input  wire        new_a, new_b,      // one clock each: a new noise window value of A / B
    input  wire [19:0] noise_a, noise_b,  // stable from new_* until the next one
    output reg         busy,
    output reg  [5:0]  idx,
    output reg         tune,
    output reg         done,
    output reg         found
);
    localparam MS = CLK_HZ / 1000;
    reg [$clog2(MS+1)-1:0] msc;
    wire ms = (msc == MS - 1);
    always @(posedge clk) msc <= (rst || ms || !busy) ? 0 : msc + 1'b1;

    localparam S_SETTLE = 2'd0, S_MEASURE = 2'd1;
    reg [1:0]  st;
    reg [9:0]  t;                         // ms in this state
    reg [1:0]  wa, wb;                    // noise windows seen since the settling ended (saturate at 2)
    reg [19:0] sa, sb;                    // the second window's values
    reg [5:0]  start_idx, best_idx;
    reg [20:0] best;                      // lowest score so far; bit 20 set = none yet
    reg        have;

    // the score of this channel once both receivers are decided
    wire        ok_a = (wa == 2'd2) && locked[0];
    wire        ok_b = (wb == 2'd2) && locked[1];
    wire [19:0] sc   = (ok_a && ok_b) ? ((sa <= sb) ? sa : sb) : ok_a ? sa : sb;
// this channel replaces the best so far: a lower score, or the same score when it is the
// channel the scan started from (a tie never goes to a later channel otherwise)
wire        better = (ok_a || ok_b) && ({1'b0, sc} < best || (idx == start_idx && {1'b0, sc} == best));
    wire        both_decided = (wa == 2'd2 && wb == 2'd2) || t == MAX_MS;

    always @(posedge clk) begin
        tune <= 1'b0;
        done <= 1'b0;
        if (!busy) begin
            if (start) begin
                busy <= 1'b1; start_idx <= cur_idx; idx <= 0; tune <= 1'b1;
                st <= S_SETTLE; t <= 0; best <= 21'h100000; best_idx <= cur_idx; have <= 1'b0;
            end
        end else if (abort) begin
            busy <= 1'b0; idx <= start_idx; tune <= 1'b1; done <= 1'b1; found <= 1'b0;
        end else begin
            if (ms && t != 10'h3FF) t <= t + 1'b1;
            case (st)
            S_SETTLE: if (ms && t == SETTLE_MS - 1) begin st <= S_MEASURE; t <= 0; wa <= 0; wb <= 0; end
            default: begin
                if (new_a && wa != 2'd2) begin wa <= wa + 1'b1; sa <= noise_a; end
                if (new_b && wb != 2'd2) begin wb <= wb + 1'b1; sb <= noise_b; end
                if (both_decided) begin
                    if (better) begin best <= {1'b0, sc}; best_idx <= idx; have <= 1'b1; end
                    if (idx == N_CH - 1) begin
                        busy <= 1'b0; tune <= 1'b1; done <= 1'b1;
                        found <= have || better;
                        idx <= better ? idx : have ? best_idx : start_idx;
                    end else begin
                        idx <= idx + 1'b1; tune <= 1'b1; st <= S_SETTLE; t <= 0;
                    end
                end
            end
            endcase
        end
        if (rst) begin busy <= 1'b0; tune <= 1'b0; done <= 1'b0; found <= 1'b0; idx <= 0; end
    end
endmodule
`default_nettype wire
