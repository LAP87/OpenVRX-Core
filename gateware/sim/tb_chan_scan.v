// chan_scan against a small world (world.txt, one line per channel 0..47):
//   lock_a noise_a lock_b noise_b
// A decoder reports lock LOCK_MS after its channel is tuned, if the world says it locks there.
// Noise windows end every WIN_A_US / WIN_B_US (different, so the phases drift); a window's
// value is the noise of the channel that was tuned when the window began, so the first window
// after a retune can still belong to the previous channel. NO_B = 1: receiver B delivers no
// windows. ABORT_MS > 0: a button aborts the scan then.
// Prints every tune "T idx t_us", every noise window "WA t_us value" / "WB t_us value", and at
// the end "D idx found t_us" and the channel left tuned. Driven by sim/test_chan_scan.py, which
// works out from these events alone what each channel should have scored.
`timescale 1ns/1ps
`default_nettype none
module tb_chan_scan;
    parameter CLK_HZ = 100_000;               // 10 us clock: 100 clocks per ms
    parameter START = 3;
    parameter LOCK_MS = 25;
    parameter WIN_A_US = 65_500, WIN_B_US = 64_100, WIN_B_PHASE_US = 17_000;
    parameter NO_B = 0;
    parameter ABORT_MS = 0;

    reg clk = 0, rst = 1;
    always #5000 clk = ~clk;

    reg [31:0] lock_a [0:47];
    reg [31:0] noise_a [0:47];
    reg [31:0] lock_b [0:47];
    reg [31:0] noise_b [0:47];
    integer fw, i, n, la, na, lb, nb;
    initial begin
        fw = $fopen("world.txt", "r");
        for (i = 0; i < 48; i = i + 1) begin
            n = $fscanf(fw, "%d %d %d %d\n", la, na, lb, nb);
            lock_a[i] = la; noise_a[i] = na; lock_b[i] = lb; noise_b[i] = nb;
        end
        $fclose(fw);
    end

    reg  start = 0, abort = 0;
    wire busy, tune, done, found;
    wire [5:0] idx;
    reg  [5:0] tuned = START;
    integer t_us = 0, t_tune = 0;
    always @(posedge clk) begin
        t_us = t_us + 10;
        if (tune) begin tuned = idx; t_tune = t_us; $display("T %0d %0d", idx, t_us); end
    end
    wire since_ok = (t_us - t_tune) >= LOCK_MS * 1000;
    wire [1:0] locked = {since_ok && lock_b[tuned] != 0, since_ok && lock_a[tuned] != 0};

    // noise windows: value from the channel tuned when the window began
    reg new_a = 0, new_b = 0;
    reg [19:0] va = 0, vb = 0;
    reg [5:0] ch_at_start_a = START, ch_at_start_b = START;
    integer next_a = WIN_A_US, next_b = WIN_B_PHASE_US;
    always @(posedge clk) begin
        new_a <= 0; new_b <= 0;
        if (t_us >= next_a) begin
            va <= noise_a[ch_at_start_a]; new_a <= 1; $display("WA %0d %0d", t_us, noise_a[ch_at_start_a]);
            ch_at_start_a = tuned; next_a = next_a + WIN_A_US;
        end
        if (!NO_B && t_us >= next_b) begin
            vb <= noise_b[ch_at_start_b]; new_b <= 1; $display("WB %0d %0d", t_us, noise_b[ch_at_start_b]);
            ch_at_start_b = tuned; next_b = next_b + WIN_B_US;
        end
    end

    chan_scan #(.CLK_HZ(CLK_HZ), .MAX_MS(200)) dut (
        .clk(clk), .rst(rst), .start(start), .abort(abort), .cur_idx(START[5:0]), .locked(locked),
        .new_a(new_a), .new_b(new_b), .noise_a(va), .noise_b(vb),
        .busy(busy), .idx(idx), .tune(tune), .done(done), .found(found));

    initial begin
        repeat (10) @(posedge clk);
        rst <= 0;
        repeat (500) @(posedge clk);
        start <= 1; @(posedge clk); start <= 0;
        if (ABORT_MS > 0) begin
            repeat (ABORT_MS * (CLK_HZ / 1000)) @(posedge clk);
            abort <= 1; @(posedge clk); abort <= 0;
        end
        @(posedge done);
        #1 $display("D %0d %0d %0d", idx, found, t_us);
        repeat (10) @(posedge clk);
        $display("TUNED %0d", tuned);
        $finish;
    end
    initial begin #(30.0e9) $display("TIMEOUT"); $finish; end
endmodule
`default_nettype wire
