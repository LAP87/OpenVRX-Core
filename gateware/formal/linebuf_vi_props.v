// Formal harness for the line buffer slots of fb_display.v with VINTERP = 1 (Core #24): the
// same small picture and free inputs as linebuf_props.v, with the second read port's copy of
// the four slots covered as well. The request path prefetches one source line further ahead
// than the default build, which holds as long as the picture is scaled up at least twice:
// the harness assumes that scale contract on pub_lines and ll_lines (720p shows 240-288
// source lines, V_ACTIVE / 2 = 360; see fb_display.v's header and formal/README.md).
`default_nettype none
module linebuf_vi_props (
    input wire        clk, rst, lock, trig, h_alt,
    input wire        pub_toggle,
    input wire [9:0]  pub_lines,
    input wire        frame_low,
    input wire        ll,
    input wire [9:0]  ll_lines,
    input wire        ll_alive, ll_low,
    input wire [31:0] lb_rdata,
    input wire [31:0] lb_rdata_b
);
    wire [11:0] x, y;
    wire de, hs, vs, fs;
    genlock_timing #(.H_ACTIVE(4), .H_FP(1), .H_SYNC(1), .H_BP(1), .H_FP_ALT(3),
                     .V_ACTIVE(4), .V_FP(1), .V_SYNC(1), .V_BP(2), .MAX_WAIT(3), .JUMP_AFTER(2), .HOLD(2)) timing (
        .clk(clk), .rst(rst), .lock(lock), .trig(trig), .h_alt(h_alt),
        .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs));
    wire        fetch_toggle, fetch_first;
    wire [9:0]  fetch_line;
    wire [1:0]  fetch_slot;
    wire [12:0] lb_raddr;
    wire [10:0] lb_raddr_b;
    wire [7:0]  r, g, b, yo, cbo, cro;
    wire        de_o, hs_o, vs_o, have_video;
    fb_display #(.V_TOTAL(8), .V_ACTIVE(4), .H_WIN0(0), .H_WIN(4), .VINTERP(1)) dut (
        .clk(clk), .rst(rst), .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs),
        .pub_toggle(pub_toggle), .pub_lines(pub_lines), .frame_low(frame_low),
        .fetch_toggle(fetch_toggle), .fetch_line(fetch_line), .fetch_slot(fetch_slot), .fetch_first(fetch_first),
        .ll(ll), .ll_lines(ll_lines), .ll_alive(ll_alive), .ll_triggered(1'b0), .ll_low(ll_low),
        .lb_raddr(lb_raddr), .lb_rdata(lb_rdata),
        .lb_raddr_b(lb_raddr_b), .lb_rdata_b(lb_rdata_b),
        .r(r), .g(g), .b(b), .yo(yo), .cbo(cbo), .cro(cro), .de_o(de_o), .hs_o(hs_o), .vs_o(vs_o),
        .have_video(have_video));

`ifdef FORMAL
    // the request path's scale contract (fb_display.v: one request per output line as long as
    // the source is scaled up at least twice); V_ACTIVE = 4 here, so at most 2 source lines.
    // The sender side of the publication crossing (fb_sdram.v changes pub_lines at most once
    // per flip of pub_toggle, never between flips) is assumed here, as the default harness
    // leaves the senders to formal/README.md item 2; without it the synchroniser can sample a
    // mid-change pub_lines and the contract says nothing about torn values.
    reg        f_pub_t_q;
    reg [9:0]  f_pub_d_q;
    reg        f_ll_q;
    reg        f_in_frame;
    always @(posedge clk) begin
        f_pub_t_q <= pub_toggle;
        f_pub_d_q <= pub_lines;
        f_ll_q <= ll;
        // a frame region: from its first request (the last blanking line) to the end of the last
        // active line; ll is held over it (a real switch blanks the rest of the frame, and the
        // display's requests are then irrelevant: have_video is low)
        if (y == 12'd7 && x == 12'd0) f_in_frame <= 1'b1;
        else if (y == 12'd0 && x == 12'd6) f_in_frame <= 1'b0;
    end
    always @* begin
        assume (pub_lines <= 10'd2);
        assume (ll_lines <= 10'd2);
        if (pub_toggle == f_pub_t_q) assume (pub_lines == f_pub_d_q);
        if (f_in_frame) assume (ll == f_ll_q);
    end
`endif
endmodule
`default_nettype wire
