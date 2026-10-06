// mixer2 with two BT.656 byte streams from hex files (a.hex, b.hex), each on its
// own clock; prints what the two noise_stats instances report: every line
// (LA/LB field line count) and every finished window (WA/WB sum), with
// windows shortened to 2^LOG_N lines. Driven by sim/test_noise_stats.py.
`timescale 1ns/1ps
`default_nettype none
module tb_noise_stats;
    parameter N_A = 1, N_B = 1;               // stream lengths (bytes)
    parameter LOG_N = 3;
    parameter real T_A = 37.0, T_B = 36.93, T_S = 15.4;
    defparam dut.noise_a_st.LOG_N = LOG_N;
    defparam dut.noise_b_st.LOG_N = LOG_N;

    reg a_clk = 0, b_clk = 0, sys_clk = 0, rst = 1;
    always #(T_A / 2) a_clk = ~a_clk;
    always #(T_B / 2) b_clk = ~b_clk;
    always #(T_S / 2) sys_clk = ~sys_clk;

    reg [7:0] mem_a [0:N_A-1];
    reg [7:0] mem_b [0:N_B-1];
    reg [7:0] a_d = 8'h80, b_d = 8'h80;
    integer ia = 0, ib = 0;
    reg run = 0;
    always @(negedge a_clk) if (run) begin
        if (ia < N_A) begin a_d <= mem_a[ia]; ia <= ia + 1; end else a_d <= 8'h80;
    end
    always @(negedge b_clk) if (run) begin
        if (ib < N_B) begin b_d <= mem_b[ib]; ib <= ib + 1; end else b_d <= 8'h80;
    end

    wire        out_empty, dec_valid, dec_field, cur, overflow, alive_a, alive_b, a_lines, b_lines;
    wire [51:0] out_data;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    wire [19:0] noise_a, noise_b;
    wire        nta, ntb;
    mixer2 dut (.a_clk(a_clk), .a_d(a_d), .b_clk(b_clk), .b_d(b_d), .sys_clk(sys_clk), .rst_async(rst),
                .ext_bad_a(1'b0), .ext_bad_b(1'b0),
                .out_empty(out_empty), .out_data(out_data), .out_pop(!out_empty),
                .a_lines(a_lines), .b_lines(b_lines), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
                .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
                .dec_field(dec_field), .dec_line(dec_line),
                .noise_a(noise_a), .noise_b(noise_b), .noise_toggle_a(nta), .noise_toggle_b(ntb));

    always @(posedge sys_clk) begin
        if (dut.noise_a_st.line_valid)
            $display("LA %0d %0d %0d", dut.noise_a_st.line_field, dut.noise_a_st.line_no, dut.noise_a_st.line_count);
        if (dut.noise_b_st.line_valid)
            $display("LB %0d %0d %0d", dut.noise_b_st.line_field, dut.noise_b_st.line_no, dut.noise_b_st.line_count);
    end
    always @(nta) if (!rst) $display("WA %0d", noise_a);
    always @(ntb) if (!rst) $display("WB %0d", noise_b);

    initial begin
        $readmemh("a.hex", mem_a);
        $readmemh("b.hex", mem_b);
        #500 rst = 0;
        #2000 run = 1;
        wait (ia == N_A && ib == N_B);
        #20000;
        $display("END overflow=%0d", overflow);
        $finish;
    end
endmodule
`default_nettype wire
