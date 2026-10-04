// Testbench wrapper: bt656_rx -> luma_writer, the input half of m1_moneagle_view.
`default_nettype none
module tb_m1_input (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  d,
    output wire        we,
    output wire [16:0] addr,
    output wire [7:0]  data
);
    wire px_valid, px_field, rec_valid, rec_field;
    wire [7:0] px_data, rec_xy_corrected, rec_xy_bad;
    wire [10:0] px_index, rec_active;
    wire [9:0] px_line, rec_line;
    wire [15:0] rec_length;
    wire [19:0] rec_hf;
    bt656_rx rx (.clk(clk), .rst(rst), .d(d),
                 .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_field(px_field), .px_line(px_line),
                 .rec_valid(rec_valid), .rec_field(rec_field), .rec_line(rec_line), .rec_length(rec_length),
                 .rec_active(rec_active), .rec_xy_corrected(rec_xy_corrected), .rec_xy_bad(rec_xy_bad), .rec_hf(rec_hf));
    luma_writer #(.FB_COLS(360), .FB_LINES(240), .AW(17)) lw (
        .clk(clk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line),
        .we(we), .addr(addr), .data(data));
endmodule
`default_nettype wire
