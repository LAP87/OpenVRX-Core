// 27 MHz crystal -> 148.5 MHz pixel clock for 1080p60 (no serialiser: the
// LT8618SX makes TMDS). rPLL: fout = 27 * (FBDIV_SEL+1) / (IDIV_SEL+1)
// = 27 * 11 / 2 = 148.5 MHz, VCO = fout * ODIV_SEL = 594 MHz, PFD = 13.5 MHz.
`default_nettype none
module clocks_1080p (
    input  wire clk_27,
    output wire clk_pixel,    // 148.5 MHz
    output wire locked
);
    wire gnd = 1'b0;
    wire unused_p, unused_d, unused_d3;
    rPLL #(
        .FCLKIN("27"),
        .DYN_IDIV_SEL("false"), .IDIV_SEL(1),
        .DYN_FBDIV_SEL("false"), .FBDIV_SEL(10),
        .DYN_ODIV_SEL("false"), .ODIV_SEL(4),
        .PSDA_SEL("0000"), .DYN_DA_EN("true"), .DUTYDA_SEL("1000"),
        .CLKOUT_FT_DIR(1'b1), .CLKOUTP_FT_DIR(1'b1),
        .CLKOUT_DLY_STEP(0), .CLKOUTP_DLY_STEP(0),
        .CLKFB_SEL("internal"),
        .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"), .CLKOUTD_BYPASS("false"),
        .DYN_SDIV_SEL(2), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"),
        .DEVICE("GW2AR-18C")
    ) pll (
        .CLKOUT(clk_pixel), .LOCK(locked),
        .CLKOUTP(unused_p), .CLKOUTD(unused_d), .CLKOUTD3(unused_d3),
        .RESET(gnd), .RESET_P(gnd), .CLKIN(clk_27), .CLKFB(gnd),
        .FBDSEL({6{gnd}}), .IDSEL({6{gnd}}), .ODSEL({6{gnd}}),
        .PSDA({4{gnd}}), .DUTYDA({4{gnd}}), .FDLY({4{gnd}})
    );
endmodule
`default_nettype wire
