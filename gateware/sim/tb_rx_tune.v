// rx_tune: first write after START_MS, rewrites every PERIOD_MS only while
// nothing is locked. CLK_HZ 100 kHz makes a "millisecond" 100 clocks.
`timescale 1ns/1ps
`default_nettype none
module tb_rx_tune;
    reg clk = 0, rst = 1, locked = 0;
    always #5 clk = ~clk;
    wire sclk, sdat, sel;
    wire [7:0] writes;
    rx_tune #(.CLK_HZ(100_000), .START_MS(5), .PERIOD_MS(20)) dut (
        .clk(clk), .rst(rst), .locked(locked), .spi_clk(sclk), .spi_data(sdat), .spi_sel_n(sel), .writes(writes));
    integer frames = 0, bits = 0;
    reg [24:0] word;
    always @(posedge sclk) if (!sel) begin word[bits] <= sdat; bits <= bits + 1; end
    always @(posedge sel) if (bits > 0) begin
        frames = frames + 1; $display("FRAME %0d bits=%0d word=%07x t=%0t", frames, bits, word, $time); bits = 0;
    end
    reg idle_high_ok = 1;
    always @(posedge clk) if (!rst && sel && !sdat && $time > 1000) idle_high_ok = 0;
    initial begin
        #100 rst = 0;
        #(4 * 1000);                 // 4 ms: before START_MS
        $display("MARK before_start frames=%0d", frames);
        #(60 * 1000);                // to 64 ms, unlocked: first write at 5 ms, rewrites at 25, 45
        $display("MARK unlocked frames=%0d", frames);
        locked = 1;
        #(100 * 1000);               // locked for 100 ms: no rewrites
        $display("MARK locked frames=%0d", frames);
        locked = 0;
        #(30 * 1000);                // unlocked again: rewrites resume on the 20 ms cadence (166, 186 ms)
        $display("MARK relost frames=%0d idle_high=%0d", frames, idle_high_ok);
        $finish;
    end
endmodule
`default_nettype wire
