// 27 MHz -> 64.8 MHz SDRAM controller clock + 180-degree shifted copy for the
// SDRAM chip (nand2mario's controller expects the inverted phase).
// rPLL: 27 * (FBDIV_SEL+1) / (IDIV_SEL+1) = 27 * 12 / 5 = 64.8 MHz,
// VCO = 64.8 * ODIV_SEL(8) = 518.4 MHz; CLKOUTP phase PSDA_SEL 1000 = 8/16 turn.
`default_nettype none
module clocks_sdram (
    input  wire clk_27,
    output wire clk,          // 64.8 MHz
    output wire clk_shift,    // 64.8 MHz, 180 degrees
    output wire locked
);
    wire gnd = 1'b0;
    wire unused_d, unused_d3;
    rPLL #(
        .FCLKIN("27"),
        .DYN_IDIV_SEL("false"), .IDIV_SEL(4),
        .DYN_FBDIV_SEL("false"), .FBDIV_SEL(11),
        .DYN_ODIV_SEL("false"), .ODIV_SEL(8),
        .PSDA_SEL("1000"), .DYN_DA_EN("false"), .DUTYDA_SEL("1000"),
        .CLKOUT_FT_DIR(1'b1), .CLKOUTP_FT_DIR(1'b1),
        .CLKOUT_DLY_STEP(0), .CLKOUTP_DLY_STEP(0),
        .CLKFB_SEL("internal"),
        .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"), .CLKOUTD_BYPASS("false"),
        .DYN_SDIV_SEL(2), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"),
        .DEVICE("GW2AR-18C")
    ) pll (
        .CLKOUT(clk), .LOCK(locked), .CLKOUTP(clk_shift), .CLKOUTD(unused_d), .CLKOUTD3(unused_d3),
        .RESET(gnd), .RESET_P(gnd), .CLKIN(clk_27), .CLKFB(gnd),
        .FBDSEL({6{gnd}}), .IDSEL({6{gnd}}), .ODSEL({6{gnd}}),
        .PSDA({4{gnd}}), .DUTYDA({4{gnd}}), .FDLY({4{gnd}})
    );
endmodule
`default_nettype wire
