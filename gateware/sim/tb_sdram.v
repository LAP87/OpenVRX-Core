// sdram_burst + behavioural SDRAM model, SDRAM clock = inverted controller clock.
`default_nettype none
module tb_sdram (
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
    sdram_burst #(.FREQ(5_000_000)) ctrl (       // short 200 us wait in simulation
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe),
        .SDRAM_nRAS(nras), .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .clk(clk), .clk_sdram(~clk), .resetn(resetn),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid), .init_done(init_done));
    sdram_model #(.AW(21)) mem (.clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
                                .ba(ba), .a(a), .dqm(dqm), .dq(dq));
endmodule
`default_nettype wire
