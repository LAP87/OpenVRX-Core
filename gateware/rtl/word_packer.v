// Packs the receiver's active-video byte stream (Cb Y Cr Y ...) into 32-bit
// words {Y1, Cr, Y0, Cb} (byte 0 = Cb, i.e. little-endian in the word), one
// word per two pixels, tagged with field, line and word index (0..359).
`default_nettype none
module word_packer (
    input  wire        clk,
    input  wire        px_valid,
    input  wire [7:0]  px_data,
    input  wire [10:0] px_index,
    input  wire [9:0]  px_line,
    input  wire        px_field,
    output reg         w_valid,
    output reg  [31:0] w_data,
    output reg  [8:0]  w_idx,
    output reg  [9:0]  w_line,
    output reg         w_field
);
    reg [23:0] acc;
    always @(posedge clk) begin
        w_valid <= 1'b0;
        if (px_valid) begin
            case (px_index[1:0])
                2'd0: acc[7:0]   <= px_data;
                2'd1: acc[15:8]  <= px_data;
                2'd2: acc[23:16] <= px_data;
                2'd3: begin
                    w_valid <= (px_index[10:2] < 9'd360);
                    w_data  <= {px_data, acc};
                    w_idx   <= px_index[10:2];
                    w_line  <= px_line;
                    w_field <= px_field;
                end
            endcase
        end
    end
endmodule
`default_nettype wire
