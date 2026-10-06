// Stand-in for rtl/ycbcr2rgb.v in formal/linebuf_props.v: same ports, no arithmetic.
`default_nettype none
module ycbcr2rgb (
    input  wire       clk,
    input  wire [7:0] y, cb, cr,
    output reg  [7:0] r, g, b
);
    always @(posedge clk) {r, g, b} <= {y, cb, cr};
endmodule
`default_nettype wire
