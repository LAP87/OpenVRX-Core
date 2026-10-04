// bt1120_tx on a tiny raster; pixel data = function of x/y, delivered LAT clocks late.
`timescale 1ns/1ps
`default_nettype none
module tb_bt1120;
    localparam HA = 16, HT = 28, VA = 4, VT = 6, LAT = 5;
    reg clk = 0;
    always #5 clk = ~clk;
    reg [11:0] x = 0, y = 0;
    always @(posedge clk) begin
        x <= (x == HT - 1) ? 0 : x + 1;
        if (x == HT - 1) y <= (y == VT - 1) ? 0 : y + 1;
    end
    // pixel source: Y = 40 + x + 8y, Cb = 100 + x, Cr = 150 + y (LAT clocks behind x/y)
    reg [7:0] py [0:LAT-1], pb [0:LAT-1], pr [0:LAT-1];
    integer i;
    always @(posedge clk) begin
        py[0] <= 40 + x + 8 * y; pb[0] <= 100 + x; pr[0] <= 150 + y;
        for (i = 1; i < LAT; i = i + 1) begin py[i] <= py[i-1]; pb[i] <= pb[i-1]; pr[i] <= pr[i-1]; end
    end
    wire [7:0] oy, oc;
    bt1120_tx #(.H_ACTIVE(HA), .H_TOTAL(HT), .V_ACTIVE(VA), .V_TOTAL(VT), .LAT(LAT)) dut (
        .clk(clk), .x(x), .y(y), .yy(py[LAT-1]), .cb(pb[LAT-1]), .cr(pr[LAT-1]), .out_y(oy), .out_c(oc));
    // remember x/y LAT+1 clocks back to label the output
    reg [11:0] hx [0:LAT], hy [0:LAT];
    always @(posedge clk) begin
        hx[0] <= x; hy[0] <= y;
        for (i = 1; i <= LAT; i = i + 1) begin hx[i] <= hx[i-1]; hy[i] <= hy[i-1]; end
    end
    integer n = 0;
    always @(posedge clk) begin
        n <= n + 1;
        if (n > 2 * HT * VT) $display("O %0d %0d %02x %02x", hx[LAT], hy[LAT], oy, oc);
        if (n > 4 * HT * VT) $finish;
    end
endmodule
`default_nettype wire
