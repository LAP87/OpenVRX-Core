// Formal harness for async_fifo.v (properties live in its `ifdef FORMAL block).
// Two independent free clocks, free enables and data; formal/run.sh starts every
// register at 0, which is the FIFO's reset state.
`default_nettype none
module fifo_props #(parameter AW = 2, parameter W = 2) (
    input wire         wclk, rclk,
    input wire         wr_en, rd_en,
    input wire [W-1:0] wr_data
);
    wire full, empty;
    wire [W-1:0] rd_data;
    wire [AW:0] wl, rl;
    async_fifo #(.W(W), .AW(AW)) dut (
        .wclk(wclk), .wrst(1'b0), .wr_en(wr_en), .wr_data(wr_data), .full(full), .wr_level(wl),
        .rclk(rclk), .rrst(1'b0), .rd_en(rd_en), .rd_data(rd_data), .empty(empty), .rd_level(rl));
endmodule
`default_nettype wire
