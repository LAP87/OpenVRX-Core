// osd_overlay on a 300 x 140 raster (256 x 120 active), SCALE 2, box at (10, 20).
// Video in = pattern of the pixel position, delivered LAT clocks after x/y.
`timescale 1ns/1ps
`default_nettype none
module tb_osd;
    parameter SHOW = 1;
    localparam HT = 300, VT = 140, HA = 256, VA = 120, LAT = 6;
    reg clk = 0;
    always #5 clk = ~clk;
    reg [11:0] x = 0, y = 0;
    always @(posedge clk) begin
        x <= (x == HT - 1) ? 0 : x + 1;
        if (x == HT - 1) y <= (y == VT - 1) ? 0 : y + 1;
    end
    // video pipeline LAT deep: r = x, g = y, b = 0x40, de in the active area
    reg [7:0] pr [0:LAT-1], pg [0:LAT-1];
    reg [LAT-1:0] pde;
    integer i;
    always @(posedge clk) begin
        pr[0] <= x[7:0]; pg[0] <= y[7:0]; pde <= {pde[LAT-2:0], (x < HA) && (y < VA)};
        for (i = 1; i < LAT; i = i + 1) begin pr[i] <= pr[i-1]; pg[i] <= pg[i-1]; end
    end
    // write the text RAM from a list
    reg we = 0; reg [6:0] wa, wc;
    reg [7:0] msg [0:83];
    initial $readmemh("text.hex", msg);
    wire [7:0] r, g, b;
    wire de, hs, vs;
    osd_overlay #(.X0(10), .Y0(20), .SCALE(2), .LAT(LAT), .PAD(3)) dut (
        .clk(clk), .show(SHOW[0]), .x(x), .y(y), .r_in(pr[LAT-1]), .g_in(pg[LAT-1]), .b_in(8'h40),
        .de_in(pde[LAT-1]), .hs_in(1'b0), .vs_in(1'b0), .r(r), .g(g), .b(b), .de(de), .hs(hs), .vs(vs),
        .wclk(clk), .we(we), .waddr(wa), .wchar(wc));
    // label each output with the x/y it belongs to (LAT + 1 clocks back)
    reg [11:0] hx [0:LAT], hy [0:LAT];
    always @(posedge clk) begin
        hx[0] <= x; hy[0] <= y;
        for (i = 1; i <= LAT; i = i + 1) begin hx[i] <= hx[i-1]; hy[i] <= hy[i-1]; end
    end
    integer frame = 0, k;
    always @(posedge clk) begin
        if (x == 0 && y == 0) frame <= frame + 1;
        if (frame == 2 && de) $display("P %0d %0d %02x %02x %02x", hx[LAT], hy[LAT], r, g, b);
        if (frame == 3) $finish;
    end
    initial begin
        for (k = 0; k < 84; k = k + 1) begin
            @(negedge clk); we = 1; wa = (k / 21) * 32 + (k % 21); wc = msg[k][6:0];
        end
        @(negedge clk); we = 0;
    end
endmodule
`default_nettype wire
