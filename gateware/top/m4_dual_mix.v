// M4: two of our own TVP5150AM1 decoders (two receivers on the same channel)
// -> line-by-line mixer -> SDRAM field triple buffer -> 720p60 on the onboard
// HDMI. The decoders are brought up over I2C by the FPGA (tvp_ctrl).
//
// LEDs (active low): 0 heartbeat, 1 lines from A, 2 lines from B, 3 mixer
// currently prefers B, 4 a field is being shown, 5 both decoders answered
// on I2C and report horizontal + vertical lock.
`default_nettype none
module m4_dual_mix #(
    parameter LOW_LATENCY = 0             // 1: no SDRAM field buffer, output locked to the input (fb_backend.v)
) (
    input  wire        clk,
    input  wire        rst_i,
    input  wire        tvpa_sclk,
    input  wire [7:0]  tvpa_d,
    input  wire        tvpb_sclk,
    input  wire [7:0]  tvpb_d,
    inout  wire        i2c_scl,           // shared
    inout  wire        i2c_sda_a,         // one SDA per decoder: identical modules share an address
    inout  wire        i2c_sda_b,
    output wire        tvp_resetb,
    output wire        tmds_clk_p, tmds_clk_n,
    output wire [2:0]  tmds_d_p, tmds_d_n,
    output wire [5:0]  led,
    output wire        O_sdram_clk, O_sdram_cke, O_sdram_cs_n, O_sdram_cas_n, O_sdram_ras_n, O_sdram_wen_n,
    output wire [3:0]  O_sdram_dqm,
    output wire [10:0] O_sdram_addr,
    output wire [1:0]  O_sdram_ba,
    inout  wire [31:0] IO_sdram_dq
);
    wire clk_serial, clk_pixel, pix_locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(pix_locked));
    wire sd_clk, sd_clk_shift, sd_locked;
    clocks_sdram sdclk (.clk_27(clk), .clk(sd_clk), .clk_shift(sd_clk_shift), .locked(sd_locked));
    wire rst = rst_i | ~pix_locked | ~sd_locked;

    // ---- decoder bring-up (board clock) ----
    reg [2:0] rst_c;
    always @(posedge clk) rst_c <= {rst_c[1:0], rst_i};
    wire scl_low, init_done;
    wire [1:0] sda_low;
    wire [1:0] dev_err, st_valid;
    wire [15:0] st0, st1;
    tvp_ctrl #(.SPLIT_SDA(1), .DEV0(7'h5C), .DEV1(7'h5C)) ctrl (.clk(clk), .rst(rst_c[2]), .tvp_resetb(tvp_resetb),
                   .scl_low(scl_low), .sda_low(sda_low), .scl_in(i2c_scl), .sda_in({i2c_sda_b, i2c_sda_a}),
                   .init_done(init_done), .dev_err(dev_err), .status0(st0), .status1(st1), .status_valid(st_valid),
                   .hold(1'b0), .active());
    assign i2c_scl = scl_low ? 1'b0 : 1'bz;
    assign i2c_sda_a = sda_low[0] ? 1'b0 : 1'bz;
    assign i2c_sda_b = sda_low[1] ? 1'b0 : 1'bz;
    wire locked_ok = init_done && dev_err == 2'b00 && st_valid == 2'b11 &&
                     st0[1] && st0[2] && st1[1] && st1[2];

    // ---- mixer (SDRAM clock domain) ----
    wire        m_empty, m_pop, a_lines, b_lines, alive_a, alive_b, cur, overflow;
    wire [51:0] m_data;
    wire        dec_valid, dec_field;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    // a decoder that answers but reports no H or V lock loses against one that is locked
    wire nolock_a = st_valid[0] && !(st0[1] && st0[2]);
    wire nolock_b = st_valid[1] && !(st1[1] && st1[2]);
    mixer2 mix (.a_clk(tvpa_sclk), .a_d(tvpa_d), .b_clk(tvpb_sclk), .b_d(tvpb_d), .sys_clk(sd_clk), .rst_async(rst),
                .ext_bad_a(nolock_a), .ext_bad_b(nolock_b),
                .out_empty(m_empty), .out_data(m_data), .out_pop(m_pop),
                .a_lines(a_lines), .b_lines(b_lines), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
                .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
                .dec_field(dec_field), .dec_line(dec_line));

    wire [7:0] r, g, b;
    wire de, hs, vs, have_video, sdram_ready;
    fb_backend backend (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(clk_pixel), .rst_async(rst), .ll_mode(LOW_LATENCY[0]),
        .f_empty(m_empty), .f_data(m_data), .f_pop(m_pop),
        .SDRAM_DQ(IO_sdram_dq), .SDRAM_A(O_sdram_addr), .SDRAM_BA(O_sdram_ba), .SDRAM_nCS(O_sdram_cs_n),
        .SDRAM_nWE(O_sdram_wen_n), .SDRAM_nRAS(O_sdram_ras_n), .SDRAM_nCAS(O_sdram_cas_n),
        .SDRAM_CLK(O_sdram_clk), .SDRAM_CKE(O_sdram_cke), .SDRAM_DQM(O_sdram_dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hs), .vsync(vs),
        .have_video(have_video), .sdram_ready(sdram_ready));

    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], rst};
    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst_sr[3]),
                      .de(de), .hsync(hs), .vsync(vs), .r(r), .g(g), .b(b),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    reg [24:0] sec;
    always @(posedge clk) sec <= sec + 1'b1;
    assign led = ~{locked_ok, have_video, cur, b_lines, a_lines, sec[24]};
endmodule
`default_nettype wire
