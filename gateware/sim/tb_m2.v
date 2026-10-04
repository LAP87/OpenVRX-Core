// M2 core + behavioural SDRAM, short display frame (40 lines, 36 active) for speed.
`default_nettype none
module tb_m2 (
    input  wire       tvp_clk,
    input  wire [7:0] tvp_d,
    input  wire       sd_clk,
    input  wire       pix_clk,
    input  wire       rst,
    input  wire       ll_mode,
    output wire [7:0] r, g, b,
    output wire       de, hsync, vsync,
    output wire       lines_arriving, have_video, sdram_ready
);
    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    m2_core #(.V_TOTAL(40), .V_ACTIVE(36), .V_FP(1), .V_SYNC(1), .SDRAM_FREQ(5_000_000)) core (
        .tvp_clk(tvp_clk), .tvp_d(tvp_d), .tvp_hs(1'b0), .tvp_vs(1'b0), .tvp_avid(1'b0), .sd_clk(sd_clk), .sd_clk_shift(~sd_clk), .pix_clk(pix_clk),
        .rst_async(rst), .ll_mode(ll_mode),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hsync), .vsync(vsync),
        .lines_arriving(lines_arriving), .have_video(have_video), .sdram_ready(sdram_ready));
    sdram_model #(.AW(21)) mem (.clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
                                .ba(ba), .a(a), .dqm(dqm), .dq(dq));
endmodule
`default_nettype wire
