// Formal harness for toggle_tx (rtl/cdc_sync.v), the send side of the
// low-latency frame trigger in fb_backend.v. One clock; reset, requests and
// data free every clock; registers start at 0. Proven:
//   spacing  tgl flips at least GAP clocks after the previous flip
//   hold     q changes only when tgl flips
//   data     a flip carries the data of the latest request
//   served   a request is sent at the next clock or waits (pend), and nothing
//            waits longer than GAP clocks
// With GAP = 16 these are the sender conditions of formal/toggle_props.v
// (flips at least 16 sender clocks apart, data held 16 sender clocks), so
// the low-latency trigger meets what toggle_rx is proven under.
`default_nettype none
module toggle_tx_props #(
    parameter GAP = 16, W = 2
) (
    input wire         clk, rst, req,
    input wire [W-1:0] din
);
    wire         tgl, pend;
    wire [W-1:0] q;
    toggle_tx #(.W(W), .GAP(GAP)) dut (.clk(clk), .rst(rst), .req(req), .din(din), .tgl(tgl), .q(q), .f_pend(pend));

    reg         tgl_q, rst_q, req_q;
    reg [W-1:0] q_q, want;
    reg [5:0]   gap, pend_n;               // clocks since the last flip; clocks a request has waited
    wire        flip = tgl != tgl_q && !rst_q;
    always @(posedge clk) begin
        tgl_q <= tgl; q_q <= q; rst_q <= rst; req_q <= req;
        if (req) want <= din;
        if (flip) gap <= 6'd1; else if (gap != 6'h3F) gap <= gap + 1'b1;
        if (rst) gap <= 6'h3F;
        pend_n <= pend ? pend_n + 1'b1 : 6'd0;
    end
    always @* begin
        if (flip) assert (gap >= GAP);                                // spacing
        if (q != q_q && !rst_q) assert (flip);                        // hold
        if (flip) assert (q == want);                                 // data
        if (req_q && !rst_q) assert (flip || pend);                   // served
        assert (pend_n <= GAP);
    end
endmodule
`default_nettype wire
