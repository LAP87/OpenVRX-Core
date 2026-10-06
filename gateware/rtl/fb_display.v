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
// * Reads the line buffer: 4:3 window of H_WIN pixels from x = H_WIN0; source
//   pixel = (x - H_WIN0) * 3 / 4 (720p: 960-px window) or / 2 (H_HALF = 1,
//   1080p: 1440-px window), chroma shared by pixel pairs. Outputs BT.601 -> RGB
//   (for DVI) and the same pixels as YCbCr (for a BT.1120 transmitter).
//
// Low-latency mode (ll = 1, see fb_backend.v): the field's line count comes
// from the ring writer (ll_lines), video is shown while fields keep coming
// (ll_alive), and the line buffer is read as a 16-line ring (slot = source
// line mod 16) instead of the 4 prefetch slots.
//
// CDC: publications arrive as a toggle + stable data, fetch requests leave
// the same way (data is held stable for far longer than the synchronisers
// need). frame_low changes at the first request of a frame and is read one
// output line later.
`default_nettype none
module fb_display #(
    parameter V_TOTAL = 750, V_ACTIVE = 720,     // 720p60; smaller values in simulation
    parameter H_WIN0 = 160, H_WIN = 960, H_HALF = 0,
    parameter BOB = 1
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
    input  wire        ll_low,
    // line buffer read port
    output reg  [12:0] lb_raddr,
    input  wire [31:0] lb_rdata,
    // video out (5 cycles behind x/y)
    output wire [7:0]  r, g, b,
    output reg  [7:0]  yo, cbo, cro,    // same timing as r/g/b; limited-range blank levels
    output reg         de_o, hs_o, vs_o,
    output reg         have_video
);
    // ---- publications ----
    reg [2:0] pt;
    reg [9:0] latest_lines;
    reg       have_pub;
    reg [23:0] since_pub;               // frames are 16.7 ms; ~0.2 s without a field -> no video
    reg [1:0] fl_s, lw_s;               // frame_low, ll_low synchronised
    always @(posedge clk) begin
        pt <= {pt[1:0], pub_toggle};
        fl_s <= {fl_s[0], frame_low};
        lw_s <= {lw_s[0], ll_low};
        if (pt[2] != pt[1]) begin
            latest_lines <= pub_lines; have_pub <= 1'b1; since_pub <= 0;
        end else if (since_pub != {24{1'b1}}) since_pub <= since_pub + 1'b1;
        if (since_pub[23]) have_pub <= 1'b0;
        // In low-latency mode the field store is held in reset and its buffers go stale. Forget the
        // fields published before, so that the first frames after a switch back to the buffer are
        // blank until a field has been published again (the same as the first frame after a switch
        // to low latency), instead of showing whatever buffer 0 held before.
        if (ll) have_pub <= 1'b0;
        if (rst) begin have_pub <= 1'b0; since_pub <= 0; latest_lines <= 0; end
    end

    // ---- frame start: line count of the field to show ----
    reg [9:0] lines;                    // source lines the picture is scaled from
    wire line_start = (x == 0);
    wire frame_start = line_start && (y == V_TOTAL - 1);   // during the last blanking line
    always @(posedge clk) if (rst) begin
        lines <= 10'd240; have_video <= 1'b0;
    end else if (frame_start) begin
        if (ll) begin
            lines      <= (ll_lines == 0) ? 10'd240 : ll_lines;
            have_video <= ll_alive;
        end else begin
            lines      <= (latest_lines == 0) ? 10'd240 : latest_lines;
            have_video <= have_pub;
        end
    end

    // ---- output line -> source line, one line ahead ----
    // acc holds (2j + 1) * 2 * lines + (4 - k) * V_ACTIVE modulo 4 * V_ACTIVE for output line j,
    // k = 1 or 3 quarter lines of offset. The source line goes up at every wrap except the first.
    localparam AW = $clog2(8 * V_ACTIVE);
    localparam [AW-1:0] V4 = 4 * V_ACTIVE;
    reg [9:0]     src_next, src_cur;
    reg [AW-1:0]  acc;
    reg           started, low_r;
    wire [AW-1:0] base = {lines, 1'b0} + (low_r ? V_ACTIVE : 3 * V_ACTIVE);
    wire [AW-1:0] step = acc + {lines, 2'b00};
    always @(posedge clk) if (rst) begin
        fetch_toggle <= 1'b0; fetch_first <= 1'b0; src_next <= 0; src_cur <= 0; acc <= 0; started <= 1'b0; low_r <= 1'b0;
    end else begin
        if (line_start && y == V_TOTAL - 1) begin               // ask for line 0; that starts the frame
            src_next <= 0; src_cur <= 0;
            fetch_line <= 0; fetch_slot <= 0; fetch_first <= 1'b1;
            fetch_toggle <= ~fetch_toggle;
        end
        if (line_start && y < V_ACTIVE) src_cur <= src_next;
        if (line_start && y == 0) low_r <= (BOB != 0) && (ll ? lw_s[1] : fl_s[1]);
        if (x == 1 && y == 0) begin                             // output line 0
            started <= base >= V4;
            acc     <= (base >= V4) ? base - V4 : base;
        end
        if (x == 2 && y < V_ACTIVE - 1) begin                   // source line for output line y + 1
            if (step >= V4) begin
                acc <= step - V4;
                started <= 1'b1;
                if (started && src_next + 1 < lines) begin
                    src_next   <= src_next + 1'b1;
                    fetch_line <= src_next + 1'b1;
                    fetch_slot <= src_next[1:0] + 2'd1;
                    fetch_first <= 1'b0;
                    fetch_toggle <= ~fetch_toggle;
                end
            end else
                acc <= step;
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
        in_p  <= {in_p[2:0],  in43};
        de_p  <= {de_p[2:0],  de};
        hs_p  <= {hs_p[2:0],  hsync};
        vs_p  <= {vs_p[2:0],  vsync};
        odd_p <= {odd_p[2:0], sx[0]};
    end
    // stage 1: RAM read (lb_rdata valid after the 2nd edge). stage 2: pick Y
    reg [7:0] yy, cb, cr;
    always @(posedge clk) begin
        yy <= odd_p[1] ? lb_rdata[31:24] : lb_rdata[15:8];
        cb <= lb_rdata[7:0];
        cr <= lb_rdata[23:16];
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
endmodule
`default_nettype wire
