// Frame buffer back end shared by M2 and M4: tagged word stream {field, line,
// idx, data} (first-word fall-through, SDRAM clock domain) -> SDRAM field
// store (fb_sdram.v) -> 4:3 colour window in the display timing.
//
// Clock domains: sd_clk (SDRAM controller, 64.8 MHz) and pix_clk (74.25 MHz
// for 720p). Crossings: toggle+stable-data handshakes for line requests and
// field publications. Which field buffer a frame shows is decided in the
// SDRAM domain, where the writer is, at the first line request of the frame.
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
// picture, about 0.8 ms at the bottom.
// The two fields of an interlaced picture arrive alternately a line period
// further apart and closer (field_phase.v). The frame start of the field that
// comes early is delayed by half the difference, so that the output frames
// are equally long: NTSC gives 720p at 59.94 Hz (frames of 750/751 lines),
// PAL 720p50 (H_FP_ALT). The other field is the lower one and is drawn half a
// source line lower. Missing lines keep an initialized slot's old contents;
// a slot with no complete line since reset is black.
`default_nettype none
`ifndef VINTERP
`define VINTERP 0
`endif
module fb_backend #(
    parameter V_TOTAL = 750, V_ACTIVE = 720,
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter V_FP = 5, V_SYNC = 5,
    parameter SDRAM_FREQ = 64_800_000,
    parameter [4:0] RD_SAMPLE = 5'd0,       // SDRAM read sample point; 0 = sdram_burst's default
    parameter H_WIN0 = 160, H_WIN = 960, H_HALF = 0,
    parameter H_FP_ALT = 440,               // 720p50 front porch, low-latency mode with PAL input
    parameter BOB = 1,                      // fb_display.v
    parameter VINTERP = `VINTERP,           // fb_display.v: 1 blends two source lines in BUF (build.sh VINTERP=1)
    parameter RT_EN = 1, RT_NTSC = 4, RT_PAL = 44, RT_HYST = 16, RT_SPLIT = 270,    // fb_sdram.v
    parameter LL_EQ = 1,                    // low-latency mode: delay early fields for frames of equal length
    parameter JUMP_AFTER = 3, HOLD = 32,    // genlock_timing.v
    parameter WAIT_BEFORE_VSYNC = 0,        // genlock_timing.v: the varying line before vsync (needs V_FP >= 2)
    parameter SELFTEST = 0                  // 1: sdram_selftest.v runs once after the SDRAM start-up, before the field store
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
    output wire        sdram_ready,       // sd domain: SDRAM initialised
    output wire        sdram_test_done,   // sd domain: the self-test has run (SELFTEST = 0: always 0)
    output wire [2:0]  sdram_test_ok,     // sd domain, steady once done: sample point 4/5/6 (bit 0/1/2) read right
    output wire        hz50               // pix domain: the timing runs 720p50 lines (LOW with a PAL source)
);
    reg [2:0] rst_s, rst_p;
    always @(posedge sd_clk  or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    always @(posedge pix_clk or posedge rst_async) if (rst_async) rst_p <= 3'b111; else rst_p <= {rst_p[1:0], 1'b0};
    wire srst = rst_s[2], prst = rst_p[2];
    // crossings: cdc_sync.v, proven in formal/toggle_props.v and formal/level_props.v
    wire ll_s, ll_p;
    sync2 ll_sync_s (.clk(sd_clk),  .d(ll_mode), .q(ll_s));
    sync2 ll_sync_p (.clk(pix_clk), .d(ll_mode), .q(ll_p));

    // ---- pixel -> SDRAM domain: line requests ----
    wire       p_fetch_toggle, p_fetch_first;
    wire [1:0] p_fetch_slot;
    wire [9:0] p_fetch_line;
    wire        fetch_ev;
    wire [12:0] fetch_q;
    toggle_rx #(.W(13), .RESET_Q(0)) fetch_rx (.clk(sd_clk), .rst(1'b0), .tgl(p_fetch_toggle),
        .din({p_fetch_first, p_fetch_slot, p_fetch_line}), .event_now(fetch_ev), .q(fetch_q));
    wire       s_fetch_first = fetch_q[12];
    wire [1:0] s_fetch_slot  = fetch_q[11:10];
    wire [9:0] s_fetch_line  = fetch_q[9:0];
    reg        s_fetch_req;
    always @(posedge sd_clk) s_fetch_req <= fetch_ev && !ll_s && !srst;

    // ---- SDRAM domain ----
    wire        req_valid, req_write, req_ready, wdata_take, rdata_valid, init_done;
    wire [20:0] req_addr;
    wire [31:0] wdata, rdata;
    wire [4:0]  rd_sample;
    wire        fb_req_valid, fb_req_write;     // the field store's request port
    wire [20:0] fb_req_addr;
    wire [31:0] fb_wdata;
    wire        lb_we, pub_valid, frame_low;
    wire [10:0] lb_waddr;
    wire [31:0] lb_wdata;
    wire [9:0]  pub_lines;
    sdram_burst #(.FREQ(SDRAM_FREQ)) sdram (
        .SDRAM_DQ(SDRAM_DQ), .SDRAM_A(SDRAM_A), .SDRAM_BA(SDRAM_BA), .SDRAM_nCS(SDRAM_nCS), .SDRAM_nWE(SDRAM_nWE),
        .SDRAM_nRAS(SDRAM_nRAS), .SDRAM_nCAS(SDRAM_nCAS), .SDRAM_CLK(SDRAM_CLK), .SDRAM_CKE(SDRAM_CKE), .SDRAM_DQM(SDRAM_DQM),
        .clk(sd_clk), .clk_sdram(sd_clk_shift), .resetn(~srst), .rd_sample(rd_sample),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid), .init_done(init_done));
    assign sdram_ready = init_done;

    // ---- SDRAM read self-test (sdram_selftest.v): owns the request port until it is done ----
    wire        st_done, st_req_valid, st_req_write;
    wire [20:0] st_req_addr;
    wire [31:0] st_wdata;
    wire [4:0]  st_rd_sample;
    wire [2:0]  st_ok;
    generate if (SELFTEST != 0) begin : selftest
        sdram_selftest test (.clk(sd_clk), .rst(srst), .init_done(init_done),
            .req_valid(st_req_valid), .req_write(st_req_write), .req_addr(st_req_addr), .rd_sample(st_rd_sample),
            .req_ready(req_ready), .wdata(st_wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid),
            .done(st_done), .ok(st_ok));
    end else begin : no_selftest
        assign st_done = 1'b0; assign st_ok = 3'b000;
        assign st_req_valid = 1'b0; assign st_req_write = 1'b0; assign st_req_addr = 21'd0;
        assign st_wdata = 32'd0; assign st_rd_sample = 5'd0;
    end endgenerate
    wire   fb_owns = (SELFTEST == 0) || st_done;
    assign req_valid = fb_owns ? fb_req_valid : st_req_valid;
    assign req_write = fb_owns ? fb_req_write : st_req_write;
    assign req_addr  = fb_owns ? fb_req_addr  : st_req_addr;
    assign wdata     = fb_owns ? fb_wdata     : st_wdata;
    assign rd_sample = fb_owns ? RD_SAMPLE    : st_rd_sample;
    assign sdram_test_done = st_done;
    assign sdram_test_ok   = st_ok;

    wire fb_pop;
    // held in reset in low-latency mode, so that it starts empty when the mode is left
    fb_sdram #(.RT_EN(RT_EN), .RT_NTSC(RT_NTSC), .RT_PAL(RT_PAL), .RT_HYST(RT_HYST), .RT_SPLIT(RT_SPLIT)) fb (
        .clk(sd_clk), .resetn(~srst & init_done & fb_owns & ~ll_s),
        .in_empty(f_empty | ll_s), .in_data(f_data), .in_pop(fb_pop),
        .fetch_req(s_fetch_req), .fetch_first(s_fetch_first), .fetch_line(s_fetch_line), .fetch_slot(s_fetch_slot),
        .lb_we(lb_we), .lb_addr(lb_waddr), .lb_data(lb_wdata),
        .pub_valid(pub_valid), .pub_lines(pub_lines), .frame_low(frame_low),
        .req_valid(fb_req_valid), .req_write(fb_req_write), .req_addr(fb_req_addr), .req_ready(req_ready),
        .wdata(fb_wdata), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid));

    reg       s_pub_toggle;             // one cycle after pub_valid, when pub_lines has its new value
    always @(posedge sd_clk) begin
        if (pub_valid) s_pub_toggle <= ~s_pub_toggle;
        if (srst) s_pub_toggle <= 1'b0;
    end

    // ---- low-latency writer (SDRAM domain): words straight into the line ring ----
    wire       ll_take = ll_s && !f_empty;
    assign f_pop = ll_s ? ll_take : fb_pop;
    wire       e_field = f_data[51];
    wire [9:0] e_line  = f_data[50:41];
    wire [8:0] e_idx   = f_data[40:32];
    reg        ll_have, ll_field, ll_trig_done, s_ll_low, ll_wait, ll_n1_v;
    reg        ll_joined;                 // the ring holds the field the writer joined after the switch
    reg  [9:0] ll_last, ll_max, s_ll_lines, ll_n1;
    reg [11:0] ll_dly;
    wire       ll_new_field = ll_have && (e_field != ll_field || e_line < ll_last);
    wire       ll_done = ll_new_field ? 1'b0 : ll_trig_done;
    wire       ll_end  = ll_take && e_idx == 9'd359;                  // a line is complete
    // The field the writer joined (its first word was not the field's first line) starts no frame:
    // the ring holds only part of it, and its line count is not a field's. The first frame comes
    // from the next field, as in fb_sdram.v.
    wire       ll_joined_w = !ll_have || (ll_joined && !ll_new_field);
    wire       ll_fire = ll_end && e_line != 0 && !ll_done && !ll_joined_w;   // ... and it starts the output frame
    wire       ll_ref  = ll_end && e_line == 10'd1;
    wire [9:0] ll_n    = ll_max + 10'd1;                              // lines of the field just finished
    wire [9:0] ll_gap  = (ll_n > ll_n1) ? ll_n - ll_n1 : ll_n1 - ll_n;
    wire       ph_low, ph_low_now, ph_early;
    wire [11:0] ph_dly;
    field_phase ll_phase (.clk(sd_clk), .rst(srst || !ll_s), .nf(ll_take && (!ll_have || ll_new_field)), .at_ref(ll_ref),
                          .low(ph_low), .low_now(ph_low_now), .il(), .early(ph_early), .dly(ph_dly));
    wire       ll_delay = LL_EQ != 0 && ll_ref && ph_early;           // this field came early: wait ph_dly
    wire       ll_send  = (ll_wait && ll_dly == 12'd0) || (ll_fire && !ll_delay);
    wire       s_ll_trig;
    wire [9:0] s_ll_pay;
    always @(posedge sd_clk) begin
        if (ll_take) begin
            ll_last <= e_line;
            if (!ll_have || ll_new_field) begin
                ll_have <= 1'b1; ll_field <= e_field; ll_max <= e_line; ll_joined <= !ll_have;
                if (ll_new_field && !ll_joined) begin                 // line count as in fb_sdram.v
                    if (!ll_n1_v) s_ll_lines <= ll_n;
                    else if (ll_gap <= 10'd2) s_ll_lines <= (ll_n < ll_n1) ? ll_n : ll_n1;
                    ll_n1 <= ll_n; ll_n1_v <= 1'b1;
                end
            end else if (e_line > ll_max) ll_max <= e_line;
            ll_trig_done <= ll_done;
        end
        // the frame starts once line 1 (or the first later line) of a field is complete;
        // half a line period later if this field came early (ll_send below)
        if (ll_wait) begin
            ll_dly <= ll_dly - 12'd1;
            if (ll_dly == 12'd0) ll_wait <= 1'b0;
        end
        if (ll_fire) begin
            ll_trig_done <= 1'b1;
            s_ll_low <= ll_ref ? ph_low_now : ph_low;
            if (ll_delay) begin ll_wait <= 1'b1; ll_dly <= ph_dly; end
            else ll_wait <= 1'b0;
        end
        if (srst || !ll_s) begin ll_have <= 1'b0; ll_joined <= 1'b0; ll_trig_done <= 1'b0; ll_wait <= 1'b0; ll_n1_v <= 1'b0; end
        if (srst) begin s_ll_lines <= 10'd0; s_ll_low <= 1'b0; end
    end
    // The trigger carries the previous field's line count. That count changes when the next field
    // starts, which may be right after the trigger, so toggle_tx holds a copy from each flip to the
    // next and keeps flips 16 clocks apart (the conditions toggle_rx is proven under).
    toggle_tx #(.W(10), .GAP(16)) ll_tx (.clk(sd_clk), .rst(srst), .req(ll_send), .din(s_ll_lines),
        .tgl(s_ll_trig), .q(s_ll_pay));

    // ---- line buffer: 4 slots x 512 words (SDRAM fetches), or 16 (low-latency ring) ----
    wire [12:0] lb_raddr;
    wire [31:0] lb_rdata;
    wire        lbw_we   = ll_s ? ll_take : lb_we;
    wire [12:0] lbw_addr = ll_s ? {e_line[3:0], e_idx} : {2'b00, lb_waddr};
    wire [31:0] lbw_data = ll_s ? f_data[31:0] : lb_wdata;
    localparam [31:0] LINEBUF_BLACK = 32'h10801080;
    reg [15:0] linebuf_initialized_s;
    reg        linebuf_cover_active;
    reg  [3:0] linebuf_cover_slot;
    reg  [8:0] linebuf_cover_next;
    // The shared RAM is not reset. Mark a physical slot initialized only after
    // observing its accepted words 0..359 in order; LOW may begin mid-line, so
    // an accepted word 359 alone is not enough. Idle cycles do not break a run.
    always @(posedge sd_clk) begin
        if (srst) begin
            linebuf_initialized_s <= 16'd0;
            linebuf_cover_active <= 1'b0;
            linebuf_cover_slot <= 4'd0;
            linebuf_cover_next <= 9'd0;
        end else if (lbw_we) begin
            if (lbw_addr[8:0] == 9'd0) begin
                linebuf_cover_active <= 1'b1;
                linebuf_cover_slot <= lbw_addr[12:9];
                linebuf_cover_next <= 9'd1;
            end else if (linebuf_cover_active && lbw_addr[12:9] == linebuf_cover_slot &&
                         lbw_addr[8:0] == linebuf_cover_next) begin
                if (lbw_addr[8:0] == 9'd359) begin
                    linebuf_initialized_s[linebuf_cover_slot] <= 1'b1;
                    linebuf_cover_active <= 1'b0;
                    linebuf_cover_next <= 9'd0;
                end else
                    linebuf_cover_next <= linebuf_cover_next + 9'd1;
            end else begin
                // A later partial write never invalidates already initialized
                // RAM, but it cannot complete a virgin slot's first full line.
                linebuf_cover_active <= 1'b0;
                linebuf_cover_next <= 9'd0;
            end
        end
    end
    dual_clock_ram #(.DEPTH(8192), .AW(13), .W(32)) linebuf (
        .wclk(sd_clk), .we(lbw_we), .waddr(lbw_addr), .wdata(lbw_data),
        .rclk(pix_clk), .raddr(lb_raddr), .rdata(lb_rdata));
    // VINTERP: a copy of the four BUF slots for the second line of each output line
    wire [10:0] lb_raddr_b;
    wire [31:0] lb_rdata_b;
    generate if (VINTERP != 0) begin : vi_ram
        dual_clock_ram #(.DEPTH(2048), .AW(11), .W(32)) linebuf_b (
            .wclk(sd_clk), .we(lb_we && !ll_s), .waddr(lb_waddr), .wdata(lb_wdata),
            .rclk(pix_clk), .raddr(lb_raddr_b), .rdata(lb_rdata_b));
    end else begin : no_vi_ram
        assign lb_rdata_b = 32'd0;
    end endgenerate

    // These per-slot bits only move 0->1 between global resets, so each can
    // cross independently. Sample slot/mode beside the RAM address: the
    // registered metadata and registered data then describe the same read.
    reg [15:0] linebuf_initialized_p1, linebuf_initialized_p2;
    reg  [3:0] linebuf_read_slot;
    reg        linebuf_read_low;
    always @(posedge pix_clk) begin
        if (prst) begin
            linebuf_initialized_p1 <= 16'd0;
            linebuf_initialized_p2 <= 16'd0;
            linebuf_read_slot <= 4'd0;
            linebuf_read_low <= 1'b0;
        end else begin
            linebuf_initialized_p1 <= linebuf_initialized_s;
            linebuf_initialized_p2 <= linebuf_initialized_p1;
            linebuf_read_slot <= lb_raddr[12:9];
            linebuf_read_low <= ll_p;
        end
    end
    wire [31:0] lb_rdisplay = (linebuf_read_low && !linebuf_initialized_p2[linebuf_read_slot])
                            ? LINEBUF_BLACK : lb_rdata;

    // ---- low-latency trigger into the pixel domain ----
    wire       ll_ev;
    wire [9:0] ll_lines;
    toggle_rx #(.W(10)) ll_rx (.clk(pix_clk), .rst(prst), .tgl(s_ll_trig), .din(s_ll_pay),
        .event_now(ll_ev), .q(ll_lines));
    reg        ll_trig;
    reg  [22:0] ll_since;                 // ~0.1 s at 74.25 MHz without a field -> no video
    always @(posedge pix_clk) begin
        ll_trig <= ll_p && ll_ev;
        if (ll_ev) ll_since <= 0;
        else if (!ll_since[22]) ll_since <= ll_since + 1'b1;
        if (prst || !ll_p) begin ll_trig <= 1'b0; ll_since <= 23'h400000; end   // only this LOW period's triggers count
    end
    wire ll_alive = !ll_since[22];
    wire ll_pal   = ll_lines > 10'd270;
    assign hz50 = ll_p && ll_pal;

    // ---- pixel domain ----
    wire [11:0] x, y;
    wire t_de, t_hs, t_vs, t_fs, t_tr;
    genlock_timing #(.H_ACTIVE(H_ACTIVE), .H_FP(H_FP), .H_SYNC(H_SYNC), .H_BP(H_BP), .H_FP_ALT(H_FP_ALT),
                     .V_ACTIVE(V_ACTIVE), .V_FP(V_FP), .V_SYNC(V_SYNC), .V_BP(V_TOTAL - V_ACTIVE - V_FP - V_SYNC),
                     .JUMP_AFTER(JUMP_AFTER), .HOLD(HOLD), .WAIT_BEFORE_VSYNC(WAIT_BEFORE_VSYNC))
        timing (.clk(pix_clk), .rst(prst), .lock(ll_p), .trig(ll_trig), .h_alt(ll_p && ll_pal),
                .x(x), .y(y), .de(t_de), .hsync(t_hs), .vsync(t_vs), .frame_start(t_fs), .triggered(t_tr));
    assign tx = x;
    assign ty = y;
    fb_display #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .H_WIN0(H_WIN0), .H_WIN(H_WIN), .H_HALF(H_HALF), .BOB(BOB),
                 .VINTERP(VINTERP)) disp (
        .clk(pix_clk), .rst(prst), .x(x), .y(y), .de(t_de), .hsync(t_hs), .vsync(t_vs),
        .pub_toggle(s_pub_toggle), .pub_lines(pub_lines), .frame_low(frame_low),
        .fetch_toggle(p_fetch_toggle), .fetch_line(p_fetch_line), .fetch_slot(p_fetch_slot), .fetch_first(p_fetch_first),
        .ll(ll_p), .ll_lines(ll_lines), .ll_alive(ll_alive), .ll_triggered(t_tr), .ll_low(s_ll_low),
        .lb_raddr(lb_raddr), .lb_rdata(lb_rdisplay), .lb_raddr_b(lb_raddr_b), .lb_rdata_b(lb_rdata_b),
        .r(r), .g(g), .b(b), .yo(yo), .cbo(cbo), .cro(cro), .de_o(de), .hs_o(hsync), .vs_o(vsync), .have_video(have_video));
endmodule
`default_nettype wire
