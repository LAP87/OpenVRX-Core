// flash_store against sim/spi_flash_model.v (8 KB at the top of the array, preloaded from
// mem.hex). sched.txt: lines "t_ms payload(20 hex digits)": the settings change to payload at
// t_ms; a loaded record replaces them, as in the menu. The run ends END_MS after start; the flash is dumped to mem_out.hex. Prints
//   LOAD <payload> <seq>   when the start scan loads a record
//   READY <t_ms>           when the start scan is over
//   END <programs> <erases> <dirty programs> <blocked> <err> <seq>
// Driven by sim/test_flash_store.py.
`timescale 1ns/1ps
`default_nettype none
module tb_flash_store;
    parameter CLK_HZ = 4_000_000;            // the start scan takes about 70 ms
    parameter SAVE_MS = 50;
    parameter END_MS = 2000;

    reg clk = 0, rst = 1;
    always #125 clk = ~clk;
    wire cs_n, sck, mosi, miso, wp_drive, load, ready, err;
    wire [79:0] loaded;
    wire [15:0] seq;
    reg  [79:0] cur = 80'h0;
    wire wp_n = wp_drive ? 1'b1 : 1'bz;
    flash_store #(.CLK_HZ(CLK_HZ), .SAVE_MS(SAVE_MS)) dut (
        .clk(clk), .rst(rst), .flash_cs_n(cs_n), .flash_clk(sck), .flash_mosi(mosi), .flash_miso(miso),
        .flash_wp_drive(wp_drive), .cur(cur), .loaded(loaded), .load(load), .ready(ready), .err(err), .seq(seq));
    spi_flash_model #(.LOAD(1)) flash (.cs_n(cs_n), .clk(sck), .mosi(mosi), .miso(miso), .wp_n(wp_n));

    always @(posedge clk) if (load) begin $display("LOAD %020x %0d", loaded, seq); cur <= loaded; end   // the menu takes it
    reg ready_d = 0;
    always @(posedge clk) begin ready_d <= ready; if (ready && !ready_d) $display("READY %0d", $time / 1_000_000); end

    integer fs, n, t_ms;
    reg [79:0] v;
    initial begin
        fs = $fopen("sched.txt", "r");
        #10_000 rst = 0;
        while (!$feof(fs)) begin
            n = $fscanf(fs, "%d %h\n", t_ms, v);
            if (n == 2) begin
                if ($time < t_ms * 1_000_000) #(t_ms * 1_000_000 - $time);
                @(posedge clk); cur <= v;
            end
        end
        if ($time < END_MS * 1_000_000) #(END_MS * 1_000_000 - $time);
        flash.dump;
        $display("END %0d %0d %0d %0d %0d %0d", flash.programs, flash.erases, flash.dirty_programs, flash.blocked, err, seq);
        $finish;
    end
endmodule
`default_nettype wire
