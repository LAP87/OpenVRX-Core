// BT.601 limited-range YCbCr -> 8-bit RGB, 2 pipeline stages.
//   R = 1.164(Y-16) + 1.596(Cr-128)
//   G = 1.164(Y-16) - 0.813(Cr-128) - 0.392(Cb-128)
//   B = 1.164(Y-16) + 2.017(Cb-128)
// Coefficients x256: 298, 409, 208, 100, 516.
//
// All arithmetic is unsigned: Apicula has been seen to miscompile signed
// comparisons (otanl/CVBS2HDMI). Each sum is built from non-negative terms
// (negative coefficients act on 255 - x) and the constant offset is applied
// in the clamp as an unsigned compare and subtract:
//   R*256 = 298y + 409cr               - 56992
//   G*256 = 298y + 208(255-cr) + 100(255-cb) - 43756
//   B*256 = 298y + 516cb               - 70688
// (offsets include the +128 rounding term). Bit-exact with the signed version.
`default_nettype none
module ycbcr2rgb (
    input  wire       clk,
    input  wire [7:0] y, cb, cr,
    output reg  [7:0] r, g, b
);
    localparam [17:0] OFF_R = 18'd56992, OFF_G = 18'd43756, OFF_B = 18'd70688;
    reg [17:0] rr, gg, bb;

    // v - off, clamped to 0..255 after >> 8 (v - off is in [0, 65280] when not clamped)
    function [7:0] clamp(input [17:0] v, input [17:0] off);
        reg [17:0] d;
        begin
            d = v - off;
            clamp = (v < off) ? 8'd0 : (v > off + 18'd65280) ? 8'd255 : d[15:8];
        end
    endfunction

    always @(posedge clk) begin
        rr <= 18'd298 * y + 18'd409 * cr;
        gg <= 18'd298 * y + 18'd208 * (8'd255 - cr) + 18'd100 * (8'd255 - cb);
        bb <= 18'd298 * y + 18'd516 * cb;
        r <= clamp(rr, OFF_R);
        g <= clamp(gg, OFF_G);
        b <= clamp(bb, OFF_B);
    end
endmodule
`default_nettype wire
