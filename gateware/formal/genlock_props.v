// Formal harness for genlock_timing.v (properties in its `ifdef FORMAL block):
// small video timing, lock/trig/h_alt free every clock; registers start at 0.
// Independently count the registered output's vsync edges between frame starts.
`default_nettype none
module genlock_props (
    input wire clk, rst, lock, trig, h_alt
);
    wire [11:0] x, y;
    wire de, hs, vs, fs, triggered;
    genlock_timing #(.H_ACTIVE(4), .H_FP(1), .H_SYNC(1), .H_BP(1), .H_FP_ALT(3),
                     .V_ACTIVE(4), .V_FP(1), .V_SYNC(2), .V_BP(4), .MAX_WAIT(3), .JUMP_AFTER(2), .HOLD(2)) dut (
        .clk(clk), .rst(rst), .lock(lock), .trig(trig), .h_alt(h_alt),
        .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs), .triggered(triggered));
    reg vs_prev, fs_prev, have_frame;
    reg [1:0] pulses;
    always @(posedge clk) begin
        vs_prev <= vs; fs_prev <= fs;
        if (rst) begin have_frame <= 1'b0; pulses <= 0; end
        else if (fs && !fs_prev) begin
            have_frame <= 1'b1; pulses <= 0;
        end else if (have_frame && vs && !vs_prev) begin
            pulses <= pulses + 1'b1;
        end
    end
    always @* begin
        if (!rst && have_frame) begin
            if (fs && !fs_prev) assert (pulses == 1);
            else if (vs && !vs_prev) assert (pulses == 0);
        end
        // y and vs are registered together; no inserted pulse or missing sync line.
        assert (vs == (y >= 5 && y < 7));
    end
endmodule
`default_nettype wire
