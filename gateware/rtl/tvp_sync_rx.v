// Receiver for a TVP5150AM1 in "8-bit 4:2:2 with discrete syncs" mode:
// YOUT[7:0] + SCLK (27 MHz) + HSYNC, VSYNC and AVID pins.
//
// Same pixel interface as bt656_rx (px_valid/px_data/px_index/px_line), so
// luma_writer and the display path are reused unchanged.
//
// Moneagle's SoC configures the TVP, so polarities and the AVID window are
// unknown; this module adapts:
//  * polarity of HSYNC, VSYNC and AVID is measured over a window of
//    2^POL_WINDOW_LOG2 clocks (must exceed one field): sync pulses are the
//    minority level, AVID the majority level (~78 % of the time in real video);
//    only clear majorities change the decision (hysteresis);
//  * which byte phase carries luma is decided once per field from the energy
//    of same-parity byte differences (luma varies more than chroma); bytes are
//    re-indexed so luma lands on odd px_index like Cb Y Cr Y;
//  * VSYNC resets the active-line counter; lines with AVID are counted, the
//    first SKIP_LINES of them are dropped (in case AVID also runs in VBI).
`default_nettype none

module tvp_sync_rx #(
    parameter POL_WINDOW_LOG2 = 20,     // ~39 ms at 27 MHz: longer than one field
    parameter SKIP_LINES = 0
) (
    input  wire        clk,             // SCLK
    input  wire        rst,
    input  wire [7:0]  d,
    input  wire        hsync_in,
    input  wire        vsync_in,
    input  wire        avid_in,

    output reg         px_valid,
    output reg  [7:0]  px_data,
    output reg  [10:0] px_index,
    output reg  [9:0]  px_line,
    output reg         px_field,

    output reg         line_done,       // pulse at the end of each counted active line
    output reg  [10:0] line_bytes,      // AVID length of that line
    output reg         hs_active_high,  // detected polarities (for LEDs/debug)
    output reg         vs_active_high,
    output reg         avid_active_high,
    output reg         luma_odd         // 1: luma on odd bytes after AVID start (Cb Y Cr Y)
);
    // ---- polarity measurement ----
    reg [POL_WINDOW_LOG2-1:0] win;
    reg [POL_WINDOW_LOG2-1:0] hs_hi, vs_hi, av_hi;
    always @(posedge clk) begin
        if (rst) begin
            win <= 0; hs_hi <= 0; vs_hi <= 0; av_hi <= 0;
            hs_active_high <= 1'b0; vs_active_high <= 1'b0; avid_active_high <= 1'b1;
        end else begin
            win <= win + 1'b1;
            if (&win) begin
                // decide only on a clear majority; ambiguous windows keep the old value.
                // syncs are asserted a small fraction of the time: high < 25 % -> active high,
                // high > 75 % -> active low.
                if (hs_hi[POL_WINDOW_LOG2-1 -: 2] == 2'b00) hs_active_high <= 1'b1;
                else if (hs_hi[POL_WINDOW_LOG2-1 -: 2] == 2'b11) hs_active_high <= 1'b0;
                if (vs_hi[POL_WINDOW_LOG2-1 -: 2] == 2'b00) vs_active_high <= 1'b1;
                else if (vs_hi[POL_WINDOW_LOG2-1 -: 2] == 2'b11) vs_active_high <= 1'b0;
                // AVID is asserted most of the time (~78 % in real video):
                // high >= 62.5 % -> active high, high < 37.5 % -> active low.
                if (av_hi[POL_WINDOW_LOG2-1 -: 3] >= 3'b101) avid_active_high <= 1'b1;
                else if (av_hi[POL_WINDOW_LOG2-1 -: 3] < 3'b011) avid_active_high <= 1'b0;
                hs_hi <= 0; vs_hi <= 0; av_hi <= 0;
            end else begin
                hs_hi <= hs_hi + hsync_in;
                vs_hi <= vs_hi + vsync_in;
                av_hi <= av_hi + avid_in;
            end
        end
    end

    wire vs = vsync_in ~^ vs_active_high;   // 1 when asserted
    wire av = avid_in  ~^ avid_active_high;

    // ---- line / field bookkeeping ----
    reg        vs_d, av_d;
    reg  [9:0] line_cnt;                  // AVID lines since VSYNC
    reg  [10:0] idx;                      // byte index since AVID start
    reg  [7:0] p1, p2;                    // previous two bytes (same-parity neighbour = p2)
    reg  [27:0] e_even, e_odd;            // same-parity difference energy this field (240*720*255 < 2^28)
    always @(posedge clk) begin
        px_valid  <= 1'b0;
        line_done <= 1'b0;
        if (rst) begin
            vs_d <= 0; av_d <= 0; line_cnt <= 0; idx <= 0;
            e_even <= 0; e_odd <= 0; luma_odd <= 1'b1; px_field <= 1'b0;
        end else begin
            vs_d <= vs;
            av_d <= av;
            if (vs && !vs_d) begin                     // start of a field
                line_cnt <= 0;
                px_field <= ~px_field;
                luma_odd <= (e_odd >= e_even);
                e_even <= 0; e_odd <= 0;
            end
            if (av) begin
                if (!av_d) idx <= 11'd1; else idx <= idx + 11'd1;
                // byte position within the line (0 = first AVID byte)
                if (av_d) begin
                    if (idx >= 2) begin
                        if (idx[0]) e_odd  <= e_odd  + ((d > p2) ? d - p2 : p2 - d);
                        else        e_even <= e_even + ((d > p2) ? d - p2 : p2 - d);
                    end
                end
                p2 <= p1; p1 <= d;
                if (line_cnt >= SKIP_LINES) begin
                    px_valid <= 1'b1;
                    px_data  <= d;
                    // re-index so luma ends up on odd px_index
                    px_index <= (av_d ? idx : 11'd0) + (luma_odd ? 11'd0 : 11'd1);
                    px_line  <= line_cnt - SKIP_LINES;
                end
            end else if (av_d) begin                   // end of an AVID line
                line_done  <= (line_cnt >= SKIP_LINES);
                line_bytes <= idx;
                line_cnt   <= line_cnt + 1'b1;
            end
        end
    end
endmodule
`default_nettype wire
