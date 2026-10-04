// snow_stats with 16-line windows: A gets lines with hf = 100 + i, B none at first,
// decisions cycle A, A, B, blend. Prints each finished window.
`timescale 1ns/1ps
module tb_snow_stats;
    reg clk = 0, rst = 1;
    always #5 clk = ~clk;
    reg line_a = 0, line_b = 0, dv = 0;
    reg [19:0] hf_a = 0, hf_b = 0;
    reg [1:0] du = 0;
    wire [19:0] ma, mb;
    wire [4:0] ua, ub, um;
    wire ta, tb, tu;
    snow_stats #(.LOG_N(4)) dut (.clk(clk), .rst(rst), .line_a(line_a), .hf_a(hf_a), .line_b(line_b), .hf_b(hf_b),
        .dec_valid(dv), .dec_use(du), .mean_a(ma), .mean_b(mb), .use_a(ua), .use_b(ub), .use_mix(um),
        .toggle_a(ta), .toggle_b(tb), .toggle_use(tu));
    always @(ta) if (!rst) $display("A %0d", ma);
    always @(tb) if (!rst) $display("B %0d", mb);
    always @(tu) if (!rst) $display("U %0d %0d %0d", ua, ub, um);
    integer i;
    initial begin
        #20 rst = 0;
        for (i = 0; i < 40; i = i + 1) begin
            @(negedge clk); line_a = 1; hf_a = 100 + i; dv = 1; du = (i % 4 == 2) ? 2'b10 : (i % 4 == 3) ? 2'b11 : 2'b01;
            line_b = (i >= 8); hf_b = 5000;
            @(negedge clk); line_a = 0; line_b = 0; dv = 0;
        end
        #50 $finish;
    end
endmodule
