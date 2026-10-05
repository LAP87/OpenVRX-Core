// Benches for test_sdram.py:
//   tb_sdram        sdram_burst + the SDRAM model, SDRAM clock = controller clock shifted 225 degrees
//   tb_sdram_model  the model alone with its pins driven by the test (negative controls of its checks)
`timescale 1ns/1ps
`default_nettype none
module tb_sdram #(
    parameter T_CLK_DLY_PS = 3000,       // board delays: the model's assumed defaults
    parameter T_DQ_DLY_PS  = 3000,
    parameter T_OUT_DLY_PS = 3000,
    parameter CLK_PS       = 15432,      // the period of the clock that test_sdram.py drives
    parameter PHASE16      = 10,         // SDRAM clock phase in sixteenths of a period, as PSDA_SEL
    parameter RD_SAMPLE    = 5
) (
    input  wire        clk,
    input  wire        resetn,
    input  wire        req_valid,
    input  wire        req_write,
    input  wire [20:0] req_addr,
    output wire        req_ready,
    input  wire [31:0] wdata,
    output wire        wdata_take,
    output wire [31:0] rdata,
    output wire        rdata_valid,
    output wire        init_done
);
    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    reg  clk_shift = 1'b0;               // what the PLL's CLKOUTP gives: the same clock, later
    always @(clk) clk_shift <= #(PHASE16 * CLK_PS / 16000.0) clk;
    sdram_burst #(.RD_SAMPLE(RD_SAMPLE)) ctrl (  // FREQ as on the board: the real 200 us power-up wait
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe),
        .SDRAM_nRAS(nras), .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .clk(clk), .clk_sdram(clk_shift), .resetn(resetn),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid), .init_done(init_done));
    // REF_WINDOW 8: the refresh check looks at 8 refreshes (125 us) instead of 4096 (64 ms)
    sdram_model #(.AW(21), .T_CLK_DLY_PS(T_CLK_DLY_PS), .T_DQ_DLY_PS(T_DQ_DLY_PS), .T_OUT_DLY_PS(T_OUT_DLY_PS),
                  .REF_WINDOW(8)) mem (
        .clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
        .ba(ba), .a(a), .dqm(dqm), .dq(dq));
endmodule

// The model alone, without board delays, so that the pins are the SDRAM's own pins.
module tb_sdram_model #(
    parameter STRICT = 0                 // 1: the first protocol error ends the simulation
) (
    input  wire        clk,
    input  wire        cke, ncs, nras, ncas, nwe,
    input  wire [1:0]  ba,
    input  wire [10:0] a,
    input  wire [3:0]  dqm,
    input  wire [31:0] dq_out,           // the test's drive of DQ
    input  wire        dq_oe,
    output wire [31:0] dq
);
    assign dq = dq_oe ? dq_out : 32'bz;
    // REF_WINDOW 4: no 4 consecutive refreshes may take longer than 62.5 us
    sdram_model #(.AW(12), .T_CLK_DLY_PS(0), .T_DQ_DLY_PS(0), .T_OUT_DLY_PS(0), .REF_WINDOW(4),
                  .STRICT(STRICT)) mem (
        .clk(clk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
        .ba(ba), .a(a), .dqm(dqm), .dq(dq));
endmodule
`default_nettype wire
