// rx5808_tune against a scripted sequence of lock changes and channel changes.
// Prints every stimulus event and every SPI frame for sim/test_rx5808_tune.py,
// which compares the frames with its own model of the rule.
//   SCENARIO 0  unlocked start, lock, channel change while locked, unlock, a short
//               lock, a channel change in the middle of a frame
//   SCENARIO 1  a decoder is locked from the start
//   USE_LOCK 0  the lock input is held low although the events are printed: what a
//               design that ignores the lock would do (negative control)
//   IDLE_DATA   the level DATA is expected to hold between frames
`timescale 1ns/1ps
`default_nettype none
module tb_rx5808_tune;
    parameter SCENARIO = 0;
    parameter USE_LOCK = 1;
    parameter IDLE_DATA = 1;
    reg clk = 0, rst = 1;
    always #500 clk = ~clk;                       // 1 MHz: 1 ms = 1000 clocks
    reg [19:0] synth = 20'h02984;                 // F4
    reg        write_now = 0, lock = 0;
    wire       sclk, sdat;
    wire [1:0] sel_n;
    rx5808_tune #(.CLK_HZ(1_000_000), .FIRST_MS(50), .REPEAT_MS(200)) dut (
        .clk(clk), .rst(rst), .synth(synth), .write_now(write_now), .any_locked(lock && USE_LOCK != 0),
        .spi_clk(sclk), .spi_data(sdat), .spi_sel_n(sel_n));

    // a frame: starts when SEL falls, one bit per rising clock edge, printed when SEL rises
    reg [24:0] bits;
    integer    n = 0;
    time       t0;
    always @(negedge sel_n[0]) t0 = $time;
    always @(posedge sclk) if (!sel_n[0]) begin bits[n] <= sdat; n <= n + 1; end
    always @(posedge sel_n[0]) begin
        if (n > 0) $display("SPI %0d %0d %07x", t0, n, bits);
        n = 0;
    end
    // between frames CLK is low and DATA at its idle level; the two SEL outputs always agree
    integer idle_bad = 0, sel_bad = 0;
    always @(posedge clk) if (!rst) begin
        if (sel_n == 2'b11 && (sclk !== 1'b0 || sdat !== IDLE_DATA[0])) idle_bad = idle_bad + 1;
        if (sel_n[0] !== sel_n[1]) sel_bad = sel_bad + 1;
    end

    task set_lock(input v);
        begin lock = v; $display("LOCK %0d %0d", $time, v); end
    endtask
    task change(input [19:0] s);                  // as puck_ui does it: the pulse, then the new word
        begin
            @(posedge clk) write_now <= 1'b1;
            $display("WRITE %0d %05x", $time, s);
            @(posedge clk) begin write_now <= 1'b0; synth <= s; end
        end
    endtask

    initial begin
        if (SCENARIO == 1) set_lock(1);
        #3000 rst = 0;
        if (SCENARIO == 0) begin
            #499_997_000 set_lock(1);             //  500 ms
            #200_000_000 change(20'h02913);       //  700 ms: A6, although a decoder is locked
            #300_000_000 set_lock(0);             // 1000 ms
            #500_000_000 set_lock(1);             // 1500 ms
            #10_000_000  set_lock(0);             // 1510 ms: the repeat interval starts again
            #200_050_000 change(20'h02903);       // 1710.05 ms: B1, in the middle of the repeat frame
            #90_000_000;
        end else #600_000_000;
        $display("RESULT idle_bad=%0d sel_bad=%0d", idle_bad, sel_bad);
        $finish;
    end
endmodule
`default_nettype wire
