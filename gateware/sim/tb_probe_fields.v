// bt656_probe alone: +vec=<hex> is sent REPEAT times, then the window is latched and printed
// (FIELDS <fields> LINES <lines>). Used by sim/test_probe.py with a progressive vector (F always 1).
`timescale 1ns/1ps
`default_nettype none
module tb_probe_fields;
    parameter REPEAT = 4;
    reg clk = 0, rst = 1, snap = 0;
    always #18.5 clk = ~clk;
    reg [7:0] mem [0:1048575];
    reg [7:0] d = 8'h80;
    integer n, k, r;
    string vec;
    wire ack;
    wire [9:0] fields;
    wire [19:0] lines;
    bt656_probe probe (.clk(clk), .rst(rst), .d(d), .snap_toggle(snap), .ack_toggle(ack), .tog(), .hi(),
                       .len_min(), .len_max(), .lines(lines), .fields(fields), .xy_bad(), .div_out());
    initial begin
        if (!$value$plusargs("vec=%s", vec)) $fatal(1, "missing +vec=<file>");
        $readmemh(vec, mem);
        n = 0;
        while (mem[n] !== 8'bx && n < 1048575) n = n + 1;
        repeat (4) @(posedge clk);
        rst = 0;
        for (r = 0; r < REPEAT; r = r + 1)
            for (k = 0; k < n; k = k + 1) @(posedge clk) d <= mem[k];
        repeat (8) @(posedge clk) d <= 8'h80;
        snap = 1;
        @(ack);
        repeat (2) @(posedge clk);
        $display("FIELDS %0d LINES %0d", fields, lines);
        $finish;
    end
endmodule
`default_nettype wire
