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
// toggle_tx: send side for a sender that cannot itself promise toggle_rx's
// spacing and hold (the low-latency frame trigger: a field may end right after
// its trigger). `req` asks for an event carrying `din`. tgl flips at most every
// GAP clocks, and `q` takes the data when tgl flips and holds it until the next
// flip. A request less than GAP clocks after the last flip waits and is sent
// GAP clocks after it; a further request in that time replaces its data, so
// two events merge into one. Proven in formal/toggle_tx_props.v; with GAP = 16
// it meets the sender conditions of formal/toggle_props.v.
//
// sync2: two-stage synchroniser for a slow level (a mode bit).
`default_nettype none
module toggle_tx #(
    parameter W = 1,
    parameter GAP = 16
) (
    input  wire         clk,
    input  wire         rst,
    input  wire         req,
    input  wire [W-1:0] din,
    output reg          tgl,
    output reg  [W-1:0] q
`ifdef FORMAL
    , output wire       f_pend             // a request is waiting, for the proof
`endif
);
    localparam CW = $clog2(GAP + 1);
    reg [CW-1:0] since;                    // clocks since the last flip, saturates at GAP - 1
    reg          pend;
    reg [W-1:0]  pdata;
    wire         ready = since == GAP - 1;
    always @(posedge clk) begin
        if (!ready) since <= since + 1'b1;
        if (req && !ready) begin pend <= 1'b1; pdata <= din; end
        if ((req || pend) && ready) begin
            tgl <= ~tgl; q <= req ? din : pdata; since <= 0; pend <= 1'b0;
        end
        if (rst) begin tgl <= 1'b0; q <= {W{1'b0}}; since <= GAP - 1; pend <= 1'b0; end
    end
`ifdef FORMAL
    assign f_pend = pend;
`endif
endmodule

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
