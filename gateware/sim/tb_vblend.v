// vblend.v against model/fb_ref.py vblend(): reads (a, b, w) from vec.hex, writes y per line.
// Driven by sim/test_vblend.py.
`timescale 1ns/1ps
`default_nettype none
module tb_vblend;
    parameter N = 1;
    reg  [19:0] vec [0:N-1];              // {w[3:0], a[7:0], b[7:0]}
    reg  [7:0]  a, b;
    reg  [3:0]  w;
    wire [7:0]  y;
    vblend dut (.a(a), .b(b), .w(w), .y(y));
    integer i, f;
    initial begin
        $readmemh("vec.hex", vec);
        f = $fopen("out.txt", "w");
        for (i = 0; i < N; i = i + 1) begin
            {w, a, b} = vec[i];
            #1 $fwrite(f, "%0d\n", y);
        end
        $fclose(f);
        $finish;
    end
endmodule
`default_nettype wire
