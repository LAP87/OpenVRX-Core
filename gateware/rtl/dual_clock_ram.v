// Simple dual-port RAM, write and read on different clocks (yosys maps it to
// Gowin BSRAM SDPB blocks). Read data is registered: 1 cycle latency.
`default_nettype none

module dual_clock_ram #(
    parameter DEPTH = 86400,
    parameter AW = 17,
    parameter W = 8
) (
    input  wire          wclk,
    input  wire          we,
    input  wire [AW-1:0] waddr,
    input  wire [W-1:0]  wdata,
    input  wire          rclk,
    input  wire [AW-1:0] raddr,
    output reg  [W-1:0]  rdata
);
    reg [W-1:0] mem [0:DEPTH-1];
    always @(posedge wclk) if (we) mem[waddr] <= wdata;
    always @(posedge rclk) rdata <= mem[raddr];
endmodule
`default_nettype wire
