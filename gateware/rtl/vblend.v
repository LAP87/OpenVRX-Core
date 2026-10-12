// Vertical interpolation of one 8-bit sample between two source lines (fb_display.v, VINTERP = 1):
// y = (a * (8 - w) + b * w) / 8, rounded down, for a weight w of 0..8 eighths towards b.
// w = 0 passes a through untouched (b is then not looked at, so an unwritten b cannot reach the
// output), w = 8 gives b. Unsigned throughout (Apicula: no signed arithmetic).
// Compared with model/fb_ref.py vblend() in sim/test_vblend.py.
`default_nettype none
module vblend (
    input  wire [7:0] a,
    input  wire [7:0] b,
    input  wire [3:0] w,              // 0..8
    output wire [7:0] y
);
    wire [3:0]  wa  = 4'd8 - w;
    wire [11:0] sum = a * wa + b * w;  // at most 255 * 8 = 2040
    assign y = (w == 4'd0) ? a : sum[10:3];
endmodule
`default_nettype wire
