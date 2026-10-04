// M2 core: TVP5150 BT.656 (or discrete syncs) -> SDRAM field triple buffer ->
// 4:3 colour window in the display timing. Everything except PLLs, DVI and
// board I/O, so the same module is used on hardware and in simulation.
//
// Clock domains: tvp_clk (27 MHz from the TVP), sd_clk and pix_clk (see
// fb_backend.v). The pixel words cross into the SDRAM domain in an async FIFO.
`default_nettype none
module m2_core #(
    parameter DISCRETE_SYNC = 0,          // 1: TVP in "8-bit 4:2:2 with discrete syncs" (uses tvp_hs/vs/avid)
    parameter V_TOTAL = 750, V_ACTIVE = 720,
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter V_FP = 5, V_SYNC = 5,
    parameter SDRAM_FREQ = 64_800_000,
    parameter H_WIN0 = 160, H_WIN = 960, H_HALF = 0    // picture window (see fb_display)
) (
    input  wire        tvp_clk,
    input  wire [7:0]  tvp_d,
    input  wire        tvp_hs, tvp_vs, tvp_avid,   // only used when DISCRETE_SYNC = 1
    input  wire        sd_clk,
    input  wire        sd_clk_shift,
    input  wire        pix_clk,
    input  wire        rst_async,         // active high, any domain
    input  wire        ll_mode,           // any domain: 1 = low latency, no SDRAM buffer (fb_backend.v)

    inout  wire [31:0] SDRAM_DQ,
    output wire [10:0] SDRAM_A,
    output wire [1:0]  SDRAM_BA,
    output wire        SDRAM_nCS, SDRAM_nWE, SDRAM_nRAS, SDRAM_nCAS, SDRAM_CLK, SDRAM_CKE,
    output wire [3:0]  SDRAM_DQM,

    output wire [7:0]  r, g, b,
    output wire        de, hsync, vsync,
    output wire [7:0]  yo, cbo, cro,      // YCbCr, same timing as r/g/b (for BT.1120)
    output wire [11:0] tx, ty,            // timing position; the video is valid 6 clocks later
    output wire        lines_arriving,    // tvp domain: BT.656 lines are being decoded
    output wire        have_video,        // pix domain: a field buffer is being shown
    output wire        sdram_ready        // sd domain: SDRAM initialised
);
    // ---- resets, synchronised per domain ----
    reg [2:0] rst_t, rst_s;
    always @(posedge tvp_clk or posedge rst_async) if (rst_async) rst_t <= 3'b111; else rst_t <= {rst_t[1:0], 1'b0};
    always @(posedge sd_clk  or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    wire trst = rst_t[2], srst = rst_s[2];

    // ---- TVP domain: receive, pack, push ----
    reg [7:0] d_in;
    reg hs_in, vs_in, av_in;
    always @(posedge tvp_clk) {d_in, hs_in, vs_in, av_in} <= {tvp_d, tvp_hs, tvp_vs, tvp_avid};
    wire px_valid, px_field, rec_valid;
    wire [7:0] px_data;
    wire [10:0] px_index;
    wire [9:0] px_line;
    generate if (DISCRETE_SYNC) begin : sync_rx
        wire line_done, hs_hi, vs_hi, av_hi, luma_odd;
        wire [10:0] line_bytes;
        tvp_sync_rx rx (.clk(tvp_clk), .rst(trst), .d(d_in), .hsync_in(hs_in), .vsync_in(vs_in), .avid_in(av_in),
                        .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line),
                        .px_field(px_field), .line_done(line_done), .line_bytes(line_bytes),
                        .hs_active_high(hs_hi), .vs_active_high(vs_hi), .avid_active_high(av_hi), .luma_odd(luma_odd));
        assign rec_valid = line_done;
    end else begin : bt656
        wire rec_field;
        wire [7:0] rec_xy_corrected, rec_xy_bad;
        wire [10:0] rec_active;
        wire [9:0] rec_line;
        wire [15:0] rec_length;
        wire [19:0] rec_hf;
        bt656_rx rx (.clk(tvp_clk), .rst(trst), .d(d_in),
                     .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_field(px_field), .px_line(px_line),
                     .rec_valid(rec_valid), .rec_field(rec_field), .rec_line(rec_line), .rec_length(rec_length),
                     .rec_active(rec_active), .rec_xy_corrected(rec_xy_corrected), .rec_xy_bad(rec_xy_bad), .rec_hf(rec_hf));
    end endgenerate
    wire w_valid, w_field;
    wire [31:0] w_data;
    wire [8:0] w_idx;
    wire [9:0] w_line;
    word_packer pack (.clk(tvp_clk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index),
                      .px_line(px_line), .px_field(px_field),
                      .w_valid(w_valid), .w_data(w_data), .w_idx(w_idx), .w_line(w_line), .w_field(w_field));
    reg [21:0] alive_cnt;
    reg alive;
    always @(posedge tvp_clk) begin
        if (rec_valid) begin alive_cnt <= 0; alive <= 1'b1; end
        else if (alive_cnt != {22{1'b1}}) alive_cnt <= alive_cnt + 1'b1;
        else alive <= 1'b0;
        if (trst) begin alive <= 1'b0; alive_cnt <= 0; end
    end
    assign lines_arriving = alive;

    wire        f_empty, f_full, f_pop;
    wire [51:0] f_data;
    wire [7:0]  f_wl, f_rl;
    async_fifo #(.W(52), .AW(7)) fifo (
        .wclk(tvp_clk), .wrst(trst), .wr_en(w_valid), .wr_data({w_field, w_line, w_idx, w_data}),
        .full(f_full), .wr_level(f_wl),
        .rclk(sd_clk), .rrst(srst), .rd_en(f_pop), .rd_data(f_data), .empty(f_empty), .rd_level(f_rl));

    fb_backend #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .H_ACTIVE(H_ACTIVE), .H_FP(H_FP), .H_SYNC(H_SYNC),
                 .H_BP(H_BP), .V_FP(V_FP), .V_SYNC(V_SYNC), .SDRAM_FREQ(SDRAM_FREQ),
                 .H_WIN0(H_WIN0), .H_WIN(H_WIN), .H_HALF(H_HALF)) backend (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(pix_clk), .rst_async(rst_async), .ll_mode(ll_mode),
        .f_empty(f_empty), .f_data(f_data), .f_pop(f_pop),
        .SDRAM_DQ(SDRAM_DQ), .SDRAM_A(SDRAM_A), .SDRAM_BA(SDRAM_BA), .SDRAM_nCS(SDRAM_nCS), .SDRAM_nWE(SDRAM_nWE),
        .SDRAM_nRAS(SDRAM_nRAS), .SDRAM_nCAS(SDRAM_nCAS), .SDRAM_CLK(SDRAM_CLK), .SDRAM_CKE(SDRAM_CKE), .SDRAM_DQM(SDRAM_DQM),
        .r(r), .g(g), .b(b), .de(de), .hsync(hsync), .vsync(vsync), .yo(yo), .cbo(cbo), .cro(cro), .tx(tx), .ty(ty),
        .have_video(have_video), .sdram_ready(sdram_ready));
endmodule
`default_nettype wire
