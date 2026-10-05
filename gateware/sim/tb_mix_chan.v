// Small line-ring scoreboard: a partially lost line must never become readable.
`timescale 1ns/1ps
module tb_mix_chan;
    reg clk = 0, rst = 1, ext_bad = 0, empty = 1, pop_line = 0;
    always #7.7 clk = ~clk;
    reg [52:0] data = 0;
    reg [8:0] rd_idx = 0;
    wire [31:0] rd_data;
    wire [2:0] count;
    wire [9:0] line_no;
    wire [7:0] epoch;
    wire bad, alive, overflow;
    mix_chan #(.N_WORDS(4)) dut (.clk(clk), .rst(rst), .ext_bad(ext_bad),
        .in_empty(empty), .in_data(data), .in_pop(), .pop_line(pop_line),
        .rd_idx(rd_idx), .rd_data(rd_data), .count(count), .head_field(),
        .head_line(line_no), .head_hf(), .head_bad(bad), .head_epoch(epoch),
        .head_age(), .alive(alive), .overflow(overflow));

    task put(input [52:0] entry);
        begin
            @(negedge clk); data = entry; empty = 0;
            @(negedge clk); empty = 1;
        end
    endtask
    task word_entry(input [9:0] l, input [8:0] i);
        reg [31:0] value;
        begin value = 32'h10000000 + l * 16 + i; put({1'b0, 1'b0, l, i, value}); end
    endtask
    task marker(input [9:0] l);
        begin put({1'b1, 1'b0, l, 20'd0, 4'd0, 4'd0, 12'd1716, 1'b0}); end
    endtask
    task complete_line(input [9:0] l);
        integer i;
        begin for (i = 0; i < 4; i = i + 1) word_entry(l, i); marker(l); end
    endtask
    task release_head;
        begin @(negedge clk); pop_line = 1; @(negedge clk); pop_line = 0; end
    endtask
    task reset_dut;
        begin @(negedge clk); rst = 1; repeat (3) @(negedge clk); rst = 0; end
    endtask

    integer i;
    initial begin
        reset_dut();
        for (i = 0; i < 4; i = i + 1) complete_line(i);
        if (count != 4) $fatal(1, "ring not full");
        word_entry(4, 0);                  // full at the start of this line
        release_head();                   // a slot becomes available halfway through
        for (i = 1; i < 4; i = i + 1) word_entry(4, i);
        marker(4);
        if (count != 3) $fatal(1, "partial full line published");
        if (!overflow) $fatal(1, "full-line loss not reported");
        complete_line(5);
        repeat (3) release_head();
        if (count != 1 || line_no != 5) $fatal(1, "wrong surviving line");
        for (i = 0; i < 4; i = i + 1) begin
            @(negedge clk); rd_idx = i;
            repeat (2) @(negedge clk);
            if (rd_data !== 32'h10000050 + i) $fatal(1, "stale word in complete line");
        end
        reset_dut();
        complete_line(0);
        word_entry(1, 0); word_entry(1, 2); word_entry(1, 3); marker(1);
        if (count != 1) $fatal(1, "line with missing word published");
        complete_line(2);
        if (count != 2) $fatal(1, "next complete line lost");
        ext_bad = 1; repeat (3) @(negedge clk);
        if (!bad) $fatal(1, "forced mode did not affect waiting head");
        ext_bad = 0; repeat (3) @(negedge clk);
        if (bad) $fatal(1, "forced mode latched into line metadata");
        // Data captured during a fault stays bad after recovery. A later good
        // line must not inherit the old flag after the synchronizer settles.
        reset_dut();
        ext_bad = 1; repeat (3) @(negedge clk);
        complete_line(0);
        ext_bad = 0; repeat (3) @(negedge clk);
        if (!bad) $fatal(1, "captured fault cleared on recovery");
        complete_line(1);
        release_head();
        if (bad) $fatal(1, "recovered line inherited old fault");
        // About 1.54 ms: realistic PAL vertical blanking, beyond old 1.01 ms timeout.
        repeat (100000) @(negedge clk);
        if (!alive) $fatal(1, "healthy channel died in VBI");
        repeat (262150) @(negedge clk);
        if (alive) $fatal(1, "stopped channel did not expire");
        $display("ring scoreboard passed");
        $finish;
    end
endmodule
