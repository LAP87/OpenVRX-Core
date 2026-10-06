// Formal harness for the line buffer slots of fb_display.v (properties in its
// `ifdef FORMAL block): the real timing generator in a small picture (as in
// genlock_props.v, 8 lines of which 4 active, 7-9 clocks per line) drives
// fb_display; lock/trig/h_alt, publications, low-latency inputs and RAM data are
// free every clock. Registers start at 0. formal/run.sh turns genlock_timing's
// own assertions into assumptions here (they are proven on their own, for all
// inputs) and reads formal/ycbcr2rgb_stub.v instead of the colour converter,
// which plays no part in which slot is read.
`default_nettype none
module linebuf_props (
    input wire        clk, rst, lock, trig, h_alt,
    input wire        pub_toggle,
    input wire [9:0]  pub_lines,
    input wire        frame_low,
    input wire        ll,
    input wire [9:0]  ll_lines,
    input wire        ll_alive, ll_low,
    input wire [31:0] lb_rdata
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
    wire [7:0]  r, g, b, yo, cbo, cro;
    wire        de_o, hs_o, vs_o, have_video;
    fb_display #(.V_TOTAL(8), .V_ACTIVE(4), .H_WIN0(0), .H_WIN(4)) dut (
        .clk(clk), .rst(rst), .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs),
        .pub_toggle(pub_toggle), .pub_lines(pub_lines), .frame_low(frame_low),
        .fetch_toggle(fetch_toggle), .fetch_line(fetch_line), .fetch_slot(fetch_slot), .fetch_first(fetch_first),
        .ll(ll), .ll_lines(ll_lines), .ll_alive(ll_alive), .ll_low(ll_low),
        .lb_raddr(lb_raddr), .lb_rdata(lb_rdata),
        .r(r), .g(g), .b(b), .yo(yo), .cbo(cbo), .cro(cro), .de_o(de_o), .hs_o(hs_o), .vs_o(vs_o),
        .have_video(have_video));
endmodule
`default_nettype wire
