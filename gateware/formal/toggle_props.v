// Formal harness for toggle_rx (rtl/cdc_sync.v): the toggle handshakes of
// fb_backend.v (line requests, pixel -> SDRAM domain; field publications and
// low-latency frame triggers, SDRAM -> pixel domain). formal/run.sh starts every
// register at 0 and gives each clock its own free input (clk2fflogic).
//
// Clocks: sclk (sender) and dclk (receiver) are free, except that at most R
// rising edges of one fall between two rising edges of the other (a further one
// may coincide with the next). R = 3 holds for any pair of 27-108 MHz against
// 74.25 MHz, both ways: 108 / 74.25 = 1.45, 74.25 / 27 = 2.75.
//
// Crossing model: a bit that the receiver samples (the toggle into the first
// synchroniser stage, the data into q) and that has changed since the
// receiver's previous edge may be read as either value: a sample taken while it
// changes, resolving either way, or skew between the bits of the data. A bit
// that has been stable for a whole receiver period is read correctly.
//
// Sender: flips tgl at most every S of its clocks and sets din with the flip.
// din may also change at any sender clock at least H clocks after the last
// flip, for instance in the clock before the next flip (fb_sdram.v sets
// pub_lines one clock before s_pub_toggle flips).
//
// Proven (assertions below):
//   count    every flip gives exactly one event_now: sent - received is 0 or 1
//   latency  a flip is received by the fourth receiver edge after it
//   data     q is the data sent with the last flip received
`default_nettype none
module toggle_props #(
    parameter S = 16, H = 16, R = 3, W = 2
) (
    input wire         sclk, dclk,
    input wire         ev,                 // the sender wants to flip (taken when allowed)
    input wire [W-1:0] nd,                 // data sent with a flip
    input wire         chg,                // the sender changes din (taken when allowed)
    input wire [W-1:0] nd2,
    input wire         t_any,              // value of an uncertain toggle sample
    input wire [W-1:0] d_any               // values of uncertain data bits
);
    // ---- clock ratio
    reg [3:0] cs, cd, cs_at_d, cd_at_s;
    always @(posedge sclk) begin cs <= cs + 1'b1; cd_at_s <= cd; end
    always @(posedge dclk) begin cd <= cd + 1'b1; cs_at_d <= cs; end
    wire [3:0] s_since_d = cs - cs_at_d, d_since_s = cd - cd_at_s;
    // no empty steps: one of the clocks changes in every step (any real timing is such a sequence)
    reg sclk_q, dclk_q;
    always @($global_clock) begin sclk_q <= sclk; dclk_q <= dclk; end
    always @* begin
        assume (s_since_d <= R);
        assume (d_since_s <= R);
        assume (sclk != sclk_q || dclk != dclk_q);
    end

    // ---- sender
    reg         tgl;
    reg [W-1:0] din, d_sent, d_prev;
    reg [5:0]   gap;                       // sender clocks since the last flip (saturates)
    reg [3:0]   n_sent;
    wire        flip = ev && gap >= S - 1;
    always @(posedge sclk) begin
        if (gap != 6'h3F) gap <= gap + 1'b1;
        if (flip) begin
            tgl <= ~tgl; din <= nd; d_prev <= d_sent; d_sent <= nd; gap <= 0; n_sent <= n_sent + 1'b1;
        end else if (chg && gap >= H - 1)
            din <= nd2;
    end

    // ---- what the receiver samples
    reg         tgl_last;
    reg [W-1:0] din_last;
    always @(posedge dclk) begin tgl_last <= tgl; din_last <= din; end
    wire         tgl_seen = (tgl != tgl_last) ? t_any : tgl;
    wire [W-1:0] din_x    = din ^ din_last;
    wire [W-1:0] din_seen = (din & ~din_x) | (d_any & din_x);

    // ---- receiver
    wire         evn;
    wire [W-1:0] q;
    wire [2:0]   t;
    toggle_rx #(.W(W)) dut (.clk(dclk), .rst(1'b0), .tgl(tgl_seen), .din(din_seen), .event_now(evn), .q(q),
                            .f_t(t));
    reg [3:0] n_recv, n_sent_d;
    reg [3:0] since;                       // receiver edges since the last flip (saturates)
    always @(posedge dclk) begin
        if (evn) n_recv <= n_recv + 1'b1;
        n_sent_d <= n_sent;
        if (n_sent != n_sent_d) since <= 4'd1;
        else if (since != 4'hF) since <= since + 1'b1;
    end

    wire [3:0] lag = n_sent - n_recv;
    wire [3:0] unseen = n_sent - n_sent_d;
    wire       seen = unseen == 0;                                // the receiver has had an edge since the flip
    always @* begin
        assert (lag <= 1);                                        // count
        if (lag == 0) assert (q == d_sent);                       // data
        if (lag == 1) assert (q == d_prev);
        if (lag == 1 && seen) assert (since <= 3);                // latency
`ifndef FORMAL_NO_STRENGTHEN
        // induction strengthening: where the flip is on its way through the stages (left out in the
        // negative controls, so that their counterexamples come from the properties above)
        assert (tgl == n_sent[0]);
        if (!seen) assert (lag == 1 && unseen == 1);
        if (lag == 0) assert (t == {3{tgl}} && tgl_last == tgl);
        if (lag == 1) begin
            assert (t[2] == !tgl && din == d_sent);
            if (!seen) assert (t[1:0] == {2{!tgl}} && tgl_last == !tgl && gap + 1 <= s_since_d);
            if (seen) begin
                assert (since >= 1 && tgl_last == tgl && din_last == din);
                assert (gap <= R * since + s_since_d);
                if (since == 1) assert (t[1] == !tgl);
                if (since >= 2) assert (t[0] == tgl);
                if (since == 3) assert (t[1] == tgl);
            end
        end
`endif
    end
endmodule
`default_nettype wire
