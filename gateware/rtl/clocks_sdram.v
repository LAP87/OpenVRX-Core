// 27 MHz -> 64.8 MHz SDRAM controller clock, and a copy shifted 225 degrees for
// the SDRAM chip.
// rPLL: 27 * (FBDIV_SEL+1) / (IDIV_SEL+1) = 27 * 12 / 5 = 64.8 MHz,
// VCO = 64.8 * ODIV_SEL(8) = 518.4 MHz. CLKOUTP: PSDA_SEL 1010 = 10/16 of a
// period late (UG286 Table 5-7), DUTYDA_SEL 1000 = 8/16 duty (Table 5-8).
//
// Why 225 degrees, and what that is worth:
//  * Proven on hardware upstream: nand2mario's NESTang runs the Tang Nano
//    20K's SDRAM at 64.8 MHz from an rPLL with exactly these settings
//    (src/pllr/gowin_pll_nes.v). His 27 MHz example and Seyviour's port of
//    it to the open toolchain have the same phase (src/gowin_rpll/
//    gowin_rpll.v in both). All read single words and sample them CAS+1
//    clocks after the READ command.
//  * Not proven: this project. sdram_burst.v reads 8-word bursts, which
//    upstream never does (see its header), and nothing here has run on
//    hardware. This file used 180 degrees until 2026-10-05. No upstream
//    design does; the "normally 180-degrees" in nand2mario's port comment is
//    not what his PLLs are set to.
//  * The phase is a tuning knob. Gowin's own controller guide says so
//    (IPUG279: "the phase of I_sdram_clk can be adjusted to meet the setup
//    and hold time requirements of read and write signals").
//    top/m2a_memtest.v shows on the board which sample point reads correctly.
//    To try another phase without editing this file:
//    SDRAM_PHASE=<0..15> gateware/build.sh <top> defines SDRAM_PHASE, in
//    sixteenths of a period (8 = 180, 10 = 225, 12 = 270 degrees).
`default_nettype none
module clocks_sdram (
    input  wire clk_27,
    output wire clk,          // 64.8 MHz
    output wire clk_shift,    // 64.8 MHz, 225 degrees late
    output wire locked
);
    wire gnd = 1'b0;
    wire unused_d, unused_d3;
`ifdef SDRAM_PHASE
    localparam [3:0] PHASE = `SDRAM_PHASE;
`endif
    rPLL #(
        .FCLKIN("27"),
        .DYN_IDIV_SEL("false"), .IDIV_SEL(4),
        .DYN_FBDIV_SEL("false"), .FBDIV_SEL(11),
        .DYN_ODIV_SEL("false"), .ODIV_SEL(8),
`ifdef SDRAM_PHASE
        .PSDA_SEL(PHASE),             // four bits, read like the string below
`else
        .PSDA_SEL("1010"),
`endif
        .DYN_DA_EN("false"), .DUTYDA_SEL("1000"),
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
