// One receiver channel for the mixer (runs on that TVP's own 27 MHz clock):
// bt656_rx -> word_packer, plus one marker entry after each completed line
// carrying the line's quality metrics. Entries (53 bits) go to an async FIFO:
//   word:   {1'b0, field, line[9:0], idx[8:0], data[31:0]}            (as in M2)
//   marker: {1'b1, field, line[9:0], hf[19:0], xy_bad[3:0], xy_corr[3:0], length[11:0], 1'b0}
// Counts and length saturate. The marker always follows the line's words.
`default_nettype none
module chan_capture (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  d,
    output reg         e_valid,
    output reg  [52:0] e_data,
    output wire        line_pulse         // one pulse per completed line (activity LED)
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
    assign line_pulse = rec_valid;

    wire w_valid, w_field;
    wire [31:0] w_data;
    wire [8:0] w_idx;
    wire [9:0] w_line;
    word_packer pack (.clk(clk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index),
                      .px_line(px_line), .px_field(px_field),
                      .w_valid(w_valid), .w_data(w_data), .w_idx(w_idx), .w_line(w_line), .w_field(w_field));

    function [3:0] sat4(input [7:0] v); sat4 = (v > 8'd15) ? 4'd15 : v[3:0]; endfunction
    wire [52:0] marker = {1'b1, rec_field, rec_line, rec_hf, sat4(rec_xy_bad), sat4(rec_xy_corrected),
                          (rec_length > 16'd4095) ? 12'd4095 : rec_length[11:0], 1'b0};

    // Words come at most every 4th cycle; a marker that collides with a word
    // waits one cycle in `pend`.
    reg        pend;
    reg [52:0] pend_data;
    always @(posedge clk) begin
        e_valid <= 1'b0;
        if (w_valid) begin
            e_valid <= 1'b1;
            e_data  <= {1'b0, w_field, w_line, w_idx, w_data};
        end else if (pend) begin
            e_valid <= 1'b1;
            e_data  <= pend_data;
            pend    <= 1'b0;
        end
        if (rec_valid) begin
            if (w_valid || pend) begin pend <= 1'b1; pend_data <= marker; end
            else begin e_valid <= 1'b1; e_data <= marker; end
        end
        if (rst) begin pend <= 1'b0; e_valid <= 1'b0; end
    end
endmodule
`default_nettype wire
