// Two-receiver front end: two TVP5150 BT.656 streams (each on its own clock)
// -> line_mixer -> one tagged word stream in the M2 frame buffer format,
// first-word fall-through on sys_clk (out_empty / out_data / out_pop).
`default_nettype none
module mixer2 #(
    parameter LEN_NTSC = 1716, LEN_PAL = 1728, LEN_TOL = 2,
    parameter TIMEOUT = 262144,             // alive_a/alive_b only (indicators)
    parameter BLEND_Q8 = 38, SWITCH_Q8 = 64,
    parameter T_PAIR = 1024, N_STEP = 8, N_DEAD = 40   // see line_mixer.v
) (
    input  wire        a_clk,
    input  wire [7:0]  a_d,
    input  wire        b_clk,
    input  wire [7:0]  b_d,
    input  wire        sys_clk,
    input  wire        rst_async,
    input  wire        ext_bad_a, ext_bad_b,  // any domain: decoder status says no lock
    input  wire        ext_weak_a, ext_weak_b,  // any domain: weak RSSI, counts against health only (mix_chan.v)

    output wire        out_empty,
    output wire [51:0] out_data,
    input  wire        out_pop,

    output wire        a_lines, b_lines,   // own clock domains: lines are being decoded
    output wire        alive_a, alive_b,   // sys domain: lines arrived within TIMEOUT cycles
    output wire        cur,                // sys domain: 0 = A, 1 = B
    output wire        overflow,           // sys domain, sticky
    output wire        dec_valid,
    output wire [1:0]  dec_use, dec_pop,
    output wire        dec_field,
    output wire [9:0]  dec_line,
    // snow meter (sys domain, see snow_stats.v): mean line HF energy per receiver over
    // 1024 lines and mixer usage over 1024 decisions; each toggle flips on new values
    output wire [19:0] snow_a, snow_b,
    output wire [10:0] use_a, use_b, use_mix,
    output wire        snow_toggle_a, snow_toggle_b, use_toggle,
    // noise meter (sys domain, see noise_stats.v): luma samples outside 16..235 per receiver,
    // summed over 1024 arriving lines; each toggle flips on a new value. Not used by the mixer.
    output wire [19:0] noise_a, noise_b,
    output wire        noise_toggle_a, noise_toggle_b
);
    reg [2:0] rst_a, rst_b, rst_s;
    always @(posedge a_clk   or posedge rst_async) if (rst_async) rst_a <= 3'b111; else rst_a <= {rst_a[1:0], 1'b0};
    always @(posedge b_clk   or posedge rst_async) if (rst_async) rst_b <= 3'b111; else rst_b <= {rst_b[1:0], 1'b0};
    always @(posedge sys_clk or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    wire arst = rst_a[2], brst = rst_b[2], srst = rst_s[2];

    reg [7:0] a_in, b_in;
    always @(posedge a_clk) a_in <= a_d;
    always @(posedge b_clk) b_in <= b_d;

    wire        ea_v, eb_v, a_pulse, b_pulse;
    wire [52:0] ea_d, eb_d;
    chan_capture cap_a (.clk(a_clk), .rst(arst), .d(a_in), .e_valid(ea_v), .e_data(ea_d), .line_pulse(a_pulse));
    chan_capture cap_b (.clk(b_clk), .rst(brst), .d(b_in), .e_valid(eb_v), .e_data(eb_d), .line_pulse(b_pulse));

    activity act_a (.clk(a_clk), .rst(arst), .pulse(a_pulse), .active(a_lines));
    activity act_b (.clk(b_clk), .rst(brst), .pulse(b_pulse), .active(b_lines));

    wire        fa_empty, fb_empty, fa_pop, fb_pop, fa_full, fb_full;
    wire [52:0] fa_data, fb_data;
    wire [7:0]  fa_wl, fa_rl, fb_wl, fb_rl;
    async_fifo #(.W(53), .AW(7)) fifo_a (
        .wclk(a_clk), .wrst(arst), .wr_en(ea_v), .wr_data(ea_d), .full(fa_full), .wr_level(fa_wl),
        .rclk(sys_clk), .rrst(srst), .rd_en(fa_pop), .rd_data(fa_data), .empty(fa_empty), .rd_level(fa_rl));
    async_fifo #(.W(53), .AW(7)) fifo_b (
        .wclk(b_clk), .wrst(brst), .wr_en(eb_v), .wr_data(eb_d), .full(fb_full), .wr_level(fb_wl),
        .rclk(sys_clk), .rrst(srst), .rd_en(fb_pop), .rd_data(fb_data), .empty(fb_empty), .rd_level(fb_rl));

    localparam AGE_W = $clog2(8 * T_PAIR);
    wire        pop_a, pop_b, ha_f, hb_f, ha_bad, hb_bad, ha_weak, hb_weak, ov_a, ov_b;
    wire        sick_a, sick_b, arr_a, arr_b, dead_a, dead_b;
    wire        ha_psick, hb_psick, ha_swell, hb_swell, ha_near, hb_near;
    wire        ha_pdead, hb_pdead, ha_sok, hb_sok;
    wire [8:0]  rd_idx;
    wire [31:0] rd_a, rd_b;
    wire [2:0]  cnt_a, cnt_b;
    wire [9:0]  ha_l, hb_l;
    wire [19:0] ha_hf, hb_hf;
    wire [1:0]  ha_fc, hb_fc;
    wire [AGE_W-1:0] ha_age, hb_age, last_a, last_b;
    mix_chan #(.LEN_NTSC(LEN_NTSC), .LEN_PAL(LEN_PAL), .LEN_TOL(LEN_TOL), .TIMEOUT(TIMEOUT), .T_PAIR(T_PAIR), .AGE_W(AGE_W)) ch_a (
        .clk(sys_clk), .rst(srst), .ext_bad(ext_bad_a), .ext_weak(ext_weak_a), .in_empty(fa_empty), .in_data(fa_data), .in_pop(fa_pop),
        .pop_line(pop_a), .rd_idx(rd_idx), .rd_data(rd_a),
        .peer_sick(sick_b), .peer_dead(dead_b), .peer_arrived(arr_b), .peer_last_age(last_b),
        .sick(sick_a), .dead(dead_a), .arrived(arr_a), .last_age(last_a), .count(cnt_a),
        .head_field(ha_f), .head_line(ha_l), .head_hf(ha_hf), .head_bad(ha_bad), .head_weak(ha_weak), .head_fc(ha_fc), .head_age(ha_age),
        .head_peer_sick(ha_psick), .head_self_well(ha_swell), .head_peer_dead(ha_pdead), .head_self_ok(ha_sok),
        .head_near(ha_near), .alive(alive_a), .overflow(ov_a));
    mix_chan #(.LEN_NTSC(LEN_NTSC), .LEN_PAL(LEN_PAL), .LEN_TOL(LEN_TOL), .TIMEOUT(TIMEOUT), .T_PAIR(T_PAIR), .AGE_W(AGE_W)) ch_b (
        .clk(sys_clk), .rst(srst), .ext_bad(ext_bad_b), .ext_weak(ext_weak_b), .in_empty(fb_empty), .in_data(fb_data), .in_pop(fb_pop),
        .pop_line(pop_b), .rd_idx(rd_idx), .rd_data(rd_b),
        .peer_sick(sick_a), .peer_dead(dead_a), .peer_arrived(arr_a), .peer_last_age(last_a),
        .sick(sick_b), .dead(dead_b), .arrived(arr_b), .last_age(last_b), .count(cnt_b),
        .head_field(hb_f), .head_line(hb_l), .head_hf(hb_hf), .head_bad(hb_bad), .head_weak(hb_weak), .head_fc(hb_fc), .head_age(hb_age),
        .head_peer_sick(hb_psick), .head_self_well(hb_swell), .head_peer_dead(hb_pdead), .head_self_ok(hb_sok),
        .head_near(hb_near), .alive(alive_b), .overflow(ov_b));
    assign overflow = ov_a | ov_b;

    wire        o_we;
    wire [51:0] o_data;
    wire [5:0]  o_wl, o_rl;
    wire        o_full;
    line_mixer #(.BLEND_Q8(BLEND_Q8), .SWITCH_Q8(SWITCH_Q8), .T_PAIR(T_PAIR), .N_STEP(N_STEP), .N_DEAD(N_DEAD), .AGE_W(AGE_W)) mix (
        .clk(sys_clk), .rst(srst), .pop_a(pop_a), .pop_b(pop_b), .rd_idx(rd_idx), .rd_a(rd_a), .rd_b(rd_b),
        .cnt_a(cnt_a), .cnt_b(cnt_b), .fa(ha_f), .fb(hb_f), .la(ha_l), .lb(hb_l), .hfa(ha_hf), .hfb(hb_hf),
        .bada(ha_bad), .badb(hb_bad), .weaka(ha_weak), .weakb(hb_weak), .fca(ha_fc), .fcb(hb_fc), .age_a(ha_age), .age_b(hb_age),
        .near_a(ha_near), .near_b(hb_near), .psick_a(ha_psick), .psick_b(hb_psick), .swell_a(ha_swell), .swell_b(hb_swell),
        .pdead_a(ha_pdead), .pdead_b(hb_pdead), .sok_a(ha_sok), .sok_b(hb_sok),
        .o_we(o_we), .o_data(o_data), .o_room(o_wl < 6'd28),
        .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop), .dec_field(dec_field), .dec_line(dec_line),
        .cur(cur));

    snow_stats #(.LOG_N(10)) stats (
        .clk(sys_clk), .rst(srst), .line_a(pop_a), .hf_a(ha_hf), .line_b(pop_b), .hf_b(hb_hf),
        .dec_valid(dec_valid), .dec_use(dec_use),
        .mean_a(snow_a), .mean_b(snow_b), .use_a(use_a), .use_b(use_b), .use_mix(use_mix),
        .toggle_a(snow_toggle_a), .toggle_b(snow_toggle_b), .toggle_use(use_toggle));

    // taps the FIFO outputs mix_chan reads; per-line outputs are for tests only
    noise_stats #(.LOG_N(10)) noise_a_st (
        .clk(sys_clk), .rst(srst), .valid(!fa_empty), .data(fa_data),
        .line_valid(), .line_field(), .line_no(), .line_count(), .sum(noise_a), .toggle(noise_toggle_a));
    noise_stats #(.LOG_N(10)) noise_b_st (
        .clk(sys_clk), .rst(srst), .valid(!fb_empty), .data(fb_data),
        .line_valid(), .line_field(), .line_no(), .line_count(), .sum(noise_b), .toggle(noise_toggle_b));

    // same-clock FIFO (async_fifo on one clock is fine, just a few cycles of latency)
    async_fifo #(.W(52), .AW(5)) out_fifo (
        .wclk(sys_clk), .wrst(srst), .wr_en(o_we), .wr_data(o_data), .full(o_full), .wr_level(o_wl),
        .rclk(sys_clk), .rrst(srst), .rd_en(out_pop), .rd_data(out_data), .empty(out_empty), .rd_level(o_rl));
endmodule

// "Something happened recently" for LEDs: stays high ~0.15 s after each pulse at 27 MHz.
module activity #(parameter BITS = 22) (
    input  wire clk, rst, pulse,
    output reg  active
);
    reg [BITS-1:0] cnt;
    always @(posedge clk) begin
        if (pulse) begin cnt <= 0; active <= 1'b1; end
        else if (cnt != {BITS{1'b1}}) cnt <= cnt + 1'b1;
        else active <= 1'b0;
        if (rst) begin cnt <= 0; active <= 1'b0; end
    end
endmodule
`default_nettype wire
