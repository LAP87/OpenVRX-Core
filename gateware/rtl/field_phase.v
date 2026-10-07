// Which field of an interlaced picture a field is, from arrival times alone.
// The F bit is not used: a TVP5150AM1 holds it at 1 when it takes the signal
// for non-interlaced (SLES209E 3.21.20), and two decoders can disagree.
//
// `at_ref` marks the same line of every field (in the field's own numbering).
// The fields of a 525- or 625-line picture arrive alternately one line period
// further apart and one closer (263/262 or 313/312 lines). The field after the
// longer interval was scanned half a line later, so its lines lie half a
// source line lower: `low`. The field after the shorter interval is `early`
// by half the difference; a genlocked output delays that frame start by `dly`
// cycles (smoothed) to get frames of equal length.
//
// Intervals within T_EQ of each other: not interlaced, low = 0.
// Intervals that differ by 2 T_EQ .. T_MAX: interlaced.
// Anything else (a field without its reference line, noise): no measurement;
// the pattern seen last continues (`nf`, the start of a field, predicts).
`default_nettype none
module field_phase #(
    parameter W     = 21,                 // interval counter width (saturates; fields are about 1.1-1.3 M cycles)
    parameter T_EQ  = 1024,               // cycles
    parameter T_MAX = 6144                // more than one line period (4118-4147 cycles at 64.8 MHz) and a half
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        nf,                // a field starts
    input  wire        at_ref,            // its reference line has arrived
    output reg         low,               // the field that is arriving is the lower one
    output wire        low_now,           // valid with at_ref: `low` as it will be after this edge
    output reg         il,                // the source is interlaced
    output wire        early,             // valid with at_ref: this field came after the shorter interval
    output wire [11:0] dly                // valid with at_ref: half the difference between the intervals
);
    reg  [W-1:0] cnt, d2;
    reg          have_d2;
    reg  [11:0]  dly_s;
    wire         sat    = &cnt;
    wire         longer = cnt > d2;
    wire [W-1:0] diff   = longer ? cnt - d2 : d2 - cnt;
    wire         usable = have_d2 && !sat;
    wire         equal  = usable && (diff < T_EQ);
    wire         step   = usable && (diff > 2 * T_EQ) && (diff < T_MAX);
    wire [11:0]  half   = diff[12:1];
    assign low_now = equal ? 1'b0 : step ? longer : low;
    assign early = equal ? 1'b0 : step ? !longer : (il && !low);
    assign dly   = (step && !il) ? half : dly_s;

    always @(posedge clk) begin
        if (!sat) cnt <= cnt + 1'b1;
        if (nf) low <= il ? !low : 1'b0;
        if (at_ref) begin
            cnt <= 0; d2 <= cnt; have_d2 <= !sat;
            if (equal) begin il <= 1'b0; low <= 1'b0; end
            else if (step) begin
                il <= 1'b1; low <= longer;
                dly_s <= il ? dly_s - (dly_s >> 2) + (half >> 2) : half;
            end
        end
        // cnt starts saturated: the time from reset to the first reference line is not an
        // interval between two fields, and must not count as one (model/fb_ref.py FieldPhase)
        if (rst) begin cnt <= {W{1'b1}}; d2 <= 0; have_d2 <= 1'b0; low <= 1'b0; il <= 1'b0; dly_s <= 0; end
    end
endmodule
`default_nettype wire
