// M2 core with 1080p horizontal timing (vertical shortened to 40 lines) + BT.1120 output + SDRAM model.
`default_nettype none
module tb_m5c (
    input  wire       tvp_clk,
    input  wire [7:0] tvp_d,
    input  wire       sd_clk,
    input  wire       pix_clk,
    input  wire       rst,
    output wire [7:0] bt_y, bt_c,
    output wire       have_video, sdram_ready
);
    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    wire [7:0] r, g, b, yo, cbo, cro;
    wire [11:0] tx, ty;
    wire de, hs, vs, lines_arriving;
    m2_core #(.V_TOTAL(40), .V_ACTIVE(36), .V_FP(1), .V_SYNC(1), .SDRAM_FREQ(5_000_000),
              .H_ACTIVE(1920), .H_FP(88), .H_SYNC(44), .H_BP(148),
              .H_WIN0(240), .H_WIN(1440), .H_HALF(1)) core (
        .tvp_clk(tvp_clk), .tvp_d(tvp_d), .tvp_hs(1'b0), .tvp_vs(1'b0), .tvp_avid(1'b0),
        .sd_clk(sd_clk), .sd_clk_shift(~sd_clk), .pix_clk(pix_clk), .rst_async(rst), .ll_mode(1'b0),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hs), .vsync(vs), .yo(yo), .cbo(cbo), .cro(cro), .tx(tx), .ty(ty),
        .lines_arriving(lines_arriving), .have_video(have_video), .sdram_ready(sdram_ready));
    bt1120_tx #(.H_ACTIVE(1920), .H_TOTAL(2200), .V_ACTIVE(36), .V_TOTAL(40), .LAT(6)) bt (
        .clk(pix_clk), .x(tx), .y(ty), .yy(yo), .cb(cbo), .cr(cro), .out_y(bt_y), .out_c(bt_c));
    sdram_model #(.AW(21)) mem (.clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
                                .ba(ba), .a(a), .dqm(dqm), .dq(dq));
endmodule
`default_nettype wire
