// memtest_core + the timing-aware SDRAM model. Board delays and SDRAM clock phase are parameters that
// test_memtest.py sets per build.
`timescale 1ns/1ps
`default_nettype none
module tb_memtest #(
    parameter T_CLK_DLY_PS = 3000,       // board delays: the model's assumed defaults
    parameter T_DQ_DLY_PS  = 3000,
    parameter T_OUT_DLY_PS = 3000,
    parameter CLK_PS       = 15432,      // the period of the clock that the test drives
    parameter PHASE16      = 10,         // SDRAM clock phase in sixteenths of a period, as SDRAM_PHASE in a build
    parameter AW           = 9,          // 2^AW words are tested
    parameter BAUD         = 8_100_000   // 8 clocks per bit: a line takes 6 560 clocks instead of 460 000
) (
    input  wire clk,
    input  wire rst,
    input  wire inject,
    output wire uart_txd,
    output wire init_done, line_toggle, fail_default
);
    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    reg  clk_shift = 1'b0;               // what the PLL's CLKOUTP gives: the same clock, later
    always @(clk) clk_shift <= #(PHASE16 * CLK_PS / 16000.0) clk;
    memtest_core #(.AW(AW), .BAUD(BAUD)) core (  // FREQ as on the board: the real 200 us power-up wait
        .clk(clk), .clk_sdram(clk_shift), .rst(rst), .inject(inject),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .uart_txd(uart_txd), .init_done(init_done), .line_toggle(line_toggle), .fail_default(fail_default));
    // RTL takes X and Z for a match when it compares, which would hide errors in this bench. So the model
    // gives random bits while its outputs change (UNDEF_RANDOM), a released bus reads as ones (pull-ups;
    // on the board it keeps its last value for a while), and x_samples counts any X that still gets in.
    pullup pu [31:0] (dq);
    sdram_model #(.AW(21), .T_CLK_DLY_PS(T_CLK_DLY_PS), .T_DQ_DLY_PS(T_DQ_DLY_PS), .T_OUT_DLY_PS(T_OUT_DLY_PS),
                  .REF_WINDOW(8), .UNDEF_RANDOM(1)) mem (
        .clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
        .ba(ba), .a(a), .dqm(dqm), .dq(dq));
    integer x_samples = 0;
    always @(posedge clk) if (core.rdata_valid && ^core.rdata === 1'bx) x_samples = x_samples + 1;
endmodule
`default_nettype wire
