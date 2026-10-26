// mixer2 with B_DIGITAL (hub plan task 69): channel B is a composite sample bus from a hex file at
// 40 MHz, channel A is idle, and ext_bad_b is held high, as dec_bad.v holds it when no TVP B answers.
// Writes every change of the mixer's b_lock output and of mix_chan B's synchronised ext_bad
// (dut.ch_b.ext_s[1]) with the time in ns, then "end <b_lock> <ext_bad>". sim/test_mixer_digital.py
// checks that the digital build swaps the status input for the capture's lock and that the BT.656
// build (B_DIGITAL = 0, the negative control) keeps the status input.
`timescale 1ns/1ps
`default_nettype none
module tb_mixer_digital;
    parameter N_B = 1;                        // samples
    parameter B_DIGITAL = 1;
    parameter real T_A = 37.0, T_B = 25.0, T_S = 15.4, TAIL = 20000.0;

    reg a_clk = 0, b_clk = 0, sys_clk = 0, rst = 1;
    always #(T_A / 2) a_clk = ~a_clk;
    always #(T_B / 2) b_clk = ~b_clk;
    always #(T_S / 2) sys_clk = ~sys_clk;

    reg [7:0] mem_b [0:N_B-1];
    reg [7:0] b_d = 8'd22;                    // blank level between runs
    integer ib = 0;
    reg run_b = 0;
    always @(negedge b_clk) if (run_b) begin
        if (ib < N_B) begin b_d <= mem_b[ib]; ib <= ib + 1; end else b_d <= 8'd22;
    end

    wire        out_empty, b_lock;
    wire [51:0] out_data;
    mixer2 #(.B_DIGITAL(B_DIGITAL)) dut (
        .a_clk(a_clk), .a_d(8'h80), .b_clk(b_clk), .b_d(b_d), .sys_clk(sys_clk), .rst_async(rst),
        .ext_bad_a(1'b1), .ext_bad_b(1'b1), .ext_weak_a(1'b0), .ext_weak_b(1'b0),
        .out_empty(out_empty), .out_data(out_data), .out_pop(!out_empty),
        .b_lock(b_lock));

    wire bad_s = dut.ch_b.ext_s[1];           // what mix_chan B's bad_in sees
    integer fo;
    reg lock_q = 1'b0, bad_q = 1'b1;
    always @(posedge sys_clk) if (!rst && (^{b_lock, bad_s}) !== 1'bx && (b_lock !== lock_q || bad_s !== bad_q)) begin
        $fwrite(fo, "%0d %0d %0d\n", $time, b_lock, bad_s);
        lock_q <= b_lock; bad_q <= bad_s;
    end

    initial begin
        $readmemh("b.hex", mem_b);
        fo = $fopen("trace.txt", "w");
        #500 rst = 0;
        #2000 run_b = 1;
        wait (ib == N_B);
        #(TAIL);
        $fwrite(fo, "end %0d %0d\n", b_lock, bad_s);
        $fclose(fo);
        $finish;
    end
endmodule
`default_nettype wire
