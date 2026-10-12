// DVI (or, with HDMI = 1, HDMI with an AVI InfoFrame: tmds_link.v) transmitter for Gowin GW2A:
// TMDS symbols, OSER10 serialisers and true-LVDS output buffers (Tang Nano 20K HDMI connector uses TLVDS).
// Primitive usage follows the apicula DVI example (YosysHQ/apicula examples/DVI).
`default_nettype none

module dvi_tx_gowin (
    input  wire       clk_pixel,     // e.g. 74.25 MHz for 720p
    input  wire       clk_serial,    // 5 x clk_pixel (DDR -> 10 bits per pixel)
    input  wire       rst,
    input  wire       de,
    input  wire       hsync,
    input  wire       vsync,
    input  wire [7:0] r,
    input  wire [7:0] g,
    input  wire [7:0] b,
    input  wire       hz50,          // HDMI = 1: the timing is 720p50 (AVI VIC 19); ignored in DVI mode
    output wire       tmds_clk_p,
    output wire       tmds_clk_n,
    output wire [2:0] tmds_d_p,
    output wire [2:0] tmds_d_n
);
    wire [9:0] sym [0:2];
    tmds_link link (.clk(clk_pixel), .rst(rst), .de(de), .hsync(hsync), .vsync(vsync), .r(r), .g(g), .b(b),
                    .hz50(hz50), .sym0(sym[0]), .sym1(sym[1]), .sym2(sym[2]));

    wire [2:0] ser;
    genvar c;
    generate
        for (c = 0; c < 3; c = c + 1) begin : serialisers
            OSER10 ser10 (
                .Q(ser[c]),
                .D0(sym[c][0]), .D1(sym[c][1]), .D2(sym[c][2]), .D3(sym[c][3]), .D4(sym[c][4]),
                .D5(sym[c][5]), .D6(sym[c][6]), .D7(sym[c][7]), .D8(sym[c][8]), .D9(sym[c][9]),
                .PCLK(clk_pixel), .FCLK(clk_serial), .RESET(rst));
        end
    endgenerate

    TLVDS_OBUF obuf [3:0] (
        .I ({clk_pixel, ser}),
        .O ({tmds_clk_p, tmds_d_p}),
        .OB({tmds_clk_n, tmds_d_n}));
endmodule
`default_nettype wire
