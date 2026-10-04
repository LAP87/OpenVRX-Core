// 27 MHz crystal -> 371.25 MHz serial clock -> /5 -> 74.25 MHz pixel clock (720p60).
// rPLL: fout = 27 * (FBDIV_SEL+1) / (IDIV_SEL+1) = 27 * 55 / 4 = 371.25 MHz,
// VCO = fout * ODIV_SEL = 742.5 MHz, PFD = 6.75 MHz.
// Parameter style follows apicula examples/DVI/pll480.v.
`default_nettype none

module clocks_720p (
    input  wire clk_27,
    output wire clk_serial,   // 371.25 MHz
    output wire clk_pixel,    // 74.25 MHz
    output wire locked
);
    wire gnd = 1'b0;
    wire unused_p, unused_d, unused_d3;

    rPLL #(
        .FCLKIN("27"),
        .DYN_IDIV_SEL("false"), .IDIV_SEL(3),
        .DYN_FBDIV_SEL("false"), .FBDIV_SEL(54),
        .DYN_ODIV_SEL("false"), .ODIV_SEL(2),
        .PSDA_SEL("0000"), .DYN_DA_EN("true"), .DUTYDA_SEL("1000"),
        .CLKOUT_FT_DIR(1'b1), .CLKOUTP_FT_DIR(1'b1),
        .CLKOUT_DLY_STEP(0), .CLKOUTP_DLY_STEP(0),
        .CLKFB_SEL("internal"),
        .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"), .CLKOUTD_BYPASS("false"),
        .DYN_SDIV_SEL(2), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"),
        .DEVICE("GW2AR-18C")
    ) pll (
        .CLKOUT(clk_serial), .LOCK(locked),
        .CLKOUTP(unused_p), .CLKOUTD(unused_d), .CLKOUTD3(unused_d3),
        .RESET(gnd), .RESET_P(gnd), .CLKIN(clk_27), .CLKFB(gnd),
        .FBDSEL({6{gnd}}), .IDSEL({6{gnd}}), .ODSEL({6{gnd}}),
        .PSDA({4{gnd}}), .DUTYDA({4{gnd}}), .FDLY({4{gnd}})
    );

    CLKDIV #(.DIV_MODE("5")) div5 (
        .CLKOUT(clk_pixel), .HCLKIN(clk_serial), .RESETN(locked));
endmodule
`default_nettype wire
