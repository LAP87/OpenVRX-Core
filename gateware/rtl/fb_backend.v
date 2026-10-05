// Frame buffer back end shared by M2 and M4: tagged word stream {field, line,
// idx, data} (first-word fall-through, SDRAM clock domain) -> SDRAM field
// triple buffer -> 4:3 colour window in the display timing.
//
// Clock domains: sd_clk (SDRAM controller, 64.8 MHz) and pix_clk (74.25 MHz
// for 720p). Crossings: toggle+stable-data handshakes for fetch requests and
// field publications. The displayed buffer reaches the writer through the
// line-0 fetch request of every frame.
//
// Low-latency mode (ll_mode = 1, may change at any time): the SDRAM is
// bypassed. Incoming lines go straight into a ring of 16 lines in the line
// buffer RAM (slot = line mod 16), and the output timing is locked to the
// input (genlock_timing.v): each output frame starts when line 1 of a field
// has arrived, and the display reads the ring as the lines come in. Output
// scan per source line (720p: 3 x 22.2 us for 240 lines) is slightly slower
// than input (63.6 us), so the reader never overtakes the writer, and the
// writer stays < 16 lines ahead (about 13 at the bottom). Latency from a
// line arriving to it being on the wire: about 0.1 ms at the top of the
// picture, about 0.8 ms at the bottom, instead of one to three fields.
// NTSC fields give 720p at 59.94 Hz (frames of 750/751 lines), PAL fields
// 720p50 (H_FP_ALT). Lines that never arrive show whatever the slot held.
`default_nettype none
module fb_backend #(
    parameter V_TOTAL = 750, V_ACTIVE = 720,
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter V_FP = 5, V_SYNC = 5,
    parameter SDRAM_FREQ = 64_800_000,
    parameter [4:0] RD_SAMPLE = 5'd0,       // SDRAM read sample point; 0 = sdram_burst's default
    parameter H_WIN0 = 160, H_WIN = 960, H_HALF = 0,
    parameter H_FP_ALT = 440                // 720p50 front porch, low-latency mode with PAL input
) (
    input  wire        sd_clk,
    input  wire        sd_clk_shift,
    input  wire        pix_clk,
    input  wire        rst_async,         // active high, any domain
    input  wire        ll_mode,           // any domain: 1 = low latency (no SDRAM buffer)

    input  wire        f_empty,
    input  wire [51:0] f_data,
    output wire        f_pop,

    inout  wire [31:0] SDRAM_DQ,
    output wire [10:0] SDRAM_A,
    output wire [1:0]  SDRAM_BA,
    output wire        SDRAM_nCS, SDRAM_nWE, SDRAM_nRAS, SDRAM_nCAS, SDRAM_CLK, SDRAM_CKE,
    output wire [3:0]  SDRAM_DQM,

    output wire [7:0]  r, g, b,
    output wire        de, hsync, vsync,
    output wire [7:0]  yo, cbo, cro,      // YCbCr with the same timing as r/g/b
    output wire [11:0] tx, ty,            // timing generator position (the video is valid 6 clocks later)
    output wire        have_video,        // pix domain: a field buffer is being shown
    output wire        sdram_ready        // sd domain: SDRAM initialised
);
    reg [2:0] rst_s, rst_p;
    always @(posedge sd_clk  or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    always @(posedge pix_clk or posedge rst_async) if (rst_async) rst_p <= 3'b111; else rst_p <= {rst_p[1:0], 1'b0};
    wire srst = rst_s[2], prst = rst_p[2];
    reg [1:0] ll_ss, ll_ps;
    always @(posedge sd_clk)  ll_ss <= {ll_ss[0], ll_mode};
    always @(posedge pix_clk) ll_ps <= {ll_ps[0], ll_mode};
    wire ll_s = ll_ss[1], ll_p = ll_ps[1];

    // ---- pixel -> SDRAM domain: fetch requests ----
    wire       p_fetch_toggle;
    wire [1:0] p_fetch_buf, p_fetch_slot, p_display_buf;
    wire [9:0] p_fetch_line;
    reg  [2:0] ft;
    reg        s_fetch_req;
    reg  [1:0] s_fetch_buf, s_fetch_slot, s_display_buf;
    reg  [9:0] s_fetch_line;
    always @(posedge sd_clk) begin
        ft <= {ft[1:0], p_fetch_toggle};
        s_fetch_req <= 1'b0;
        if (ft[2] != ft[1]) begin
            s_fetch_req  <= 1'b1;
            s_fetch_buf  <= p_fetch_buf; s_fetch_line <= p_fetch_line; s_fetch_slot <= p_fetch_slot;
            if (p_fetch_line == 0) s_display_buf <= p_fetch_buf;
        end
        if (srst) begin s_fetch_req <= 1'b0; s_display_buf <= 2'd0; end
    end

    // ---- SDRAM domain ----
    wire        req_valid, req_write, req_ready, wdata_take, rdata_valid, init_done;
    wire [20:0] req_addr;
    wire [31:0] wdata, rdata;
    wire        lb_we, pub_valid;
    wire [10:0] lb_waddr;
    wire [31:0] lb_wdata;
    wire [1:0]  pub_buf;
    wire [9:0]  pub_lines;
    sdram_burst #(.FREQ(SDRAM_FREQ)) sdram (
        .SDRAM_DQ(SDRAM_DQ), .SDRAM_A(SDRAM_A), .SDRAM_BA(SDRAM_BA), .SDRAM_nCS(SDRAM_nCS), .SDRAM_nWE(SDRAM_nWE),
        .SDRAM_nRAS(SDRAM_nRAS), .SDRAM_nCAS(SDRAM_nCAS), .SDRAM_CLK(SDRAM_CLK), .SDRAM_CKE(SDRAM_CKE), .SDRAM_DQM(SDRAM_DQM),
        .clk(sd_clk), .clk_sdram(sd_clk_shift), .resetn(~srst), .rd_sample(RD_SAMPLE),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid), .init_done(init_done));
    assign sdram_ready = init_done;

    wire fb_pop;
    fb_sdram fb (
        .clk(sd_clk), .resetn(~srst & init_done),
        .in_empty(f_empty | ll_s), .in_data(f_data), .in_pop(fb_pop),
        .fetch_req(s_fetch_req), .fetch_buf(s_fetch_buf), .fetch_line(s_fetch_line), .fetch_slot(s_fetch_slot),
        .lb_we(lb_we), .lb_addr(lb_waddr), .lb_data(lb_wdata),
        .display_buf(s_display_buf), .pub_valid(pub_valid), .pub_buf(pub_buf), .pub_lines(pub_lines),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid));

    reg       s_pub_toggle;
    reg [1:0] s_pub_buf;
    reg [9:0] s_pub_lines;
    always @(posedge sd_clk) begin
        if (pub_valid) begin s_pub_toggle <= ~s_pub_toggle; s_pub_buf <= pub_buf; s_pub_lines <= pub_lines; end
        if (srst) s_pub_toggle <= 1'b0;
    end

    // ---- low-latency writer (SDRAM domain): words straight into the line ring ----
    wire       ll_take = ll_s && !f_empty;
    assign f_pop = ll_s ? ll_take : fb_pop;
    wire       e_field = f_data[51];
    wire [9:0] e_line  = f_data[50:41];
    wire [8:0] e_idx   = f_data[40:32];
    reg        ll_have, ll_field, ll_trig_done, s_ll_trig;
    reg  [9:0] ll_last, ll_max, s_ll_lines;
    wire       ll_new_field = ll_have && (e_field != ll_field || e_line < ll_last);
    wire       ll_done = ll_new_field ? 1'b0 : ll_trig_done;
    always @(posedge sd_clk) begin
        if (ll_take) begin
            ll_last <= e_line;
            if (!ll_have || ll_new_field) begin
                ll_have <= 1'b1; ll_field <= e_field; ll_max <= e_line;
                if (ll_new_field) s_ll_lines <= ll_max + 10'd1;    // lines of the field just finished
            end else if (e_line > ll_max) ll_max <= e_line;
            ll_trig_done <= ll_done;
            // the frame starts once line 1 (or the first later line) of a field is complete
            if (e_idx == 9'd359 && e_line != 0 && !ll_done) begin
                s_ll_trig <= ~s_ll_trig; ll_trig_done <= 1'b1;
            end
        end
        if (srst || !ll_s) begin ll_have <= 1'b0; ll_trig_done <= 1'b0; end
        if (srst) begin s_ll_trig <= 1'b0; s_ll_lines <= 10'd0; end
    end

    // ---- line buffer: 4 slots x 512 words (SDRAM fetches), or 16 (low-latency ring) ----
    wire [12:0] lb_raddr;
    wire [31:0] lb_rdata;
    wire        lbw_we   = ll_s ? ll_take : lb_we;
    wire [12:0] lbw_addr = ll_s ? {e_line[3:0], e_idx} : {2'b00, lb_waddr};
    wire [31:0] lbw_data = ll_s ? f_data[31:0] : lb_wdata;
    dual_clock_ram #(.DEPTH(8192), .AW(13), .W(32)) linebuf (
        .wclk(sd_clk), .we(lbw_we), .waddr(lbw_addr), .wdata(lbw_data),
        .rclk(pix_clk), .raddr(lb_raddr), .rdata(lb_rdata));

    // ---- low-latency trigger into the pixel domain ----
    reg  [2:0] llt;
    reg        ll_trig;
    reg  [9:0] ll_lines;
    reg  [22:0] ll_since;                 // ~0.1 s at 74.25 MHz without a field -> no video
    always @(posedge pix_clk) begin
        llt <= {llt[1:0], s_ll_trig};
        ll_trig <= ll_p && (llt[2] != llt[1]);
        if (llt[2] != llt[1]) begin ll_lines <= s_ll_lines; ll_since <= 0; end
        else if (!ll_since[22]) ll_since <= ll_since + 1'b1;
        if (prst) begin ll_trig <= 1'b0; ll_lines <= 10'd0; ll_since <= 23'h400000; end
    end
    wire ll_alive = !ll_since[22];
    wire ll_pal   = ll_lines > 10'd270;

    // ---- pixel domain ----
    wire [11:0] x, y;
    wire t_de, t_hs, t_vs, t_fs;
    genlock_timing #(.H_ACTIVE(H_ACTIVE), .H_FP(H_FP), .H_SYNC(H_SYNC), .H_BP(H_BP), .H_FP_ALT(H_FP_ALT),
                     .V_ACTIVE(V_ACTIVE), .V_FP(V_FP), .V_SYNC(V_SYNC), .V_BP(V_TOTAL - V_ACTIVE - V_FP - V_SYNC))
        timing (.clk(pix_clk), .rst(prst), .lock(ll_p), .trig(ll_trig), .h_alt(ll_p && ll_pal),
                .x(x), .y(y), .de(t_de), .hsync(t_hs), .vsync(t_vs), .frame_start(t_fs));
    assign tx = x;
    assign ty = y;
    fb_display #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .H_WIN0(H_WIN0), .H_WIN(H_WIN), .H_HALF(H_HALF)) disp (
        .clk(pix_clk), .rst(prst), .x(x), .y(y), .de(t_de), .hsync(t_hs), .vsync(t_vs),
        .pub_toggle(s_pub_toggle), .pub_buf(s_pub_buf), .pub_lines(s_pub_lines),
        .fetch_toggle(p_fetch_toggle), .fetch_buf(p_fetch_buf), .fetch_line(p_fetch_line), .fetch_slot(p_fetch_slot),
        .display_buf(p_display_buf),
        .ll(ll_p), .ll_lines(ll_lines), .ll_alive(ll_alive),
        .lb_raddr(lb_raddr), .lb_rdata(lb_rdata),
        .r(r), .g(g), .b(b), .yo(yo), .cbo(cbo), .cro(cro), .de_o(de), .hs_o(hsync), .vs_o(vsync), .have_video(have_video));
endmodule
`default_nettype wire
