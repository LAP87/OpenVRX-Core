// Display side of the SDRAM field store (pixel clock domain).
//
// * Asks for source lines; which field buffer they come from is decided in the
//   SDRAM domain at the first request of each frame (fb_sdram.v).
// * Maps the output lines onto the field's line count (240, 243, 288 ... all
//   work) and prefetches the source line of the next output line into a
//   4-slot line buffer one output line ahead. Output line j shows source line
//   floor((j + 1/2) * lines / V_ACTIVE - 1/4), or - 3/4 for the lower field of
//   an interlaced pair (BOB = 1): the two fields are drawn half a source line
//   apart, as they were scanned.
// * VINTERP = 1 (buffer mode only; default 0): instead of the nearest source
//   line, output line j blends source lines s and s + 1 around that position,
//   weighted in eighths (vblend.v), s + 1 clamped to the last line. The second
//   line is read from a copy of the four line-buffer slots (lb_raddr_b, written
//   by fb_backend.v together with the first), and the prefetch runs one source
//   line further ahead: for output line j + 1, line s(j + 1) + 1 is asked for.
//   That is one request per output line as long as the picture is scaled up
//   at least twice (source lines <= V_ACTIVE / 2: 288 into 720 is 2.5 times).
//   Low-latency mode keeps the nearest line: the next source line may not
//   have arrived yet.
// * Reads the line buffer: 4:3 window of H_WIN pixels from x = H_WIN0; source
//   pixel = (x - H_WIN0) * 3 / 4 (720p: 960-px window) or / 2 (H_HALF = 1,
//   1080p: 1440-px window), chroma shared by pixel pairs. Outputs BT.601 -> RGB
//   (for DVI) and the same pixels as YCbCr (for a BT.1120 transmitter).
//
// Low-latency mode (ll = 1, see fb_backend.v): the field's line count comes
// from the ring writer (ll_lines), and the line buffer is read as a 16-line
// ring (slot = source line mod 16) instead of the 4 prefetch slots.
//
// A frame has video (have_video, decided at its first line) when: in buffer
// mode, a field has been published since the last switch to low latency and
// within the last 0.2 s; in low-latency mode, a trigger has come in this
// low-latency period within the last 0.1 s (ll_alive) and this frame was
// started by a trigger (ll_triggered, from genlock_timing.v): a frame on the
// free-running timing would read ring slots the writer has not reached. A
// mode switch blanks the rest of the running frame.
//
// CDC: publications arrive as a toggle + stable data, fetch requests leave
// the same way (data is held stable for far longer than the synchronisers
// need). frame_low changes at the first request of a frame and is read one
// output line later.
`default_nettype none
module fb_display #(
    parameter V_TOTAL = 750, V_ACTIVE = 720,     // 720p60; smaller values in simulation
    parameter H_WIN0 = 160, H_WIN = 960, H_HALF = 0,
    parameter BOB = 1,
    parameter VINTERP = 0
) (
    input  wire        clk,             // pixel clock
    input  wire        rst,
    // from the timing generator
    input  wire [11:0] x, y,
    input  wire        de, hsync, vsync,
    // from the SDRAM domain
    input  wire        pub_toggle,      // a field was published
    input  wire [9:0]  pub_lines,       // line count to scale by
    input  wire        frame_low,       // the field of this frame is the lower one
    // to the SDRAM domain
    output reg         fetch_toggle,
    output reg  [9:0]  fetch_line,
    output reg  [1:0]  fetch_slot,
    output reg         fetch_first,     // first request of a frame
    // low-latency mode (pixel clock domain)
    input  wire        ll,
    input  wire [9:0]  ll_lines,
    input  wire        ll_alive,
    input  wire        ll_triggered,    // the running frame was started by a trigger (genlock_timing.v)
    input  wire        ll_low,
    // line buffer read port
    output reg  [12:0] lb_raddr,
    input  wire [31:0] lb_rdata,
    output reg  [10:0] lb_raddr_b,      // VINTERP: the second line, in the copy of the 4 slots
    input  wire [31:0] lb_rdata_b,
    // video out (5 cycles behind x/y)
    output wire [7:0]  r, g, b,
    output reg  [7:0]  yo, cbo, cro,    // same timing as r/g/b; limited-range blank levels
    output reg         de_o, hs_o, vs_o,
    output reg         have_video
);
    localparam [9:0] DEFAULT_LINES = V_ACTIVE / 3;

    // ---- publications ----
    // crossings: cdc_sync.v (proven in formal/toggle_props.v and formal/level_props.v)
    wire       pub_ev, fl_q, lw_q;          // lw_q, fl_q: frame_low, ll_low synchronised
    wire [9:0] latest_lines;
    toggle_rx #(.W(10)) pub_rx (.clk(clk), .rst(rst), .tgl(pub_toggle), .din(pub_lines),
        .event_now(pub_ev), .q(latest_lines));
    sync2 fl_sync (.clk(clk), .d(frame_low), .q(fl_q));
    sync2 lw_sync (.clk(clk), .d(ll_low), .q(lw_q));
    reg       have_pub;
    reg [23:0] since_pub;               // frames are 16.7 ms; ~0.2 s without a field -> no video
    always @(posedge clk) begin
        if (pub_ev) begin
            have_pub <= 1'b1; since_pub <= 0;
        end else if (since_pub != {24{1'b1}}) since_pub <= since_pub + 1'b1;
        if (since_pub[23]) have_pub <= 1'b0;
        // In low-latency mode the field store is held in reset and its buffers go stale. Forget the
        // fields published before, so that the first frames after a switch back to the buffer are
        // blank until a field has been published again (the same as the first frame after a switch
        // to low latency), instead of showing whatever buffer 0 held before.
        if (ll) have_pub <= 1'b0;
        if (rst) begin have_pub <= 1'b0; since_pub <= 0; end
    end

    // ---- frame start: line count of the field to show ----
    reg [9:0] lines;                    // source lines the picture is scaled from
    wire line_start = (x == 0);
    wire frame_start = line_start && (y == V_TOTAL - 1);   // during the last blanking line
    always @(posedge clk) if (rst) begin
        lines <= DEFAULT_LINES;
    end else if (frame_start) begin
        lines <= ll ? ((ll_lines == 0) ? DEFAULT_LINES : ll_lines) : ((latest_lines == 0) ? DEFAULT_LINES : latest_lines);
    end

    // ---- video or blank: decided at the frame's first line, when the timing generator has
    // settled whether the frame was started by a trigger (the pixels are 5 clocks behind x/y)
    reg ll_d;
    always @(posedge clk) begin
        ll_d <= ll;
        // low latency: only a frame a trigger started has video (the ring then holds the field from
        // its line 0). A frame that waited a trigger out is blank: while the genlock ignores early
        // triggers after a source moved, that is up to three blank frames rather than torn ones.
        if (line_start && y == 0) have_video <= ll ? (ll_alive && ll_triggered) : have_pub;
        if (ll != ll_d) have_video <= 1'b0;             // a mode switch: the rest of this frame is blank
        if (rst) begin have_video <= 1'b0; ll_d <= 1'b0; end
    end

    // ---- output line -> source line, one line ahead ----
    // acc holds (2j + 1) * 2 * lines + (4 - k) * V_ACTIVE modulo 4 * V_ACTIVE for output line j,
    // k = 1 or 3 quarter lines of offset. The source line goes up at every wrap except the first.
    localparam AW = $clog2(8 * V_ACTIVE);
    localparam [AW-1:0] V4 = 4 * V_ACTIVE;
    reg [9:0]     src_next, src_cur;
    reg [AW-1:0]  acc;
    reg           started, low_r;
    // VINTERP: weight of line src + 1 in eighths, rounded: the number of thresholds
    // (2i + 1) * V_ACTIVE / 4 that acc (the position within the line, in 1 / (4 * V_ACTIVE)) reaches
    function [3:0] eighths(input [AW-1:0] a);
        integer i;
        begin
            eighths = 4'd0;
            for (i = 0; i < 8; i = i + 1)
                if (a >= ((2 * i + 1) * V_ACTIVE) / 4) eighths = eighths + 4'd1;
        end
    endfunction
    reg [3:0]     w_next, w_cur;          // weight for the next / this output line (0 without VINTERP)
    reg [9:0]     src_b_cur;              // the second line of this output line
    reg [9:0]     req_hi;                 // highest source line asked for in this frame
    wire [AW-1:0] base = {lines, 1'b0} + (low_r ? V_ACTIVE : 3 * V_ACTIVE);
    wire [AW-1:0] step = acc + {lines, 2'b00};
    // the line output line y + 1 starts from, as the block below sets src_next at x = 2
    wire [9:0]    src_hi = (step >= V4 && started && src_next + 1 < lines) ? src_next + 1'b1 : src_next;
    always @(posedge clk) if (rst) begin
        fetch_toggle <= 1'b0; fetch_first <= 1'b0; src_next <= 0; src_cur <= 0; acc <= 0; started <= 1'b0; low_r <= 1'b0;
        w_next <= 4'd0; w_cur <= 4'd0; src_b_cur <= 0; req_hi <= 0;
    end else begin
        if (line_start && y == V_TOTAL - 1) begin               // ask for line 0; that starts the frame
            src_next <= 0; src_cur <= 0; req_hi <= 0;
            fetch_line <= 0; fetch_slot <= 0; fetch_first <= 1'b1;
            fetch_toggle <= ~fetch_toggle;
        end
        if (line_start && y < V_ACTIVE) begin
            src_cur   <= src_next;
            src_b_cur <= (src_next + 1 < lines) ? src_next + 1'b1 : src_next;
            w_cur     <= w_next;
        end
        if (line_start && y == 0) low_r <= (BOB != 0) && (ll ? lw_q : fl_q);
        if (x == 1 && y == 0) begin                             // output line 0
            started <= base >= V4;
            acc     <= (base >= V4) ? base - V4 : base;
            w_cur   <= (VINTERP != 0 && !ll && base >= V4) ? eighths(base - V4) : 4'd0;
        end
        if (x == 2 && y < V_ACTIVE - 1) begin                   // source line for output line y + 1
            w_next <= 4'd0;
            if (step >= V4) begin
                acc <= step - V4;
                started <= 1'b1;
                if (VINTERP != 0 && !ll) w_next <= eighths(step - V4);
                if (started && src_next + 1 < lines) begin
                    src_next   <= src_next + 1'b1;
                    if (VINTERP == 0 || ll) begin
                        fetch_line <= src_next + 1'b1;
                        fetch_slot <= src_next[1:0] + 2'd1;
                        fetch_first <= 1'b0;
                        fetch_toggle <= ~fetch_toggle;
                    end
                end
            end else begin
                acc <= step;
                if (VINTERP != 0 && !ll && started) w_next <= eighths(step);
            end
            // VINTERP: ask for the line after the one output line y + 1 starts from, once
            if (VINTERP != 0 && !ll && src_hi + 1 < lines && src_hi + 1 > req_hi) begin
                req_hi       <= src_hi + 1'b1;
                fetch_line   <= src_hi + 1'b1;
                fetch_slot   <= src_hi[1:0] + 2'd1;
                fetch_first  <= 1'b0;
                fetch_toggle <= ~fetch_toggle;
            end
        end
    end

    // ---- pixel pipeline ----
    // stage 0: address. source x = xr * 3/4 (or xr / 2)
    wire        in43 = (x >= H_WIN0) && (x < H_WIN0 + H_WIN);
    wire [11:0] xr   = x - H_WIN0;
    wire [13:0] xr3  = {xr, 1'b0} + xr;
    wire [9:0]  sx   = H_HALF ? xr[10:1] : xr3[11:2];   // 0..719
    reg  [3:0]  in_p, de_p, hs_p, vs_p;
    reg  [3:0]  odd_p;
    always @(posedge clk) begin
        lb_raddr <= {ll ? src_cur[3:2] : 2'b00, src_cur[1:0], sx[9:1]};
        lb_raddr_b <= {src_b_cur[1:0], sx[9:1]};
        in_p  <= {in_p[2:0],  in43};
        de_p  <= {de_p[2:0],  de};
        hs_p  <= {hs_p[2:0],  hsync};
        vs_p  <= {vs_p[2:0],  vsync};
        odd_p <= {odd_p[2:0], sx[0]};
    end
    // stage 1: RAM read (lb_rdata valid after the 2nd edge). stage 2: pick Y
    reg [7:0] yy, cb, cr;
    wire [7:0] y_a = odd_p[1] ? lb_rdata[31:24] : lb_rdata[15:8];
    wire [7:0] y_b = odd_p[1] ? lb_rdata_b[31:24] : lb_rdata_b[15:8];
    wire [7:0] y_v, cb_v, cr_v;
    wire [3:0] w_px = (VINTERP != 0) ? w_cur : 4'd0;     // w_cur stays 0 in low-latency mode
    vblend vb_y  (.a(y_a),             .b(y_b),               .w(w_px), .y(y_v));
    vblend vb_cb (.a(lb_rdata[7:0]),   .b(lb_rdata_b[7:0]),   .w(w_px), .y(cb_v));
    vblend vb_cr (.a(lb_rdata[23:16]), .b(lb_rdata_b[23:16]), .w(w_px), .y(cr_v));
    always @(posedge clk) begin
        yy <= y_v;
        cb <= cb_v;
        cr <= cr_v;
    end
    wire [7:0] r0, g0, b0;
    ycbcr2rgb conv (.clk(clk), .y(yy), .cb(cb), .cr(cr), .r(r0), .g(g0), .b(b0));
    // stages 3..4 in ycbcr2rgb; blank outside the window or without video
    reg [7:0] rr, gg, bb;
    reg [1:0] in_q, de_q, hs_q, vs_q;
    reg [7:0] y1, cb1, cr1, y2, cb2, cr2;      // YCbCr delayed like ycbcr2rgb's two stages
    always @(posedge clk) begin
        {y1, cb1, cr1} <= {yy, cb, cr};
        {y2, cb2, cr2} <= {y1, cb1, cr1};
        if (in_q[0] && have_video) {yo, cbo, cro} <= {y2, cb2, cr2};
        else if (in_q[0])          {yo, cbo, cro} <= 24'h2D8080;    // dark grey, as in RGB
        else                       {yo, cbo, cro} <= 24'h108080;    // black
        in_q <= {in_q[0], in_p[3]}; de_q <= {de_q[0], de_p[3]}; hs_q <= {hs_q[0], hs_p[3]}; vs_q <= {vs_q[0], vs_p[3]};
        de_o <= de_q[0]; hs_o <= hs_q[0]; vs_o <= vs_q[0];
        if (in_q[0] && have_video) {rr, gg, bb} <= {r0, g0, b0};
        else if (in_q[0])          {rr, gg, bb} <= 24'h202020;      // no signal: dark grey window
        else                       {rr, gg, bb} <= 24'h000000;
    end
    assign {r, g, b} = {rr, gg, bb};

`ifdef FORMAL
    // Proven by formal/run.sh (formal/linebuf_props.v: genlock_timing + fb_display in a small
    // picture, all other inputs free): a line requested during an active output line goes to a
    // line buffer slot that the display does not read for the rest of that line; the first
    // request of a frame (slot 0, which the display then reads) is made on a blanking line.
    // That the SDRAM side has written the slot before the next line start is a matter of
    // SDRAM latency and is not part of the proof (gateware/formal/README.md).
    reg        f_t_q, f_rst_q, f_pend;
    reg [1:0]  f_slot;
    reg [11:0] f_y;                                             // the line in which the request was made
    wire       f_req = fetch_toggle != f_t_q && !f_rst_q;       // a request was made in the last clock
    always @(posedge clk) begin
        f_t_q <= fetch_toggle; f_rst_q <= rst; f_y <= y;
        if (line_start || rst) f_pend <= 1'b0;
        else if (f_req && !fetch_first) begin f_pend <= 1'b1; f_slot <= fetch_slot; end
    end
    wire [9:0] f_ahead = src_next - src_cur;
    always @* begin
        if (f_req && !fetch_first) assert (f_y < V_ACTIVE - 1 && fetch_slot != src_cur[1:0]);
        if (f_req && fetch_first) assert (f_y >= V_ACTIVE);
        if (f_pend) assert (f_slot != src_cur[1:0] && f_slot == fetch_slot);
`ifndef FORMAL_NO_STRENGTHEN
        // induction strengthening: the next line is at most one ahead of the line read, and level
        // with it from the start of an active line until its request
        assert (f_ahead <= 1);
        if (y < V_ACTIVE && (x == 1 || x == 2)) assert (f_ahead == 0);
        if (f_pend || (f_req && !fetch_first)) assert (f_ahead == 1 && fetch_slot == src_next[1:0]);
`endif
    end
`endif
endmodule
`default_nettype wire
