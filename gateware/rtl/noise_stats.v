// Out-of-range luma counter for one mixer channel (mixer / SDRAM clock domain).
//
// Counts, per line, the luma samples outside 16..235 in the words the channel's
// capture FIFO delivers (chan_capture.v entries; a word is {Y1, Cr, Y0, Cb}).
// BT.656 allows 1..254 in video data, but a decoder keeps picture luma within
// 16..235, so impulse noise and disturbed sync are what lands outside. Unlike
// the HF energy (snow_stats.v) the count does not depend on picture detail.
//
// Per line, at the marker entry that ends it: line_valid for one cycle with the
// line's field, number and count. Words of a line whose marker never comes are
// dropped when the next line's first word (index 0) arrives. The count
// saturates at 1023 (a whole line has 720 luma samples).
//
// Per window of 2^LOG_N lines: the sum of the line counts on `sum`, and
// `toggle` flips. `sum` stays stable until the next window, so another clock
// domain can copy it after synchronising the toggle.
//
// Measured and logged only (puck_ui.v); the mixer does not use it.
// Reference: luma_outside() in model/bt656.py, test: sim/test_noise_stats.py.
`default_nettype none
module noise_stats #(
    parameter LOG_N = 10
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        valid,             // an entry leaves the channel FIFO (first-word fall-through)
    input  wire [52:0] data,              // the entry (chan_capture.v format)
    output reg         line_valid,
    output reg         line_field,
    output reg  [9:0]  line_no,
    output reg  [9:0]  line_count,
    output reg  [LOG_N+9:0] sum,
    output reg         toggle
);
    function outside(input [7:0] y);
        outside = (y < 8'd16) || (y > 8'd235);
    endfunction

    wire        is_marker = data[52];
    wire [8:0]  idx       = data[40:32];
    wire [1:0]  n_word    = {1'b0, outside(data[15:8])} + {1'b0, outside(data[31:24])};   // Y0, Y1
    reg  [9:0]  cnt;
    wire [9:0]  base      = (idx == 9'd0) ? 10'd0 : cnt;
    wire [10:0] cnt_n     = {1'b0, base} + {9'd0, n_word};
    reg  [LOG_N+9:0] acc;
    reg  [LOG_N-1:0] n_l;

    always @(posedge clk) begin
        line_valid <= 1'b0;
        if (valid && !is_marker)
            cnt <= cnt_n[10] ? 10'd1023 : cnt_n[9:0];
        if (valid && is_marker) begin
            line_valid <= 1'b1;
            line_field <= data[51];
            line_no    <= data[50:41];
            line_count <= cnt;
            cnt        <= 10'd0;
            if (&n_l) begin
                sum <= acc + cnt; acc <= 0; toggle <= ~toggle;
            end else acc <= acc + cnt;
            n_l <= n_l + 1'b1;
        end
        if (rst) begin
            cnt <= 0; acc <= 0; n_l <= 0; sum <= 0; toggle <= 1'b0; line_valid <= 1'b0;
        end
    end
endmodule
`default_nettype wire
