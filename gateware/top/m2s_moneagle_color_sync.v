// M2s: like m2_moneagle_color, for a TVP5150AM1 in discrete-sync mode (HSYNC/VSYNC/AVID pins).
// M2: Moneagle (TVP5150AM1, BT.656 tap) -> SDRAM field triple buffer -> full
// resolution colour in a 4:3 window at 720p60 on the onboard HDMI. No tearing:
// the display always shows a complete field (bob), the writer never touches it.
//
// LEDs (active low): 0 heartbeat, 1 BT.656 lines arriving, 2 SDRAM initialised,
// 3 a field is being shown, 4 SDRAM PLL locked, 5 pixel PLL locked.
`default_nettype none
module m2s_moneagle_color_sync (
    input  wire        clk,
    input  wire        rst_i,
    input  wire        tvp_sclk,
    input  wire [7:0]  tvp_d,
    input  wire        tvp_hsync, tvp_vsync, tvp_avid,
    output wire        tmds_clk_p, tmds_clk_n,
    output wire [2:0]  tmds_d_p, tmds_d_n,
    output wire [5:0]  led,
    // embedded SDRAM (names fixed by the constraints)
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

    wire [7:0] r, g, b;
    wire de, hs, vs, lines_arriving, have_video, sdram_ready;
    m2_core #(.DISCRETE_SYNC(1)) core (
        .tvp_clk(tvp_sclk), .tvp_d(tvp_d), .tvp_hs(tvp_hsync), .tvp_vs(tvp_vsync), .tvp_avid(tvp_avid), .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(clk_pixel),
        .rst_async(rst), .ll_mode(1'b0),
        .SDRAM_DQ(IO_sdram_dq), .SDRAM_A(O_sdram_addr), .SDRAM_BA(O_sdram_ba), .SDRAM_nCS(O_sdram_cs_n),
        .SDRAM_nWE(O_sdram_wen_n), .SDRAM_nRAS(O_sdram_ras_n), .SDRAM_nCAS(O_sdram_cas_n),
        .SDRAM_CLK(O_sdram_clk), .SDRAM_CKE(O_sdram_cke), .SDRAM_DQM(O_sdram_dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hs), .vsync(vs),
        .lines_arriving(lines_arriving), .have_video(have_video), .sdram_ready(sdram_ready));

    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], rst};
    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst_sr[3]),
                      .de(de), .hsync(hs), .vsync(vs), .r(r), .g(g), .b(b),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    reg [24:0] sec;
    always @(posedge clk) sec <= sec + 1'b1;
    assign led = ~{pix_locked, sd_locked, have_video, sdram_ready, lines_arriving, sec[24]};
endmodule
`default_nettype wire
