// M1: Moneagle -> HDMI first light on Tang Nano 20K.
// Listens passively to a TVP5150AM1's BT.656 output (YOUT0-7 + SCLK), keeps a
// low-resolution luma field buffer in BSRAM and shows it at 720p60 on the
// onboard HDMI, scaled into a centred 4:3 window. No genlock: the output runs
// from the board crystal, so occasional tearing is expected (SDRAM triple
// buffering comes in M2). Shows colour bars when no lines arrive.
//
// LEDs (active low): 0 = 1 Hz heartbeat, 1 = lines arriving, 2 = field 1 seen,
// 3 = timing code corrections seen, 4 = undecodable timing codes seen.
`default_nettype none

module m1_moneagle_view #(
    parameter FB_COLS = 360, FB_LINES = 240   // scaling below assumes 360 x 240 (x 3/8, y / 3)
) (
    input  wire       clk,          // 27 MHz board crystal
    input  wire       rst_i,
    input  wire       tvp_sclk,     // TVP5150AM1 pin 9
    input  wire [7:0] tvp_d,        // TVP5150AM1 pins 18 (YOUT0) .. 11 (YOUT7)
    output wire       tmds_clk_p, tmds_clk_n,
    output wire [2:0] tmds_d_p, tmds_d_n,
    output wire [5:0] led
);
    localparam AW = 17;

    // ---------------- input side (TVP clock domain) ----------------
    reg [7:0] d_in;
    always @(posedge tvp_sclk) d_in <= tvp_d;     // register at the pin

    wire px_valid, px_field, rec_valid, rec_field;
    wire [7:0] px_data;
    wire [10:0] px_index, rec_active;
    wire [9:0] px_line, rec_line;
    wire [15:0] rec_length;
    wire [7:0] rec_xy_corrected, rec_xy_bad;
    wire [19:0] rec_hf;
    bt656_rx rx (.clk(tvp_sclk), .rst(1'b0), .d(d_in),
                 .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_field(px_field), .px_line(px_line),
                 .rec_valid(rec_valid), .rec_field(rec_field), .rec_line(rec_line), .rec_length(rec_length),
                 .rec_active(rec_active), .rec_xy_corrected(rec_xy_corrected), .rec_xy_bad(rec_xy_bad), .rec_hf(rec_hf));

    wire we;
    wire [AW-1:0] waddr;
    wire [7:0] wdata;
    luma_writer #(.FB_COLS(FB_COLS), .FB_LINES(FB_LINES), .AW(AW)) lw (
        .clk(tvp_sclk), .px_valid(px_valid), .px_data(px_data), .px_index(px_index), .px_line(px_line),
        .we(we), .addr(waddr), .data(wdata));

    // activity / status flags in the TVP domain
    reg [21:0] alive_cnt;             // ~155 ms at 27 MHz
    reg        alive, saw_f1, saw_corr, saw_bad;
    always @(posedge tvp_sclk) begin
        if (rec_valid) begin
            alive_cnt <= 0; alive <= 1'b1;
            if (rec_field) saw_f1 <= 1'b1;
            if (rec_xy_corrected != 0) saw_corr <= 1'b1;
            if (rec_xy_bad != 0) saw_bad <= 1'b1;
        end else if (alive_cnt != {22{1'b1}})
            alive_cnt <= alive_cnt + 1'b1;
        else
            alive <= 1'b0;
    end

    // ---------------- output side (720p pixel clock) ----------------
    wire clk_serial, clk_pixel, locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(locked));
    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], ~locked | rst_i};
    wire rst = rst_sr[3];

    wire [11:0] x, y;
    wire de, hs, vs, fs;
    video_timing timing (.clk(clk_pixel), .rst(rst), .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs));

    // source coordinates: 4:3 window x 160..1119 (960 px) <- FB_COLS columns, y 0..719 <- FB_LINES lines
    wire in43 = (x >= 160) && (x < 1120);
    wire [11:0] xr = x - 12'd160;
    wire [13:0] xr3 = {xr, 1'b0} + xr;           // xr * 3
    wire [9:0]  src_x = xr3[12:3];               // * 3/8: 960 output px -> 360 columns
    // src_y = y / 3 with a counter instead of a divider (720 output lines -> 240)
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

    // synchronise the alive flag
    reg [2:0] alive_sync;
    always @(posedge clk_pixel) alive_sync <= {alive_sync[1:0], alive};

    // pipeline: x/y -> raddr (1) -> luma (2); delay timing and window flag by 2
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
        if (!in_p[1])
            {r, g, b} <= 24'h000000;
        else if (alive_sync[2])
            {r, g, b} <= {luma, luma, luma};
        else                                      // no signal: dim colour bars
            {r, g, b} <= {{8{bar_p1[1]}}, {8{bar_p1[2]}}, {8{bar_p1[0]}}} & {3{8'h60}};
    end

    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst),
                      .de(de_o), .hsync(hs_o), .vsync(vs_o), .r(r), .g(g), .b(b), .hz50(1'b0), .rgb_full(1'b1),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    reg [24:0] sec;
    always @(posedge clk) sec <= sec + 1'b1;
    assign led = ~{1'b0, saw_bad, saw_corr, saw_f1, alive, sec[24]};
endmodule
`default_nettype wire
