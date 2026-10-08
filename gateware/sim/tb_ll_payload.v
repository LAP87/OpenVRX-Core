// fb_backend in low-latency mode, fed tagged words directly (no SDRAM traffic):
// a field of lines 0-2 that the writer joins (no trigger, its count is not
// kept), a field of lines 0-2, a field of lines 0-1, then the first word of a third
// field, which starts the instant the second field's trigger has been sent
// (GUARD = 0) or 20 SDRAM clocks later (GUARD = 1). Prints every trigger as it
// leaves the SDRAM domain (SEND, with the line count it carries) and as the
// pixel domain takes it (RECEIVE). After the review fixture in the hub,
// docs/reviews/2026-10-06/repro/ll_payload.v. Driven by sim/test_ll_payload.py.
`timescale 1ns/1ps
`default_nettype none
module tb_ll_payload;
    parameter GUARD = 0;
    reg sd_clk = 0, pix_clk = 0, rst = 1, empty = 1;
    reg [51:0] data = 0;
    always #7.7 sd_clk = ~sd_clk;               // 64.9 MHz
    always #6.7 pix_clk = ~pix_clk;             // 74.6 MHz
    wire pop;
    wire [31:0] dq;
    fb_backend #(.LL_EQ(0)) dut (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk), .pix_clk(pix_clk),
        .rst_async(rst), .ll_mode(1'b1), .f_empty(empty), .f_data(data), .f_pop(pop),
        .SDRAM_DQ(dq));

    reg last = 0;
    always @(posedge sd_clk) begin
        #1;
        if (!rst && dut.s_ll_trig !== last) $display("SEND %0d", dut.ll_rx.din);
        last = dut.s_ll_trig;
    end
    always @(posedge pix_clk) begin
        #1;
        if (!rst && dut.ll_trig) $display("RECEIVE %0d", dut.ll_lines);
    end

    task word(input f, input [9:0] ln, input [8:0] idx);
        begin @(negedge sd_clk); empty = 0; data = {f, ln, idx, 32'h10203040}; end
    endtask
    task line(input f, input [9:0] n);
        integer w;
        begin for (w = 0; w < 360; w = w + 1) word(f, n, w[8:0]); end
    endtask
    initial begin
        #100 rst = 0;
        repeat (10) @(posedge sd_clk);
        line(1, 0); line(1, 1); line(1, 2);      // the field the writer joins: it fires no trigger
        line(0, 0); line(0, 1); line(0, 2);
        line(1, 0); line(1, 1);
        if (GUARD != 0) begin
            @(negedge sd_clk); empty = 1;
            repeat (20) @(posedge sd_clk);
        end
        word(0, 0, 0);
        @(negedge sd_clk); empty = 1;
        repeat (60) @(posedge sd_clk);
        $display("DONE");
        $finish;
    end
endmodule
`default_nettype wire
