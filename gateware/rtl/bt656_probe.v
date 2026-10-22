// Bring-up probe for one BT.656 input, on that decoder's own SCLK.
//
// Collects, per window: which data bits were ever 1 / ever toggled, the
// shortest and longest line (bytes between EAVs of active lines, from
// bt656_rx), active lines, fields and timing codes with
// uncorrectable errors. A toggle on snap_toggle (any domain) latches the
// window into the outputs, starts a new one and toggles ack_toggle once the
// outputs are stable. No ack means no SCLK.
//
// Fields are counted at their first active line (bt656_rx numbers lines from
// the vertical blanking), not at changes of the F bit: a TVP5150AM1 holds F at 1
// for a non-interlaced source, which counted 0 fields until 2026-10-21 (hub
// LOGIKGRANSKNING F8).
//
// div_out is SCLK / 256 for a frequency counter in another domain.
`default_nettype none
module bt656_probe (
    input  wire        clk,                // decoder SCLK
    input  wire        rst,                // synchronous to clk
    input  wire [7:0]  d,
    input  wire        snap_toggle,
    output reg         ack_toggle,
    output reg  [7:0]  tog,                // bits seen both 0 and 1
    output reg  [7:0]  hi,                 // bits seen 1
    output reg  [15:0] len_min, len_max,   // 0 / 0 when no line ended
    output reg  [19:0] lines,
    output reg  [9:0]  fields,             // first active lines of a field (one per field)
    output reg  [15:0] xy_bad,
    output wire        div_out
);
    reg [7:0] din;
    always @(posedge clk) din <= d;

    wire        rec_valid, rec_field, px_valid, px_field;
    wire [9:0]  rec_line, px_line;
    wire [15:0] rec_length;
    wire [10:0] rec_active, px_index;
    wire [7:0]  rec_xy_corrected, rec_xy_bad, px_data;
    wire [19:0] rec_hf;
    bt656_rx rx (.clk(clk), .rst(rst), .d(din),
                 .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_field(px_field), .px_line(px_line),
                 .rec_valid(rec_valid), .rec_field(rec_field), .rec_line(rec_line), .rec_length(rec_length),
                 .rec_active(rec_active), .rec_xy_corrected(rec_xy_corrected), .rec_xy_bad(rec_xy_bad), .rec_hf(rec_hf));

    reg [7:0] dv;
    always @(posedge clk) dv <= rst ? 8'd0 : dv + 1'b1;
    assign div_out = dv[7];

    reg  [2:0]  st;
    wire        snap = st[2] != st[1];
    reg  [7:0]  a_seen0, a_seen1;
    reg  [15:0] a_min, a_max, a_bad;
    reg  [19:0] a_lines;
    reg  [9:0]  a_fields;
    wire        len_ok = rec_valid && rec_length != 0;
    wire [16:0] bad_sum = {1'b0, a_bad} + rec_xy_bad;
    always @(posedge clk) begin
        st <= {st[1:0], snap_toggle};
        if (snap) begin
            tog <= a_seen0 & a_seen1;  hi <= a_seen1;
            len_min <= (a_lines == 0) ? 16'd0 : a_min;  len_max <= a_max;
            lines <= a_lines;  fields <= a_fields;  xy_bad <= a_bad;
            ack_toggle <= ~ack_toggle;
            a_seen0 <= ~din;  a_seen1 <= din;
            a_min <= 16'hFFFF;  a_max <= 0;  a_bad <= 0;  a_lines <= 0;  a_fields <= 0;
        end else begin
            a_seen0 <= a_seen0 | ~din;
            a_seen1 <= a_seen1 | din;
            if (len_ok && rec_length < a_min) a_min <= rec_length;
            if (len_ok && rec_length > a_max) a_max <= rec_length;
            if (rec_valid) begin
                if (a_lines != 20'hFFFFF) a_lines <= a_lines + 1'b1;
                a_bad <= bad_sum[16] ? 16'hFFFF : bad_sum[15:0];
                if (rec_line == 10'd0 && a_fields != 10'h3FF) a_fields <= a_fields + 1'b1;
            end
        end
        if (rst) begin
            st <= 0; ack_toggle <= 1'b0;
            a_seen0 <= 0; a_seen1 <= 0; a_min <= 16'hFFFF; a_max <= 0; a_bad <= 0; a_lines <= 0; a_fields <= 0;
        end
    end
endmodule
`default_nettype wire
