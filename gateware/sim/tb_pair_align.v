// Drives rtl/pair_align.v with a sample file (one 6-bit sample per line, hex) at 40 MHz and writes its
// output: one line per sample "<q> <phase> <mism>" (hex), q being the registered output for that sample
// (one clock after it). sim/test_pair_align.py compares with model/pair_align_ref.py.
//   vvp sim.vvp +hex=<samples> +out=<file> [+n=<samples to drive>]
// +define+PA_HOLD_MIN=<n> sets HOLD_MIN (a huge value freezes the phase: the negative control).
`timescale 1ns / 1ps
module tb_pair_align;
`ifndef PA_HOLD_MIN
`define PA_HOLD_MIN 16
`endif
    reg clk = 1'b0;
    always #12.5 clk = ~clk;                 // 40 MHz
    reg        rst = 1'b1;
    reg  [5:0] d = 6'd0;
    wire [5:0] q;
    wire       phase;
    wire [11:0] mism;
    pair_align #(.HOLD_MIN(`PA_HOLD_MIN)) dut (.clk(clk), .rst(rst), .d(d), .q(q), .phase(phase), .mism(mism));

    reg [7:0] mem [0:1048575];
    integer n, i, fd, written;
    reg [1023:0] hexfile, outfile;
    reg driving = 1'b0, driving_q = 1'b0;
    initial begin
        if (!$value$plusargs("hex=%s", hexfile)) begin $display("need +hex="); $finish; end
        if (!$value$plusargs("out=%s", outfile)) begin $display("need +out="); $finish; end
        if (!$value$plusargs("n=%d", n)) n = 0;
        for (i = 0; i < 1048576; i = i + 1) mem[i] = 8'hFF;
        $readmemh(hexfile, mem);
        if (n == 0) while (n < 1048576 && mem[n] !== 8'hFF) n = n + 1;
        fd = $fopen(outfile, "w");
        written = 0;
        repeat (4) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(posedge clk);
            rst <= 1'b0;                      // the first sample arrives with the reset release, as the model's clock 0
            d <= mem[i][5:0];
            driving <= 1'b1;
        end
        @(posedge clk);
        driving <= 1'b0;
        repeat (2) @(posedge clk);            // the last sample's q is written two clocks after it was applied
        $fclose(fd);
        $display("RESULT samples=%0d written=%0d", n, written);
        $finish;
    end
    // q for sample k is valid the clock after sample k was applied: write it then
    always @(posedge clk) begin
        driving_q <= driving && !rst;
        if (driving_q) begin
            $fdisplay(fd, "%02x %0d %03x", q, phase, mism);
            written = written + 1;
        end
    end
endmodule
