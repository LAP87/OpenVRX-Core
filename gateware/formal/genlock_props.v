// Formal harness for genlock_timing.v (properties in its `ifdef FORMAL block):
// small video timing, lock/trig/h_alt free every clock; registers start at 0.
`default_nettype none
module genlock_props (
    input wire clk, rst, lock, trig, h_alt
);
    wire [11:0] x, y;
    wire de, hs, vs, fs;
    genlock_timing #(.H_ACTIVE(4), .H_FP(1), .H_SYNC(1), .H_BP(1), .H_FP_ALT(3),
                     .V_ACTIVE(4), .V_FP(1), .V_SYNC(1), .V_BP(2), .MAX_WAIT(3), .JUMP_AFTER(2), .HOLD(2)) dut (
        .clk(clk), .rst(rst), .lock(lock), .trig(trig), .h_alt(h_alt),
        .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs));
endmodule
`default_nettype wire
