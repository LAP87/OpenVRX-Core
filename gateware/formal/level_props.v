// Formal harness for sync2 (rtl/cdc_sync.v) as fb_backend.v uses it for ll_mode:
// one mode bit from a third clock domain (the menu's), synchronised into the
// SDRAM domain (sclk) and the pixel domain (dclk). formal/run.sh starts every
// register at 0 and gives each clock its own free input (clk2fflogic).
//
// The mode changes at an mclk edge, at the earliest when both domains have had
// K edges since the last change (a person pressing a button is far slower).
// Crossing model as in toggle_props.v: a sample of the mode taken at the first
// edge after it changed may resolve either way, independently in each domain.
//
// Proven (assertions below):
//   edge     each domain's view changes only at a rising edge of its own clock
//   settle   from the third edge of its clock after a change, a domain's view
//            equals the mode
//   agree    the two views differ only while one of the domains has had fewer
//            than three edges since the change
`default_nettype none
module level_props #(
    parameter K = 4,
    parameter SETTLE = 3                   // edges after a change by which a view must equal the mode
) (
    input wire mclk, sclk, dclk,
    input wire chg,                        // change the mode (taken when allowed)
    input wire s_any, d_any                // values of uncertain samples
);
    reg       m, m_s, m_d;                 // the mode; the mode at the last sclk / dclk edge
    reg [2:0] es, ed;                      // sclk / dclk edges since the mode last changed (saturate)
    always @(posedge mclk) if (chg && m == m_s && m == m_d && es >= K && ed >= K) m <= ~m;
    always @(posedge sclk) begin
        m_s <= m;
        if (m != m_s) es <= 3'd1; else if (es != 3'd7) es <= es + 1'b1;
    end
    always @(posedge dclk) begin
        m_d <= m;
        if (m != m_d) ed <= 3'd1; else if (ed != 3'd7) ed <= ed + 1'b1;
    end

    wire qs, qd;
    sync2 dut_s (.clk(sclk), .d((m != m_s) ? s_any : m), .q(qs));
    sync2 dut_d (.clk(dclk), .d((m != m_d) ? d_any : m), .q(qd));

    reg sclk_q, dclk_q, qs_q, qd_q;
    always @($global_clock) begin sclk_q <= sclk; dclk_q <= dclk; qs_q <= qs; qd_q <= qd; end
    wire s_rise = sclk && !sclk_q, d_rise = dclk && !dclk_q;
    wire s_new = m != m_s || es < SETTLE, d_new = m != m_d || ed < SETTLE;   // shortly after a change
    // no empty steps: sclk or dclk changes in every step; a change of the mode in between lands in
    // the step of the next one (any real timing is such a sequence)
    always @* assume (sclk != sclk_q || dclk != dclk_q);
    always @* begin
        if (!s_rise) assert (qs == qs_q);                         // edge
        if (!d_rise) assert (qd == qd_q);
        if (!s_new) assert (qs == m);                             // settle
        if (!d_new) assert (qd == m);
        if (qs != qd) assert (s_new || d_new);                    // agree
    end
endmodule
`default_nettype wire
