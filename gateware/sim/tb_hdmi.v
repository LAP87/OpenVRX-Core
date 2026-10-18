// tmds_link.v in a small picture: a timing generator with sync, a pixel pattern from a counter, and
// hz50 changed every second frame; every clock's inputs and the three symbols go to sym.txt.
// rgb_full starts at RGB_FULL (the link's range until the first vsync). RAMP = 1: the pattern
// counts over the active pixels (R = n, G = 255 - n, B = n + 85, mod 256), so every component value
// appears; else a pseudo-random pattern. SWITCH = 1: rgb_full toggles in the middle of each frame's
// active picture, far from vsync.
// Driven by sim/test_hdmi.py, which decodes the symbols.
`timescale 1ns/1ps
`default_nettype none
module tb_hdmi;
    parameter HDMI = 1, RGB_FULL = 1, RAMP = 0, SWITCH = 0;
    parameter H_ACTIVE = 40, H_FP = 8, H_SYNC = 8, H_BP = 20;
    parameter V_ACTIVE = 10, V_FP = 2, V_SYNC = 2, V_BP = 6;
    parameter FRAMES = 4;
    localparam H_TOTAL = H_ACTIVE + H_FP + H_SYNC + H_BP, V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;

    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    integer x = 0, y = 0, frame = 0;
    reg [23:0] pat = RAMP ? 24'h00FF55 : 24'h123456;
    reg [7:0]  n = 8'd0;
    reg        rgb_full = (RGB_FULL != 0);
    wire de    = x < H_ACTIVE && y < V_ACTIVE;
    wire hsync = x >= H_ACTIVE + H_FP && x < H_ACTIVE + H_FP + H_SYNC;
    wire vsync = y >= V_ACTIVE + V_FP && y < V_ACTIVE + V_FP + V_SYNC;
    wire hz50  = frame[1];
    wire [9:0] s0, s1, s2;
    tmds_link #(.HDMI(HDMI), .RGB_FULL(RGB_FULL)) dut (.clk(clk), .rst(rst), .de(de), .hsync(hsync), .vsync(vsync),
        .r(pat[23:16]), .g(pat[15:8]), .b(pat[7:0]), .hz50(hz50), .rgb_full(rgb_full), .sym0(s0), .sym1(s1), .sym2(s2));

    integer f;
    always @(posedge clk) if (!rst) begin
        // inputs as presented at this edge, and the symbols the link puts out after it
        $fwrite(f, "%0d %0d %0d %0d %06x %0d %0d %0d %0d\n", de, hsync, vsync, hz50, pat, s0, s1, s2, rgb_full);
        if (RAMP == 0) pat <= {pat[22:0], pat[23] ^ pat[22] ^ pat[21] ^ pat[16]} + 24'd7;
        else if (de) begin n <= n + 8'd1; pat <= {n + 8'd1, 8'd254 - n, n + 8'd86}; end
        if (SWITCH != 0 && x == 0 && y == V_ACTIVE / 2) rgb_full <= !rgb_full;
        if (x == H_TOTAL - 1) begin
            x <= 0;
            if (y == V_TOTAL - 1) begin y <= 0; frame <= frame + 1; end else y <= y + 1;
        end else x <= x + 1;
    end
    initial begin
        f = $fopen("sym.txt", "w");
        #100 rst = 0;
        wait (frame == FRAMES);
        $fclose(f);
        $finish;
    end
endmodule
`default_nettype wire
