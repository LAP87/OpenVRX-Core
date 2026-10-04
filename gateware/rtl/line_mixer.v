// Two-channel line mixer (system clock domain). Port of mixer/line_mixer.py:
// per line, take the channel whose line has less high-frequency energy (snow),
// switch only when the other channel is clearly better (hysteresis, also
// across fields), and average both when they are about equally clean. A line
// with broken sync codes or a wrong length loses against a good one.
//
// Lines are paired by (field, line number). Unpaired lines:
//   - both channels have lines of the same field but different numbers: the
//     older one is resolved alone; it is shown if it comes from the current
//     channel or the other channel is within NEAR lines (it skipped this one),
//     otherwise dropped (channels not in step, e.g. two different sources);
//   - one channel has 3 lines waiting: its oldest is resolved alone, shown
//     only if it is the current channel.
// If the current channel stops delivering lines and the other is alive, the
// current channel switches.
//
// Output: tagged words {field, line, idx, data} in the M2 frame buffer format,
// written into a FIFO whenever o_room says there is space for 4 more.
// Decision trace (for tests and statistics): dec_use = channels whose data
// was used (01 A, 10 B, 11 blend, 00 dropped), dec_pop = lines released.
`default_nettype none
module line_mixer #(
    parameter N_WORDS   = 360,
    parameter BLEND_Q8  = 38,             // |hfA-hfB| < 38/256 * max -> blend  (prototype 0.15)
    parameter SWITCH_Q8 = 64,             // switch when the other is > 64/256 better (prototype 0.25)
    parameter NEAR      = 8
) (
    input  wire        clk,
    input  wire        rst,

    output wire        pop_a, pop_b,
    output wire [8:0]  rd_idx,
    input  wire [31:0] rd_a, rd_b,
    input  wire [2:0]  cnt_a, cnt_b,
    input  wire        fa, fb,
    input  wire [9:0]  la, lb,
    input  wire [19:0] hfa, hfb,
    input  wire        bada, badb,
    input  wire        alive_a, alive_b,

    output reg         o_we,
    output reg  [51:0] o_data,
    input  wire        o_room,

    output reg         dec_valid,
    output reg  [1:0]  dec_use,
    output reg  [1:0]  dec_pop,
    output reg         dec_field,
    output reg  [9:0]  dec_line,
    output reg         cur                // 0 = A, 1 = B
);
    localparam S_IDLE = 3'd0, S_DEC = 3'd1, S_EMIT = 3'd2, S_POP = 3'd3, S_WAIT = 3'd4;
    reg [2:0] st;
    reg [1:0] use_r, pop_r;
    reg       k_field;
    reg [9:0] k_line;
    reg [9:0] ri;                         // next word to read
    reg       v1;                         // read issued last cycle
    reg [8:0] i1;

    assign rd_idx = ri[8:0];
    assign pop_a = (st == S_POP) && pop_r[0];
    assign pop_b = (st == S_POP) && pop_r[1];

    wire has_a = cnt_a != 3'd0, has_b = cnt_b != 3'd0;
    wire same_key   = has_a && has_b && fa == fb && la == lb;
    wire same_field = has_a && has_b && fa == fb && la != lb;
    wire a_older    = la < lb;
    wire [9:0] ldiff = a_older ? lb - la : la - lb;

    // metric decision (S_DEC; heads are stable while a line is waiting)
    wire [20:0] d    = {1'b0, hfa} - {1'b0, hfb};       // > 0: A noisier
    wire        a_noisier = hfa > hfb;
    wire [19:0] absd = a_noisier ? hfa - hfb : hfb - hfa;
    wire [19:0] m    = a_noisier ? hfa : hfb;
    wire [27:0] absd_q8 = {absd, 8'd0};
    wire [27:0] blend_t = m * BLEND_Q8;
    wire [27:0] switch_t = m * SWITCH_Q8;
    wire blend   = (m == 20'd0) || (absd_q8 < blend_t);
    wire to_b    = a_noisier && (absd_q8 > switch_t);   // A clearly noisier
    wire to_a    = !a_noisier && (hfa != hfb) && (absd_q8 > switch_t);

    function [7:0] avg(input [7:0] x, input [7:0] y);
        avg = ({1'b0, x} + {1'b0, y} + 9'd1) >> 1;
    endfunction
    wire [31:0] mixed = (use_r == 2'b01) ? rd_a : (use_r == 2'b10) ? rd_b :
                        {avg(rd_a[31:24], rd_b[31:24]), avg(rd_a[23:16], rd_b[23:16]),
                         avg(rd_a[15:8], rd_b[15:8]), avg(rd_a[7:0], rd_b[7:0])};

    task automatic decide(input [1:0] u, input [1:0] p, input f, input [9:0] l);
        begin
            use_r <= u; pop_r <= p; k_field <= f; k_line <= l;
            dec_valid <= 1'b1; dec_use <= u; dec_pop <= p; dec_field <= f; dec_line <= l;
            ri <= 0;
            st <= (u == 2'b00) ? S_POP : S_EMIT;
        end
    endtask

    always @(posedge clk) begin
        dec_valid <= 1'b0;
        o_we <= 1'b0;
        v1 <= 1'b0;
        case (st)
        S_IDLE: begin
            if (cur == 1'b0 && !alive_a && alive_b) cur <= 1'b1;
            else if (cur == 1'b1 && !alive_b && alive_a) cur <= 1'b0;
            else if (same_key) st <= S_DEC;
            else if (same_field) begin
                if (a_older) decide((cur == 1'b0 || ldiff < NEAR) ? 2'b01 : 2'b00, 2'b01, fa, la);
                else         decide((cur == 1'b1 || ldiff < NEAR) ? 2'b10 : 2'b00, 2'b10, fb, lb);
            end
            else if (cnt_a >= 3'd3) decide(cur == 1'b0 ? 2'b01 : 2'b00, 2'b01, fa, la);
            else if (cnt_b >= 3'd3) decide(cur == 1'b1 ? 2'b10 : 2'b00, 2'b10, fb, lb);
        end
        S_DEC: begin
            if (bada && !badb) begin cur <= 1'b1; decide(2'b10, 2'b11, fa, la); end
            else if (badb && !bada) begin cur <= 1'b0; decide(2'b01, 2'b11, fa, la); end
            else if (bada && badb) decide(cur ? 2'b10 : 2'b01, 2'b11, fa, la);
            else if (blend) decide(2'b11, 2'b11, fa, la);
            else if (cur == 1'b0 && to_b) begin cur <= 1'b1; decide(2'b10, 2'b11, fa, la); end
            else if (cur == 1'b1 && to_a) begin cur <= 1'b0; decide(2'b01, 2'b11, fa, la); end
            else decide(cur ? 2'b10 : 2'b01, 2'b11, fa, la);
        end
        S_EMIT: begin
            if (ri != N_WORDS && o_room) begin
                v1 <= 1'b1; i1 <= ri[8:0]; ri <= ri + 1'b1;
            end
            if (v1) begin
                o_we <= 1'b1;
                o_data <= {k_field, k_line, i1, mixed};
            end
            if (ri == N_WORDS && !v1) st <= S_POP;
        end
        S_POP: st <= S_WAIT;              // counts update this edge
        default: st <= S_IDLE;            // S_WAIT: heads now show the next lines
        endcase
        if (rst) begin st <= S_IDLE; cur <= 1'b0; dec_valid <= 1'b0; o_we <= 1'b0; v1 <= 1'b0; end
    end
endmodule
`default_nettype wire
