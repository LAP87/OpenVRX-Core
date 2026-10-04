// Turns the bt656_rx pixel stream into frame-buffer writes for a low-resolution
// luma-only field buffer: every second luma sample (720 -> 360 columns) of the
// first FB_LINES active lines of each field. Both fields write the same buffer
// (bob), which is what the M1 first-light display shows.
`default_nettype none

module luma_writer #(
    parameter FB_COLS  = 360,
    parameter FB_LINES = 240,
    parameter AW = 17
) (
    input  wire          clk,
    input  wire          px_valid,
    input  wire  [7:0]   px_data,
    input  wire  [10:0]  px_index,
    input  wire  [9:0]   px_line,
    output reg           we,
    output reg  [AW-1:0] addr,
    output reg  [7:0]    data
);
    // luma bytes sit at odd indices (Cb Y Cr Y ...); luma sample k = index >> 1
    wire [9:0] k   = px_index[10:1];
    wire       keep = px_valid && px_index[0] && !k[0] && (k[9:1] < FB_COLS) && (px_line < FB_LINES);
    always @(posedge clk) begin
        we   <= keep;
        addr <= px_line * FB_COLS + k[9:1];
        data <= px_data;
    end
endmodule
`default_nettype wire
