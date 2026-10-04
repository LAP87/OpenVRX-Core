// Testbench wrapper: tvp_sync_rx -> luma_writer (input half of m1s_moneagle_view_sync),
// with small parameters so a synthetic mini-format simulates quickly.
`default_nettype none
module tb_m1s_input #(
    parameter FB_COLS = 30, FB_LINES = 16, POL_WINDOW_LOG2 = 13   // 8192 clocks > one 4800-clock test field
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  d,
    input  wire        hsync_in,
    input  wire        vsync_in,
    input  wire        avid_in,
    output wire        we,
    output wire [16:0] addr,
    output wire [7:0]  data,
    output wire        luma_odd,
    output wire        vs_active_high,
    output wire        avid_active_high
);
    wire px_valid, px_field, line_done, hs_active_high;
    wire [7:0] px_data;
    wire [10:0] px_index, line_bytes;
    wire [9:0] px_line;
    tvp_sync_rx #(.POL_WINDOW_LOG2(POL_WINDOW_LOG2)) rx (
        .clk(clk), .rst(rst), .d(d), .hsync_in(hsync_in), .vsync_in(vsync_in), .avid_in(avid_in),
        .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line), .px_field(px_field),
        .line_done(line_done), .line_bytes(line_bytes), .hs_active_high(hs_active_high),
        .vs_active_high(vs_active_high), .avid_active_high(avid_active_high), .luma_odd(luma_odd));
    luma_writer #(.FB_COLS(FB_COLS), .FB_LINES(FB_LINES), .AW(17)) lw (
        .clk(clk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line),
        .we(we), .addr(addr), .data(data));
endmodule
`default_nettype wire
