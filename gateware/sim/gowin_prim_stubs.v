// Stand-ins for the Gowin primitives used below the tops (rPLL, CLKDIV, OSER10,
// TLVDS_OBUF), so that a whole top can be simulated (sim/tb_top_pins.v).
// For wiring tests only, not timing or serialiser models:
//   rPLL        CLKOUT = CLKIN * (FBDIV_SEL + 1) / (IDIV_SEL + 1), from the measured CLKIN
//               period; CLKOUTP the same, PSDA_SEL / 16 of a period later; LOCK after 8
//               output cycles. CLKOUTD and CLKOUTD3 stay low.
//               +pll_stop_ns=<t> freezes the outputs from that time on while LOCK stays
//               high: the rest of a run then costs only the board-clock logic.
//   CLKDIV      divides by DIV_MODE (2, 4, 5 or 8)
//   OSER10      Q = D0
//   TLVDS_OBUF  O = I, OB = ~I
`timescale 1ns/1ps
module rPLL #(
    parameter FCLKIN = "100.0",
    parameter DYN_IDIV_SEL = "false", parameter IDIV_SEL = 0,
    parameter DYN_FBDIV_SEL = "false", parameter FBDIV_SEL = 0,
    parameter DYN_ODIV_SEL = "false", parameter ODIV_SEL = 8,
    parameter PSDA_SEL = "0000", parameter DYN_DA_EN = "false", parameter DUTYDA_SEL = "1000",
    parameter CLKOUT_FT_DIR = 1'b1, parameter CLKOUTP_FT_DIR = 1'b1,
    parameter CLKOUT_DLY_STEP = 0, parameter CLKOUTP_DLY_STEP = 0,
    parameter CLKFB_SEL = "internal",
    parameter CLKOUT_BYPASS = "false", parameter CLKOUTP_BYPASS = "false", parameter CLKOUTD_BYPASS = "false",
    parameter DYN_SDIV_SEL = 2, parameter CLKOUTD_SRC = "CLKOUT", parameter CLKOUTD3_SRC = "CLKOUT",
    parameter DEVICE = "GW2A-18"
) (
    output reg        CLKOUT,
    output reg        LOCK,
    output reg        CLKOUTP,
    output wire       CLKOUTD, CLKOUTD3,
    input  wire       RESET, RESET_P, CLKIN, CLKFB,
    input  wire [5:0] FBDSEL, IDSEL, ODSEL,
    input  wire [3:0] PSDA, DUTYDA, FDLY
);
    assign CLKOUTD = 1'b0;
    assign CLKOUTD3 = 1'b0;

    // PSDA_SEL is four characters '0'/'1', most significant first
    wire [31:0] ps = PSDA_SEL;
    wire [3:0]  ps16 = {ps[24], ps[16], ps[8], ps[0]};

    real    t_last, t_out;
    integer n_in, n_out;
    time    stop_ns;
    reg     run;
    initial begin
        CLKOUT = 1'b0; CLKOUTP = 1'b0; LOCK = 1'b0; run = 1'b0; n_in = 0; n_out = 0; t_last = 0.0;
        if (!$value$plusargs("pll_stop_ns=%d", stop_ns)) stop_ns = 0;
    end
    always @(posedge CLKIN) begin
        if (n_in == 1) begin
            t_out = ($realtime - t_last) * (IDIV_SEL + 1) / (FBDIV_SEL + 1);
            run = 1'b1;
        end
        t_last = $realtime;
        n_in = n_in + 1;
    end
    always begin
        wait (run);
        #(t_out / 2.0);
        if (stop_ns != 0 && $time >= stop_ns) begin
            CLKOUT = 1'b0;
            wait (0);                      // frozen for the rest of the run
        end
        CLKOUT = ~CLKOUT;
        if (CLKOUT) begin
            n_out = n_out + 1;
            if (n_out == 8) LOCK = 1'b1;
        end
    end
    always @(CLKOUT) CLKOUTP <= #(t_out * ps16 / 16.0) CLKOUT;
endmodule

module CLKDIV #(
    parameter DIV_MODE = "2",
    parameter GSREN = "false"
) (
    output reg  CLKOUT,
    input  wire HCLKIN, RESETN, CALIB
);
    localparam integer N = (DIV_MODE == "2") ? 2 : (DIV_MODE == "4") ? 4 : (DIV_MODE == "5") ? 5 :
                           (DIV_MODE == "8") ? 8 : 0;
    integer n;
    initial begin
        CLKOUT = 1'b0; n = 0;
        if (N == 0) begin $display("CLKDIV stub: DIV_MODE %0s is not modelled", DIV_MODE); $finish; end
    end
    always @(posedge HCLKIN) begin
        if (RESETN !== 1'b1) begin n = 0; CLKOUT = 1'b0; end
        else begin
            CLKOUT = (n < (N + 1) / 2);
            n = (n == N - 1) ? 0 : n + 1;
        end
    end
endmodule

module OSER10 #(
    parameter GSREN = "false",
    parameter LSREN = "true"
) (
    output wire Q,
    input  wire D0, D1, D2, D3, D4, D5, D6, D7, D8, D9,
    input  wire PCLK, FCLK, RESET
);
    assign Q = D0;
endmodule

module TLVDS_OBUF (
    input  wire I,
    output wire O, OB
);
    assign O = I;
    assign OB = ~I;
endmodule
