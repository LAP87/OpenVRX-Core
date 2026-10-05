// Self-running testbench for mixer2: two BT.656 byte streams from hex files on
// their own clocks, output words and decisions written to text files.
// Driven by sim/test_mixer.py (which generates the streams and checks the files).
`timescale 1ns/1ps
`default_nettype none
module tb_mixer;
    parameter N_A = 1, N_B = 1;               // stream lengths (bytes)
    parameter T_PAIR = 1024, N_STEP = 8, N_DEAD = 40;
    parameter real T_A = 37.0, T_B = 37.002, T_S = 15.4;
    parameter real START_A = 2000.0, START_B = 5300.0;
    // decoder status "no lock": high from *_ON to *_OFF (ns). ON < 0: never. OFF <= ON: until the end.
    parameter real EXTA_ON = -1.0, EXTA_OFF = -1.0, EXTB_ON = -1.0, EXTB_OFF = -1.0;
    parameter POP_DIV = 1;                    // the output is read every POP_DIV-th cycle (back-pressure)
    parameter real TAIL = 300000.0;           // ns to run after both streams end

    reg a_clk = 0, b_clk = 0, sys_clk = 0, rst = 1;
    always #(T_A / 2) a_clk = ~a_clk;
    always #(T_B / 2) b_clk = ~b_clk;
    always #(T_S / 2) sys_clk = ~sys_clk;

    reg [7:0] mem_a [0:N_A-1];
    reg [7:0] mem_b [0:N_B-1];
    reg [7:0] a_d = 8'h80, b_d = 8'h80;
    integer ia = 0, ib = 0;
    reg run_a = 0, run_b = 0;
    always @(negedge a_clk) if (run_a) begin
        if (ia < N_A) begin a_d <= mem_a[ia]; ia <= ia + 1; end else a_d <= 8'h80;
    end
    always @(negedge b_clk) if (run_b) begin
        if (ib < N_B) begin b_d <= mem_b[ib]; ib <= ib + 1; end else b_d <= 8'h80;
    end

    reg ext_a = 0, ext_b = 0;
    initial if (EXTA_ON >= 0.0) begin
        #(EXTA_ON) ext_a = 1;
        if (EXTA_OFF > EXTA_ON) begin #(EXTA_OFF - EXTA_ON) ext_a = 0; end
    end
    initial if (EXTB_ON >= 0.0) begin
        #(EXTB_ON) ext_b = 1;
        if (EXTB_OFF > EXTB_ON) begin #(EXTB_OFF - EXTB_ON) ext_b = 0; end
    end

    integer pc = 0;
    always @(posedge sys_clk) pc <= (pc >= POP_DIV - 1) ? 0 : pc + 1;

    wire        out_empty, dec_valid, dec_field, cur, overflow, alive_a, alive_b, a_lines, b_lines;
    wire [51:0] out_data;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    wire        out_pop = !out_empty && pc == 0;
    mixer2 #(.T_PAIR(T_PAIR), .N_STEP(N_STEP), .N_DEAD(N_DEAD)) dut (
                .a_clk(a_clk), .a_d(a_d), .b_clk(b_clk), .b_d(b_d), .sys_clk(sys_clk), .rst_async(rst),
                .ext_bad_a(ext_a), .ext_bad_b(ext_b),
                .out_empty(out_empty), .out_data(out_data), .out_pop(out_pop),
                .a_lines(a_lines), .b_lines(b_lines), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
                .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
                .dec_field(dec_field), .dec_line(dec_line));

    integer fo, fd;
    always @(posedge sys_clk) begin
        if (out_pop) $fwrite(fo, "%0d %0d %0d %08x\n", out_data[51], out_data[50:41], out_data[40:32], out_data[31:0]);
        // `cur` already shows the value this decision left behind
        if (dec_valid) $fwrite(fd, "%0d %0d %0d %0d %0d %0d\n", dec_use, dec_pop, dec_field, dec_line, cur, $realtime);
    end

    initial begin
        $readmemh("a.hex", mem_a);
        $readmemh("b.hex", mem_b);
        fo = $fopen("out.txt", "w");
        fd = $fopen("dec.txt", "w");
        #500 rst = 0;
        fork
            begin #(START_A); run_a = 1; end
            begin #(START_B); run_b = 1; end
        join
        wait (ia == N_A && ib == N_B);
        #(TAIL);
        $fwrite(fd, "end %0d %0d\n", overflow, cur);
        $fclose(fo); $fclose(fd);
        $finish;
    end
endmodule
`default_nettype wire
