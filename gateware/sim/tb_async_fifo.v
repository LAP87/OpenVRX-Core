// async_fifo.v with RD_REG = 0 and RD_REG = 1 side by side, same clocks, resets and enables.
// The reader stalls for random stretches and then pops back to back, so that several words are
// visible at once (mixer2.v pops every word as soon as it is visible and never shows this).
// out.txt: "W data" for every accepted write, "P0 data" / "P1 data" for every pop of each FIFO,
// and at the end "D n": clocks on which !empty and the two rd_data differed, "E n": clocks on
// which empty, full or the levels differed, "B n": pops on the clock after a pop, "F n": write
// clocks with the FIFO full.
`timescale 1ns/1ps
`default_nettype none
module tb_async_fifo;
    parameter W = 16, AW = 3, N = 6000, SEED = 1;
    parameter real TW = 37.0, TR = 13.0;     // clock periods (ns)
    reg wclk = 0, rclk = 0, wrst = 1, rrst = 1, wr_en = 0, rd_en = 0;
    reg [W-1:0] wr_data = 0;
    wire full0, full1, empty0, empty1;
    wire [W-1:0] rd0, rd1;
    wire [AW:0] wl0, wl1, rl0, rl1;
    async_fifo #(.W(W), .AW(AW), .RD_REG(0)) f0 (
        .wclk(wclk), .wrst(wrst), .wr_en(wr_en), .wr_data(wr_data), .full(full0), .wr_level(wl0),
        .rclk(rclk), .rrst(rrst), .rd_en(rd_en), .rd_data(rd0), .empty(empty0), .rd_level(rl0));
    async_fifo #(.W(W), .AW(AW), .RD_REG(1)) f1 (
        .wclk(wclk), .wrst(wrst), .wr_en(wr_en), .wr_data(wr_data), .full(full1), .wr_level(wl1),
        .rclk(rclk), .rrst(rrst), .rd_en(rd_en), .rd_data(rd1), .empty(empty1), .rd_level(rl1));

    always #(TW / 2) wclk = !wclk;
    always #(TR / 2) rclk = !rclk;

    integer fd, seed_w, seed_r, n_w = 0, n_r = 0, diff = 0, ediff = 0, burst = 0, stall = 0;
    initial begin
        fd = $fopen("out.txt", "w");
        seed_w = SEED; seed_r = SEED + 1000;
    end

    // writer: bursts and pauses
    always @(posedge wclk) begin
        if (!wrst && wr_en && !full0) begin $fwrite(fd, "W %0d\n", wr_data); n_w = n_w + 1; end
        if (burst > 0) begin burst = burst - 1; wr_en <= 1'b1; end
        else begin wr_en <= 1'b0; if (($random(seed_w) & 7) == 0) burst = $random(seed_w) & 15; end
        wr_data <= $random(seed_w);
    end

    // reader: stalls, then pops every clock
    integer b2b = 0, n_full = 0;
    reg popped = 1'b0;
    always @(posedge wclk) if (!wrst && full0) n_full = n_full + 1;
    always @(posedge rclk) begin
        if (!rrst && rd_en && !empty0) begin
            $fwrite(fd, "P0 %0d\n", rd0); n_r = n_r + 1;
            if (popped) b2b = b2b + 1;
        end
        popped <= !rrst && rd_en && !empty0;
        if (!rrst && rd_en && !empty1) $fwrite(fd, "P1 %0d\n", rd1);
        if (!rrst && !empty0 && rd0 !== rd1) diff = diff + 1;
        if (empty0 !== empty1 || full0 !== full1 || rl0 !== rl1 || wl0 !== wl1) ediff = ediff + 1;
        if (stall > 0) begin stall = stall - 1; rd_en <= 1'b0; end
        else begin rd_en <= 1'b1; if (($random(seed_r) & 15) == 0) stall = $random(seed_r) & 31; end
    end

    // A reset must last two clocks of the other side for the pointer synchronisers to see it
    // (they are not reset); six periods of the slower clock here.
    localparam real TRST = 6.0 * (TW > TR ? TW : TR);
    initial begin
        #(TRST) wrst = 0; rrst = 0;
        // both sides reset again in the middle, with words in the FIFO
        #(N * TR / 2) wrst = 1; rrst = 1;
        $fwrite(fd, "RESET\n");
        #(TRST) wrst = 0; rrst = 0;
        #(N * TR / 2);
        $fwrite(fd, "D %0d\nE %0d\nB %0d\nF %0d\n", diff, ediff, b2b, n_full);
        $fclose(fd);
        $finish;
    end
endmodule
`default_nettype wire
