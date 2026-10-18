// M1 (discrete-sync variant): like m1_moneagle_view, but for a TVP5150AM1 that
// Moneagle's SoC runs in "8-bit 4:2:2 with discrete syncs" mode (no EAV/SAV in
// the data). Uses YOUT0-7 + SCLK + HSYNC (TVP pin 25), VSYNC (pin 24) and
// AVID (pin 26). Polarities and the luma byte phase are detected automatically.
//
// LEDs (active low): 0 = 1 Hz heartbeat, 1 = AVID lines arriving,
// 2 = VSYNC detected active high, 3 = AVID detected active high,
// 4 = luma on odd bytes (Cb Y Cr Y order), 5 = HSYNC detected active high.
`default_nettype none

module m1s_moneagle_view_sync (
    input  wire       clk,
    input  wire       rst_i,
    input  wire       tvp_sclk,
    input  wire [7:0] tvp_d,
    input  wire       tvp_hsync,
    input  wire       tvp_vsync,
    input  wire       tvp_avid,
    output wire       tmds_clk_p, tmds_clk_n,
    output wire [2:0] tmds_d_p, tmds_d_n,
    output wire [5:0] led
);
    localparam FB_COLS = 360, FB_LINES = 240, AW = 17;

    // ---------------- input side (TVP clock domain) ----------------
    reg [7:0] d_in;
    reg hs_in, vs_in, av_in;
    always @(posedge tvp_sclk) {d_in, hs_in, vs_in, av_in} <= {tvp_d, tvp_hsync, tvp_vsync, tvp_avid};

    wire px_valid, px_field, line_done, hs_hi, vs_hi, av_hi, luma_odd;
    wire [7:0] px_data;
    wire [10:0] px_index, line_bytes;
    wire [9:0] px_line;
    tvp_sync_rx rx (.clk(tvp_sclk), .rst(1'b0), .d(d_in), .hsync_in(hs_in), .vsync_in(vs_in), .avid_in(av_in),
                    .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line), .px_field(px_field),
                    .line_done(line_done), .line_bytes(line_bytes), .hs_active_high(hs_hi),
                    .vs_active_high(vs_hi), .avid_active_high(av_hi), .luma_odd(luma_odd));

    wire we;
    wire [AW-1:0] waddr;
    wire [7:0] wdata;
    luma_writer #(.FB_COLS(FB_COLS), .FB_LINES(FB_LINES), .AW(AW)) lw (
        .clk(tvp_sclk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line),
        .we(we), .addr(waddr), .data(wdata));

    reg [21:0] alive_cnt;
    reg        alive;
    always @(posedge tvp_sclk) begin
        if (line_done) begin alive_cnt <= 0; alive <= 1'b1; end
        else if (alive_cnt != {22{1'b1}}) alive_cnt <= alive_cnt + 1'b1;
        else alive <= 1'b0;
    end

    // ---------------- output side (identical to m1_moneagle_view) ----------------
    wire clk_serial, clk_pixel, locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(locked));
    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], ~locked | rst_i};
    wire rst = rst_sr[3];

    wire [11:0] x, y;
    wire de, hs, vs, fs;
    video_timing timing (.clk(clk_pixel), .rst(rst), .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs));

    wire in43 = (x >= 160) && (x < 1120);
    wire [11:0] xr = x - 12'd160;
    wire [13:0] xr3 = {xr, 1'b0} + xr;
    wire [9:0]  src_x = xr3[12:3];
    reg  [9:0] src_y;
    reg  [1:0] y_mod3;
    always @(posedge clk_pixel) if (x == 0) begin
        if (y == 0) begin src_y <= 0; y_mod3 <= 0; end
        else if (y_mod3 == 2) begin src_y <= src_y + 1'b1; y_mod3 <= 0; end
        else y_mod3 <= y_mod3 + 1'b1;
    end
    reg  [AW-1:0] raddr;
    always @(posedge clk_pixel) raddr <= src_y * FB_COLS + src_x;

    wire [7:0] luma;
    dual_clock_ram #(.DEPTH(FB_COLS * FB_LINES), .AW(AW)) fb (
        .wclk(tvp_sclk), .we(we), .waddr(waddr), .wdata(wdata),
        .rclk(clk_pixel), .raddr(raddr), .rdata(luma));

    reg [2:0] alive_sync;
    always @(posedge clk_pixel) alive_sync <= {alive_sync[1:0], alive};
    reg [1:0] de_p, hs_p, vs_p, in_p;
    reg [2:0] bar_p0, bar_p1;
    always @(posedge clk_pixel) begin
        de_p <= {de_p[0], de}; hs_p <= {hs_p[0], hs}; vs_p <= {vs_p[0], vs}; in_p <= {in_p[0], in43};
        bar_p0 <= xr[9:7]; bar_p1 <= bar_p0;
    end
    reg [7:0] r, g, b;
    reg de_o, hs_o, vs_o;
    always @(posedge clk_pixel) begin
        de_o <= de_p[1]; hs_o <= hs_p[1]; vs_o <= vs_p[1];
        if (!in_p[1])            {r, g, b} <= 24'h000000;
        else if (alive_sync[2])  {r, g, b} <= {luma, luma, luma};
        else                     {r, g, b} <= {{8{bar_p1[1]}}, {8{bar_p1[2]}}, {8{bar_p1[0]}}} & {3{8'h60}};
    end

    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst),
                      .de(de_o), .hsync(hs_o), .vsync(vs_o), .r(r), .g(g), .b(b), .hz50(1'b0), .rgb_full(1'b1),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    reg [24:0] sec;
    always @(posedge clk) sec <= sec + 1'b1;
    assign led = ~{hs_hi, luma_odd, av_hi, vs_hi, alive, sec[24]};
endmodule
`default_nettype wire
