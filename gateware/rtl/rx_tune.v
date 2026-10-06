// Keeps both RX5808 modules on one fixed channel (no menu: M3, M4).
// First write START_MS after reset (the receivers may be powered after the
// FPGA), then again every PERIOD_MS for as long as no decoder reports lock.
// Never while a decoder is locked: whether rewriting an unchanged register
// disturbs the picture is unknown. An RTC6715 powers up on 5865 MHz (A1).
`default_nettype none
module rx_tune #(
    parameter CLK_HZ = 27_000_000,
    parameter START_MS = 500,
    parameter PERIOD_MS = 2000,
    parameter [5:0] CHANNEL = 6'd27          // index into vtx_channels.vh: 27 = F4 5800 MHz
) (
    input  wire clk,
    input  wire rst,
    input  wire locked,                      // any domain: some decoder has H + V lock
    output wire spi_clk, spi_data, spi_sel_n,
    output reg  [7:0] writes                 // frames sent (wraps), for reports
);
    `include "vtx_channels.vh"
    localparam MS = CLK_HZ / 1000;
    wire [41:0] ch = vtx_channel(CHANNEL);

    reg [1:0] ls;
    always @(posedge clk) ls <= {ls[0], locked};

    reg [$clog2(MS+1)-1:0] tick;
    reg [$clog2(PERIOD_MS + START_MS + 1)-1:0] ms;
    reg go, first_done;
    wire busy;
    wire [1:0] sel_n;
    rx5808_spi #(.HALF(CLK_HZ / 1_000_000 > 0 ? CLK_HZ / 1_000_000 : 1)) spi (
        .clk(clk), .rst(rst), .start(go), .sel_mask(2'b11), .addr(4'h1), .data(ch[19:0]),
        .busy(busy), .spi_clk(spi_clk), .spi_data(spi_data), .spi_sel_n(sel_n));
    assign spi_sel_n = sel_n[0];

    always @(posedge clk) begin
        go <= 1'b0;
        tick <= (tick == MS - 1) ? 0 : tick + 1'b1;
        if (tick == MS - 1) ms <= ms + 1'b1;
        if (!busy && !go) begin
            if (!first_done && ms >= START_MS) begin
                go <= 1'b1; first_done <= 1'b1; ms <= 0; writes <= writes + 1'b1;
            end else if (first_done && ms >= PERIOD_MS) begin
                ms <= 0;
                if (!ls[1]) begin go <= 1'b1; writes <= writes + 1'b1; end
            end
        end
        if (rst) begin tick <= 0; ms <= 0; go <= 1'b0; first_done <= 1'b0; writes <= 0; end
    end
endmodule
`default_nettype wire
