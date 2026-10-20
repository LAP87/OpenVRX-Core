// M6: puck prototype step 1 = M4 (two TVP5150AM1 + line mixer -> 720p60 HDMI)
// plus the puck UI: two RX5808 modules tuned over SPI, an SSD1306 128x32 OLED
// on the I2C bus of decoder A (shared with tvp_ctrl through hold/active), and
// the two onboard buttons (S1 = "v" next item or page, S2 = "^" change or menu; flight view, information pages and a
// menu with one item per screen, puck_ui.v). S1 is no longer a reset button; reset
// comes from the PLLs locking at power-up.
// See puck_ui.v for the screen and design/PUCK_2027_KONCEPT.md for the idea.
// RSSI: rssi_adc.v reads both receivers' RSSI from the rev A board's ADS1115 (48h) on the
// same bus once per field; its warning (one receiver low, the other not) makes the mixer
// prefer the other receiver (mixer2 ext_weak). Without the ADC nothing answers at 48h and
// nothing changes. Three masters share SCL + SDA_A: rssi_adc goes first (it raises its hold
// only between OLED bytes), the OLED waits for it and tvp_ctrl, tvp_ctrl waits for both holds.
// Saved settings: flash_store.v keeps band, channel, mode, latency, filter, HDMI range and the RSSI
// calibration in the last two sectors of the onboard SPI flash (pins 57, 59-62) and loads them at start;
// its ready / dirty / stored / err tell the flight view whether the current settings are saved.
// HDMI range: the menu's FULL / LTD (puck_ui hdmi_ltd, board clock) goes to tmds_link.v as rgb_full,
// which takes it into the pixel clock domain at each vsync; only the HDMI build (HDMI=1) uses it.
//
// LEDs (active low): 0 heartbeat, 1 Hz when both decoders answer on I2C and
// report horizontal + vertical lock, 4 Hz when not; 1 lines from A; 2 lines
// from B. The pins of LED 3-5 (18, 19, 20) are also header pins J6-18 / J6-17 /
// J6-16 and carry RESETB and the RX5808 SPI DATA and SEL. Every ordinary GPIO
// on the headers is taken by the two decoders, and the free pins 52-56 are
// FPGA configuration pins (52 = SSPI SCLK, 53 = DOUT), so they are avoided.
// RESETB must not sit in bank 4 or 5 (pins 25-42): Apicula sets BANK_VCCIO for
// a whole bank from its first single-ended output, and that changes the IOB
// fuses of the TMDS pairs there (tools/test_tmds_bank_outputs.py).
`default_nettype none
module m6_puck_proto #(
    parameter CLK_HZ = 27_000_000         // board clock; a testbench shortens the millisecond timers with it
) (
    input  wire        clk,
    input  wire        rst_i,             // S1: the "v" button (next)
    input  wire        key_i,             // S2: the "^" button (change)
    output wire        rx_spi_clk,        // both RX5808 modules (same channel)
    output wire        rx_spi_data,       // PIN19 = J6-17 (LED4's pin)
    output wire        rx_spi_sel_n,      // PIN20 = J6-16 (LED5's pin)
    input  wire        tvpa_sclk,
    input  wire [7:0]  tvpa_d,
    input  wire        tvpb_sclk,
    input  wire [7:0]  tvpb_d,
    inout  wire        i2c_scl,           // shared
    inout  wire        i2c_sda_a,         // one SDA per decoder: identical modules share an address
    inout  wire        i2c_sda_b,
    output wire        tvp_resetb,        // PIN18 = J6-18 (LED3's pin)
    output wire        tmds_clk_p, tmds_clk_n,
    output wire [2:0]  tmds_d_p, tmds_d_n,
    output wire [2:0]  led,
    output wire        uart_txd,          // measurement log -> onboard BL616 USB-UART (115200 8N1)
    // the onboard SPI flash after configuration (MSPI pins as user I/O, gowin_pack --mspi_as_gpio):
    // saved settings in its last two sectors (flash_store.v)
    output wire        flash_cs_n, flash_clk, flash_mosi,
    input  wire        flash_miso,
    output wire        flash_wp_n,        // driven high only while writing, else released
    output wire        O_sdram_clk, O_sdram_cke, O_sdram_cs_n, O_sdram_cas_n, O_sdram_ras_n, O_sdram_wen_n,
    output wire [3:0]  O_sdram_dqm,
    output wire [10:0] O_sdram_addr,
    output wire [1:0]  O_sdram_ba,
    inout  wire [31:0] IO_sdram_dq
);
    wire clk_serial, clk_pixel, pix_locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(pix_locked));
    wire sd_clk, sd_clk_shift, sd_locked;
    clocks_sdram sdclk (.clk_27(clk), .clk(sd_clk), .clk_shift(sd_clk_shift), .locked(sd_locked));
    wire rst = ~pix_locked | ~sd_locked;

    // ---- decoder bring-up (board clock) ----
    reg [2:0] rst_c;
    reg [3:0] por = 4'hF;                 // power-on reset for the board-clock logic
    always @(posedge clk) begin por <= {por[2:0], 1'b0}; rst_c <= {rst_c[1:0], por[3]}; end
    wire scl_low, init_done;
    wire [1:0] sda_low;
    wire [1:0] dev_err, st_valid, round_ok, lost_lock;
    wire [15:0] st0, st1;
    wire filter_vcr, filter_changed, hdmi_ltd;
    tvp_ctrl #(.CLK_HZ(CLK_HZ), .SPLIT_SDA(1), .DEV0(7'h5C), .DEV1(7'h5C)) ctrl (
                   .clk(clk), .rst(rst_c[2]), .tvp_resetb(tvp_resetb),
                   .scl_low(scl_low), .sda_low(sda_low), .scl_in(i2c_scl), .sda_in({i2c_sda_b, i2c_sda_a}),
                   .init_done(init_done), .dev_err(dev_err), .status0(st0), .status1(st1), .status_valid(st_valid),
                   .round_ok(round_ok), .lost_lock(lost_lock), .hold(oled_hold | rssi_hold),
                   .op_mode_req(filter_changed), .op_mode_vcr(filter_vcr), .active(tvp_active));
    // ---- puck UI: OLED shares SCL + SDA_A with tvp_ctrl and rssi_adc (one master at a time)
    wire oled_scl_low, oled_sda_low, oled_hold, tvp_active, frame_done, oled_nack, oled_active;
    wire rssi_scl_low, rssi_sda_low, rssi_hold, rssi_active, rssi_cal, rssi_done;
    wire [15:0] rssi_a, rssi_b;
    wire [1:0]  rssi_valid, rssi_cal_ok, rssi_low, rssi_warn;
    wire [6:0]  rssi_pct_a, rssi_pct_b;
    wire [15:0] rssi_min_a, rssi_max_a, rssi_min_b, rssi_max_b;
    // ---- saved settings: band, channel, mode, latency, filter, HDMI range, RSSI calibration
    //      (payload layout in flash_store.v and model/flash_store_ref.py)
    wire [79:0] saved;
    wire        set_load, flash_ready, flash_err, flash_dirty, flash_stored, wp_drive, scan_busy;
    flash_store #(.CLK_HZ(CLK_HZ)) store (
                   .clk(clk), .rst(rst_c[2]), .flash_cs_n(flash_cs_n), .flash_clk(flash_clk), .flash_mosi(flash_mosi),
                   .flash_miso(flash_miso), .flash_wp_drive(wp_drive),
                   .cur({band, ch, mode, low_lat, filter_vcr, hdmi_ltd, 5'd0, rssi_min_a, rssi_max_a, rssi_min_b, rssi_max_b}),
                   .loaded(saved), .load(set_load), .ready(flash_ready), .err(flash_err), .dirty(flash_dirty),
                   .stored(flash_stored), .seq());
    assign flash_wp_n = wp_drive ? 1'b1 : 1'bz;
    rssi_adc #(.CLK_HZ(CLK_HZ)) rssi (
                   .clk(clk), .rst(rst_c[2]), .scl_low(rssi_scl_low), .sda_low(rssi_sda_low),
                   .scl_in(i2c_scl), .sda_in(i2c_sda_a), .hold_other(rssi_hold), .other_hold(oled_hold),
                   .other_active(tvp_active | oled_active), .active(rssi_active), .cal(rssi_cal),
                   .load(set_load), .load_min_a(saved[63:48]), .load_max_a(saved[47:32]),
                   .load_min_b(saved[31:16]), .load_max_b(saved[15:0]),
                   .raw_a(rssi_a), .raw_b(rssi_b), .valid(rssi_valid),
                   .min_a(rssi_min_a), .max_a(rssi_max_a), .min_b(rssi_min_b), .max_b(rssi_max_b),
                   .cal_ok(rssi_cal_ok), .pct_a(rssi_pct_a), .pct_b(rssi_pct_b), .low(rssi_low), .warn(rssi_warn),
                   .done(rssi_done));
    wire [1:0] trow, tbig, force_bad, sel_n;
    wire [4:0] tcol;
    wire [6:0] tchar;
    wire [2:0] band, ch;
    wire [1:0] mode;
    wire [2:0] field;
    wire [1:0] page;
    wire       cur, osd_show, low_lat;
    wire [6:0] osd_char;
    wire [19:0] snow_a, snow_b;
    wire [10:0] use_a, use_b, use_mix;
    wire        snow_ta, snow_tb, use_t;
    wire [19:0] noise_a, noise_b;
    wire        noise_ta, noise_tb;
    ssd1306_text #(.CLK_HZ(CLK_HZ)) oled (
                       .clk(clk), .rst(rst_c[2]), .scl_low(oled_scl_low), .sda_low(oled_sda_low),
                       .scl_in(i2c_scl), .sda_in(i2c_sda_a), .hold_other(oled_hold),
                       .other_active(tvp_active | rssi_hold | rssi_active), .active(oled_active),
                       .text_row(trow), .text_col(tcol), .text_char(tchar), .text_big(tbig),
                       .frame_done(frame_done),
                       .nack_error(oled_nack));
`ifdef HDMI
    localparam HDMI_BUILD = 1;             // the menu's HDMI item has an effect (tmds_link.v rgb_full)
`else
    localparam HDMI_BUILD = 0;             // DVI: the item says N/A and ^ leaves it
`endif
    puck_ui #(.CLK_HZ(CLK_HZ), .HDMI_BUILD(HDMI_BUILD)) ui (
                .clk(clk), .rst(rst_c[2]), .btn_down(rst_i), .btn_up(key_i), .view_b(cur),
                .dec_present({init_done & ~dev_err[1], init_done & ~dev_err[0]}),
                .dec_locked({st_valid[1] & st1[1] & st1[2], st_valid[0] & st0[1] & st0[2]}),
                .dec_round(round_ok), .dec_lost(lost_lock),                 // 88h bit 4, see tvp_ctrl.v
                .snow_a(snow_a), .snow_b(snow_b), .use_a(use_a), .use_b(use_b), .use_mix(use_mix),
                .snow_toggle_a(snow_ta), .snow_toggle_b(snow_tb), .use_toggle(use_t),
                .noise_a(noise_a), .noise_b(noise_b), .noise_toggle_a(noise_ta), .noise_toggle_b(noise_tb),
                .rssi_a(rssi_a), .rssi_b(rssi_b), .rssi_valid(rssi_valid), .rssi_cal_ok(rssi_cal_ok),
                .rssi_low(rssi_low), .rssi_warn(rssi_warn), .rssi_pct_a(rssi_pct_a), .rssi_pct_b(rssi_pct_b),
                .rssi_cal(rssi_cal),
                .set_load(set_load), .set_band(saved[79:77]), .set_ch(saved[76:74]), .set_mode(saved[73:72]),
                .set_low_lat(saved[71]), .set_filter(saved[70]), .set_hdmi(saved[69]),
                .set_ready(flash_ready), .set_dirty(flash_dirty), .set_stored(flash_stored), .set_err(flash_err),
                .scan_busy(scan_busy), .ch_hold(),
                .force_bad(force_bad), .rx_spi_clk(rx_spi_clk), .rx_spi_data(rx_spi_data), .rx_spi_sel_n(sel_n),
                .text_row(trow), .text_col(tcol), .text_char(tchar), .text_big(tbig),
                .osd_row(scan_row), .osd_col(scan_col), .osd_char(osd_char), .osd_show(osd_show),
                .mix_overflow(overflow), .uart_txd(uart_txd),
                .band(band), .ch(ch), .mode(mode), .field(field), .page(page), .low_lat(low_lat),
                .filter_vcr(filter_vcr), .filter_changed(filter_changed), .hdmi_ltd(hdmi_ltd));
    assign i2c_scl = (scl_low | oled_scl_low | rssi_scl_low) ? 1'b0 : 1'bz;
    assign i2c_sda_a = (sda_low[0] | oled_sda_low | rssi_sda_low) ? 1'b0 : 1'bz;
    assign i2c_sda_b = sda_low[1] ? 1'b0 : 1'bz;
    assign rx_spi_sel_n = sel_n[0];       // both modules share one SEL line
    wire locked_ok = init_done && dev_err == 2'b00 && st_valid == 2'b11 &&
                     st0[1] && st0[2] && st1[1] && st1[2];

    // ---- mixer (SDRAM clock domain) ----
    wire        m_empty, m_pop, a_lines, b_lines, alive_a, alive_b, overflow;
    wire [51:0] m_data;
    wire        dec_valid, dec_field;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    // a decoder that answers but reports no H or V lock loses against one that is locked
    wire nolock_a = st_valid[0] && !(st0[1] && st0[2]);
    wire nolock_b = st_valid[1] && !(st1[1] && st1[2]);
    mixer2 mix (.a_clk(tvpa_sclk), .a_d(tvpa_d), .b_clk(tvpb_sclk), .b_d(tvpb_d), .sys_clk(sd_clk), .rst_async(rst),
                .ext_bad_a(nolock_a | force_bad[0]), .ext_bad_b(nolock_b | force_bad[1]),
                .ext_weak_a(rssi_warn[0]), .ext_weak_b(rssi_warn[1]),
                .out_empty(m_empty), .out_data(m_data), .out_pop(m_pop),
                .a_lines(a_lines), .b_lines(b_lines), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
                .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
                .dec_field(dec_field), .dec_line(dec_line),
                .snow_a(snow_a), .snow_b(snow_b), .use_a(use_a), .use_b(use_b), .use_mix(use_mix),
                .snow_toggle_a(snow_ta), .snow_toggle_b(snow_tb), .use_toggle(use_t),
                .noise_a(noise_a), .noise_b(noise_b), .noise_toggle_a(noise_ta), .noise_toggle_b(noise_tb));

    wire [7:0] r, g, b;
    wire de, hs, vs, have_video, sdram_ready, hz50;
    wire [11:0] tx, ty;
    // ---- OSD: mirror the menu text into the overlay's RAM (board clock), draw it over the video
    reg  [1:0] scan_row, w_row;
    reg  [4:0] scan_col, w_col;
    reg        scan_we;
    always @(posedge clk) begin
        scan_col <= (scan_col == 5'd20) ? 5'd0 : scan_col + 1'b1;
        if (scan_col == 5'd20) scan_row <= scan_row + 1'b1;
        {w_row, w_col} <= {scan_row, scan_col};           // osd_char is one clock behind the address
        scan_we <= 1'b1;
    end
    wire [7:0] ro, go, bo;
    wire deo, hso, vso;
    osd_overlay #(.X0(176), .Y0(576), .SCALE(3), .LAT(6)) osd (
        .clk(clk_pixel), .show(osd_show), .x(tx), .y(ty), .r_in(r), .g_in(g), .b_in(b),
        .de_in(de), .hs_in(hs), .vs_in(vs), .r(ro), .g(go), .b(bo), .de(deo), .hs(hso), .vs(vso),
        .wclk(clk), .we(scan_we), .waddr({w_row, w_col}), .wchar(osd_char));
    fb_backend backend (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(clk_pixel), .rst_async(rst), .ll_mode(low_lat),
        .f_empty(m_empty), .f_data(m_data), .f_pop(m_pop),
        .SDRAM_DQ(IO_sdram_dq), .SDRAM_A(O_sdram_addr), .SDRAM_BA(O_sdram_ba), .SDRAM_nCS(O_sdram_cs_n),
        .SDRAM_nWE(O_sdram_wen_n), .SDRAM_nRAS(O_sdram_ras_n), .SDRAM_nCAS(O_sdram_cas_n),
        .SDRAM_CLK(O_sdram_clk), .SDRAM_CKE(O_sdram_cke), .SDRAM_DQM(O_sdram_dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hs), .vsync(vs), .yo(), .cbo(), .cro(), .tx(tx), .ty(ty),
        .have_video(have_video), .sdram_ready(sdram_ready), .hz50(hz50));

    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], rst};
    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst_sr[3]),
                      .de(deo), .hsync(hso), .vsync(vso), .r(ro), .g(go), .b(bo), .hz50(hz50), .rgb_full(!hdmi_ltd),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    // ---- LEDs: heartbeat (1 Hz both decoders locked, 4 Hz not), lines from A, lines from B
    localparam [24:0] BEAT_SLOW = CLK_HZ / 2 - 1, BEAT_FAST = CLK_HZ / 8 - 1;
    reg [24:0] beat_t;
    reg        beat;
    always @(posedge clk) begin
        if (beat_t >= (locked_ok ? BEAT_SLOW : BEAT_FAST)) begin beat_t <= 0; beat <= ~beat; end
        else beat_t <= beat_t + 1'b1;
        if (rst_c[2]) begin beat_t <= 0; beat <= 1'b0; end
    end
    assign led = ~{b_lines, a_lines, beat};
endmodule
`default_nettype wire
