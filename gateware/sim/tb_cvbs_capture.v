// Drives rtl/cvbs_capture.v with a sample file (one 6-bit sample per line, hex) at the 40 MHz
// sample clock and writes every entry it emits as 14 hex digits per line. sim/test_cvbs_capture.py
// makes the samples with model/cvbs_capture_ref.py and compares the entries with the model's.
//   vvp sim.vvp +hex=<samples> +out=<entries> [+n=<samples to drive>]
// +define+CVBS_COMB=0 builds the capture without the 1H comb (the negative control).
`timescale 1ns / 1ps
module tb_cvbs_capture;
`ifndef CVBS_COMB
`define CVBS_COMB 1
`endif
    reg clk = 1'b0;
    always #12.5 clk = ~clk;                 // 40 MHz
    reg        rst = 1'b1;
    reg  [5:0] d = 6'd22;
    wire       e_valid, line_pulse;
    wire [52:0] e_data;
    cvbs_capture #(.COMB(`CVBS_COMB)) dut (.clk(clk), .rst(rst), .d(d), .e_valid(e_valid), .e_data(e_data), .line_pulse(line_pulse));

    reg [7:0] mem [0:4194303];               // up to 4 M samples (three frames)
    integer n, i, fd, entries;
    reg [1023:0] hexfile, outfile;
    initial begin
        if (!$value$plusargs("hex=%s", hexfile)) begin $display("need +hex="); $finish; end
        if (!$value$plusargs("out=%s", outfile)) begin $display("need +out="); $finish; end
        if (!$value$plusargs("n=%d", n)) n = 0;
        for (i = 0; i < 4194304; i = i + 1) mem[i] = 8'hFF;
        $readmemh(hexfile, mem);
        if (n == 0) begin
            n = 0;
            while (n < 4194304 && mem[n] !== 8'hFF) n = n + 1;
        end
        fd = $fopen(outfile, "w");
        entries = 0;
        repeat (4) @(posedge clk);
        for (i = 0; i < n; i = i + 1) begin
            @(posedge clk);
            rst <= 1'b0;                      // the first sample arrives with the reset release:
            d <= mem[i][5:0];                 // sample k is the k-th clock the model sees too
        end
        repeat (8) @(posedge clk);
        $fclose(fd);
        $display("RESULT samples=%0d entries=%0d", n, entries);
        $finish;
    end
    always @(posedge clk) if (e_valid && !rst) begin
        $fdisplay(fd, "%014x", e_data);
        entries = entries + 1;
    end
endmodule
