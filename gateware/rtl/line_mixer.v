// Two-channel line mixer (system clock domain). Bit-exact against
// model/line_mixer_ref.py, where the rules are described in full.
//
// Paired lines: same line number, arrived within T_PAIR cycles of each other
// (the F bit is not compared). Port of mixer/line_mixer.py: take the channel
// whose line has less high-frequency energy (snow), switch only when the other
// is clearly better (hysteresis), average both when they are about equally
// clean. A bad line (sync codes, length, decoder unlocked) loses against a good one.
//
// Lone lines: a head whose partner has not arrived after T_PAIR cycles is
// resolved alone, oldest first. It is shown if it comes from the current
// channel, or to fill a gap (channels in step, line good, no line of the other
// channel arrived within T_PAIR of it). Seen from a lone line of the other
// channel, the current channel changes when it is sick while the other is well
// (last 8 lines), or when it has been silent for N_STEP such lines (channels
// were in step) or N_DEAD (they were not; longer than a blanking interval).
//
// Lines bad on both receivers: a line that would be shown although it has no
// good copy (a pair of bad lines, or a lone bad line) is not written, unless the
// line shown before it in the same output field had no good copy either. The
// field store replaces the missing line with the line above; in a run of such
// lines only the first is left out. All other state is updated as if the line
// had been shown; the trace says use 00.
//
// Output order: line numbers leave strictly increasing within a field; a line
// is admitted when it starts a new field of its channel or lies above the last
// line sent. The output F bit is latched from the first line of each field.
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
    parameter T_PAIR    = 1024,           // pairing window, cycles (15.8 us at 64.8 MHz)
    parameter N_STEP    = 8,              // lone lines after the last pair while still "in step"
    parameter N_DEAD    = 40,             // lone lines of the other channel before a silent one is given up
    parameter AGE_W     = 13
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
    input  wire [1:0]  fca, fcb,          // per-channel field counters of the head lines
    input  wire [AGE_W-1:0] age_a, age_b, // cycles since the head line was stored (saturating)
    input  wire        near_a, near_b,    // head line: a line of the other channel arrived within T_PAIR of it
    input  wire        psick_a, psick_b,  // head line: the other channel was sick when it arrived
    input  wire        swell_a, swell_b,  // head line: its own channel was well when it arrived

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
    localparam QW = $clog2(N_DEAD + 1), SW = $clog2(N_STEP + 1);
    reg [2:0] st;
    reg [1:0] act;                        // what S_IDLE chose: 11 pair, 01 lone A, 10 lone B
    reg [1:0] use_r, pop_r;
    reg       k_field;
    reg [9:0] k_line;
    reg [9:0] ri;                         // next word to read
    reg       v1;                         // read issued last cycle
    reg [8:0] i1;

    reg          step_valid;              // a pair has happened
    reg [SW-1:0] since_pair;              // lone resolutions since the last pair (saturates at N_STEP)
    reg [QW-1:0] quiet_a, quiet_b;        // lone lines of the other channel since this one's last line
    reg          qfast_a, qfast_b;        // the channels were in step when this one went quiet
    reg          o_valid;                 // output field state
    reg [9:0]    o_line;
    reg          o_fbit;
    reg [1:0]    o_fc_a, o_fc_b;
    reg          join_a, join_b;
    reg          bad_last;                // the last line shown in this output field had no good copy

    assign rd_idx = ri[8:0];
    assign pop_a = (st == S_POP) && pop_r[0];
    assign pop_b = (st == S_POP) && pop_r[1];

    // ---- S_IDLE: which head(s) to resolve
    wire has_a = cnt_a != 3'd0, has_b = cnt_b != 3'd0;
    wire [AGE_W-1:0] adiff = (age_a >= age_b) ? age_a - age_b : age_b - age_a;
    // (two saturated ages say nothing about the distance; that only happens when the output stalls)
    wire pairable = has_a && has_b && (la == lb) && (adiff < T_PAIR) && !(&age_a) && !(&age_b);
    wire old_a = has_a && (age_a >= T_PAIR);
    wire old_b = has_b && (age_b >= T_PAIR);

    // ---- paired: metric comparison, registered in S_IDLE (heads are stable while a line waits)
    wire        a_noisier = hfa > hfb;
    wire [19:0] absd = a_noisier ? hfa - hfb : hfb - hfa;
    wire [19:0] m    = a_noisier ? hfa : hfb;
    wire [27:0] absd_q8 = {absd, 8'd0};
    wire [27:0] blend_t = m * BLEND_Q8;
    wire [27:0] switch_t = m * SWITCH_Q8;
    reg blend, to_a, to_b;
    always @(posedge clk) begin
        blend <= (m == 20'd0) || (absd_q8 < blend_t);
        to_b  <= a_noisier && (absd_q8 > switch_t);    // A clearly noisier
        to_a  <= !a_noisier && (hfa != hfb) && (absd_q8 > switch_t);
    end
    // ---- S_DEC, paired
    reg [1:0] p_use;
    reg       p_cur;
    always @* begin
        p_cur = cur;
        if (bada && !badb)             begin p_use = 2'b10; p_cur = 1'b1; end
        else if (badb && !bada)        begin p_use = 2'b01; p_cur = 1'b0; end
        else if (bada && badb)         p_use = cur ? 2'b10 : 2'b01;
        else if (blend)                p_use = 2'b11;
        else if (cur == 1'b0 && to_b)  begin p_use = 2'b10; p_cur = 1'b1; end
        else if (cur == 1'b1 && to_a)  begin p_use = 2'b01; p_cur = 1'b0; end
        else                           p_use = cur ? 2'b10 : 2'b01;
    end

    // ---- S_DEC, lone line of channel x
    wire             in_step   = step_valid && (since_pair != N_STEP);
    wire             x         = act[1];
    wire             x_bad     = x ? badb : bada;
    wire             x_psick   = x ? psick_b : psick_a;
    wire             x_swell   = x ? swell_b : swell_a;
    wire             x_near    = x ? near_b : near_a;
    wire [QW-1:0]    quiet_cur = cur ? quiet_b : quiet_a;
    wire             qfast_cur = cur ? qfast_b : qfast_a;
    wire [QW-1:0]    q_inc     = (quiet_cur == N_DEAD) ? quiet_cur : quiet_cur + 1'b1;
    wire             fast      = (quiet_cur == 0) ? in_step : qfast_cur;
    wire             silent    = (q_inc == N_DEAD) || (fast && q_inc >= N_STEP);
    wire             s_cur     = ((x != cur) && (silent || (x_psick && x_swell))) ? x : cur;
    wire             s_owner   = (x == s_cur);
    // gap fill: the other channel (it is the current one when this matters) lost this line
    wire             gap_ok    = in_step && !x_bad && !x_near;

    // ---- S_DEC: may the line leave now? (c = the channel whose tags are judged)
    wire       pair    = (act == 2'b11);
    wire       c       = pair ? p_cur : x;
    wire       c_owner = pair ? 1'b1 : s_owner;
    wire       c_step  = pair ? 1'b1 : in_step;
    wire       c_f     = c ? fb : fa;
    wire [9:0] c_l     = c ? lb : la;
    // A pair whose current channel has no line in this output field (the other channel carried
    // it) is judged on the partner's field counter: the two lines carry the same number, and only
    // the partner knows whether it has moved on to its next field.
    wire       c_alt   = pair && !(c ? join_b : join_a) && (c ? join_a : join_b);
    wire [1:0] c_fc    = (c ^ c_alt) ? fcb : fca;
    wire       c_join  = (c ^ c_alt) ? join_b : join_a;
    wire [1:0] c_ofc   = (c ^ c_alt) ? o_fc_b : o_fc_a;
    reg adm_ok, adm_new;
    always @* begin
        if (!o_valid)                begin adm_ok = 1'b1;              adm_new = 1'b1; end
        else if (c_join) begin
            if (c_fc == c_ofc)       begin adm_ok = (c_l > o_line);    adm_new = 1'b0; end
            else                     begin adm_ok = c_owner || c_step; adm_new = c_owner || c_step; end   // next field of this channel
        end
        else if (c_owner && !c_step) begin adm_ok = 1'b1;              adm_new = 1'b1; end   // numbering owner changed out of step
        else                         begin adm_ok = (c_l > o_line);    adm_new = 1'b0; end
    end
    wire       show  = pair ? adm_ok : (adm_ok && (s_owner || gap_ok));
    wire       tag_f = adm_new ? c_f : o_fbit;
    // no good copy: both lines of a pair are bad, or a lone line is bad (the other receiver has none)
    wire       both_bad = pair ? (bada && badb) : x_bad;
    wire       omit  = show && both_bad && (adm_new || !bad_last);
    wire [1:0] use_n = (!show || omit) ? 2'b00 : pair ? p_use : x ? 2'b10 : 2'b01;

    function [7:0] avg(input [7:0] p, input [7:0] q);
        avg = ({1'b0, p} + {1'b0, q} + 9'd1) >> 1;
    endfunction
    wire [31:0] mixed = (use_r == 2'b01) ? rd_a : (use_r == 2'b10) ? rd_b :
                        {avg(rd_a[31:24], rd_b[31:24]), avg(rd_a[23:16], rd_b[23:16]),
                         avg(rd_a[15:8], rd_b[15:8]), avg(rd_a[7:0], rd_b[7:0])};

    always @(posedge clk) begin
        dec_valid <= 1'b0;
        o_we <= 1'b0;
        v1 <= 1'b0;
        case (st)
        S_IDLE: begin
            if (pairable)                                        begin act <= 2'b11; st <= S_DEC; end
            else if (old_a && (!old_b || age_a >= age_b))        begin act <= 2'b01; st <= S_DEC; end
            else if (old_b)                                      begin act <= 2'b10; st <= S_DEC; end
        end
        S_DEC: begin
            if (pair) begin
                cur <= p_cur;
                step_valid <= 1'b1; since_pair <= 0;
                quiet_a <= 0; quiet_b <= 0;
            end else begin
                cur <= s_cur;
                if (since_pair != N_STEP) since_pair <= since_pair + 1'b1;
                if (x) begin
                    quiet_b <= 0;
                    if (quiet_a == 0) qfast_a <= in_step;
                    if (quiet_a != N_DEAD) quiet_a <= quiet_a + 1'b1;
                end else begin
                    quiet_a <= 0;
                    if (quiet_b == 0) qfast_b <= in_step;
                    if (quiet_b != N_DEAD) quiet_b <= quiet_b + 1'b1;
                end
            end
            if (show) begin
                bad_last <= both_bad;
                o_valid <= 1'b1; o_line <= c_l;
                if (adm_new) begin o_fbit <= c_f; join_a <= 1'b0; join_b <= 1'b0; end
                if (pair || !x) begin join_a <= 1'b1; o_fc_a <= fca; end
                if (pair || x)  begin join_b <= 1'b1; o_fc_b <= fcb; end
            end
            use_r <= use_n; pop_r <= act; k_field <= tag_f; k_line <= c_l;
            dec_valid <= 1'b1; dec_use <= use_n; dec_pop <= act;
            dec_field <= show ? tag_f : c_f; dec_line <= c_l;
            ri <= 0;
            st <= (use_n == 2'b00) ? S_POP : S_EMIT;
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
        if (rst) begin
            st <= S_IDLE; cur <= 1'b0; dec_valid <= 1'b0; o_we <= 1'b0; v1 <= 1'b0;
            step_valid <= 1'b0; since_pair <= 0; quiet_a <= 0; quiet_b <= 0; qfast_a <= 1'b0; qfast_b <= 1'b0;
            o_valid <= 1'b0; join_a <= 1'b0; join_b <= 1'b0; bad_last <= 1'b0;
        end
    end
endmodule
`default_nettype wire
