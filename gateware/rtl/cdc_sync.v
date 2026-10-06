// Clock domain crossings used by fb_backend.v and fb_display.v, as modules so
// that formal/run.sh can prove them (formal/toggle_props.v, formal/level_props.v).
//
// toggle_rx: receive side of a toggle handshake. The sender flips `tgl` once per
// event and holds `din` from that flip until the receiver has taken it. The
// toggle passes two synchroniser stages; `event_now` is high for one cycle per
// flip, two or three clocks after it, and `q` takes `din` at the end of that
// cycle. Proven: no event lost or doubled, and `q` is the data of the event,
// when the sender flips at most every S_MIN of its clocks and holds `din` for
// H_MIN of its clocks (see formal/toggle_props.v for the numbers and the clock
// ratios they hold for).
//
// sync2: two-stage synchroniser for a slow level (a mode bit).
`default_nettype none
module toggle_rx #(
    parameter W = 1,
    parameter RESET_Q = 1                  // 0: q has no reset (it is only read after an event)
) (
    input  wire         clk,
    input  wire         rst,
    input  wire         tgl,               // other clock domain
    input  wire [W-1:0] din,               // other clock domain, stable around each flip of tgl
    output wire         event_now,
    output reg  [W-1:0] q
`ifdef FORMAL
    , output wire [2:0] f_t                // the synchroniser stages, for the proof's invariants
`endif
);
    reg [2:0] t;
    always @(posedge clk) t <= {t[1:0], tgl};
    assign event_now = t[2] != t[1];
`ifdef FORMAL
    assign f_t = t;
`endif
    always @(posedge clk) begin
        if (event_now) q <= din;
        if (rst && RESET_Q != 0) q <= {W{1'b0}};
    end
endmodule

module sync2 (
    input  wire clk,
    input  wire d,                         // other clock domain
    output wire q
);
    reg [1:0] s;
    always @(posedge clk) s <= {s[0], d};
    assign q = s[1];
endmodule
`default_nettype wire
