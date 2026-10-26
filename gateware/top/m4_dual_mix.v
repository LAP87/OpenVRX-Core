// M4: two of our own TVP5150AM1 decoders (two receivers on the same channel)
// -> line-by-line mixer -> SDRAM field triple buffer -> 720p60 on the onboard
// HDMI. The decoders are brought up over I2C by the FPGA (tvp_ctrl). Both
// RX5808 are tuned to F4 5800 MHz 0.5 s after start, and again every 2 s for
// as long as no decoder is locked (rx5808_tune.v, same SPI pins as M3 and M6).
//
// LEDs (active low): 0 heartbeat, 2 Hz when both decoders answer on I2C and
// report horizontal + vertical lock, 1 Hz when one does, 4 Hz when none (DIGIN: B's lock is the
// capture's own flywheel lock, mixer2 b_lock, task 69); 1 lines from A; 2 lines
// from B. For ST_SHOW_MS (3 s) after the SDRAM self-test (sdram_selftest.v, at
// power-up) LED 1 and 2 show its result instead: 1 lit = the build's read point
// (5) read both test bursts right; 2 lit = it did not, but point 4 or 6 did;
// both lit = no point did. The pins of LED 3-5 are header pins: RESETB leaves on 18 (J6-18),
// the RX5808 SPI DATA on 19 (J6-17) and SEL on 20 (J6-16).
// RESETB must not sit in bank 4 or 5 (pins 25-42): Apicula sets BANK_VCCIO for
// a whole bank from its first single-ended output, and that changes the IOB
// fuses of the TMDS pairs there (tools/test_tmds_bank_outputs.py).
`default_nettype none
module m4_dual_mix #(
`ifdef LOW
    parameter LOW_LATENCY = 1,            // LOW=1 gateware/build.sh: no SDRAM field buffer, output locked to the input
`else
    parameter LOW_LATENCY = 0,            // 1: no SDRAM field buffer, output locked to the input (fb_backend.v)
`endif
    parameter CLK_HZ = 27_000_000,        // board clock; a testbench shortens the millisecond timers with it
    parameter ST_SHOW_MS = 3000           // how long LED 1/2 show the SDRAM self-test after it has run
) (
    input  wire        clk,
    input  wire        rst_i,
    input  wire        tvpa_sclk,
    input  wire [7:0]  tvpa_d,
    input  wire        tvpb_sclk,
    input  wire [7:0]  tvpb_d,
    inout  wire        i2c_scl,           // shared
    inout  wire        i2c_sda_a,         // one SDA per decoder: identical modules share an address
    inout  wire        i2c_sda_b,
    output wire        tvp_resetb,        // PIN18 = J6-18 (LED3's pin)
    output wire        rx_spi_clk,        // both RX5808 modules (same channel)
    output wire        rx_spi_data,       // PIN19 = J6-17 (LED4's pin)
    output wire        rx_spi_sel_n,      // PIN20 = J6-16 (LED5's pin)
    output wire        tmds_clk_p, tmds_clk_n,
    output wire [2:0]  tmds_d_p, tmds_d_n,
    output wire [2:0]  led,
    output wire        O_sdram_clk, O_sdram_cke, O_sdram_cs_n, O_sdram_cas_n, O_sdram_ras_n, O_sdram_wen_n,
    output wire [3:0]  O_sdram_dqm,
    output wire [10:0] O_sdram_addr,
    output wire [1:0]  O_sdram_ba,
    inout  wire [31:0] IO_sdram_dq
);
    `include "vtx_channels.vh"
    wire clk_serial, clk_pixel, pix_locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(pix_locked));
    wire sd_clk, sd_clk_shift, sd_locked;
    clocks_sdram sdclk (.clk_27(clk), .clk(sd_clk), .clk_shift(sd_clk_shift), .locked(sd_locked));
    wire rst = rst_i | ~pix_locked | ~sd_locked;
`ifdef DIGIN
    localparam B_DIGITAL = 1;              // DIGIN=1 gateware/build.sh: channel B is the C5VRX sample bus on decoder B's pins
`else
    localparam B_DIGITAL = 0;
`endif

    // ---- decoder bring-up (board clock) ----
    reg [2:0] rst_c;
    reg [3:0] por = 4'hF;                 // power-on reset for the board-clock logic
    always @(posedge clk) begin por <= {por[2:0], 1'b0}; rst_c <= {rst_c[1:0], rst_i | por[3]}; end
    wire scl_low, init_done;
    wire [1:0] sda_low;
    wire [1:0] dev_err, st_valid;
    wire [15:0] st0, st1;
`ifdef TVP_DEV_5D
    localparam [6:0] TVP_DEV = 7'h5D;  // TVP_ADDR=5D gateware/build.sh: modules strapped the other way (YOUT7)
`else
    localparam [6:0] TVP_DEV = 7'h5C;
`endif
    // poll pause 2 ms: 88h is read about every 5 ms per decoder (20 ms until 2026-10-21: about 26 ms);
    // sim/test_rssi_adc.py shows the OLED and the RSSI reads keep their rate on the shared bus
    localparam TVP_POLL_MS = 2;
    tvp_ctrl #(.CLK_HZ(CLK_HZ), .SPLIT_SDA(1), .DEV0(TVP_DEV), .DEV1(TVP_DEV), .POLL_MS(TVP_POLL_MS)) ctrl (
                   .clk(clk), .rst(rst_c[2]), .tvp_resetb(tvp_resetb),
                   .scl_low(scl_low), .sda_low(sda_low), .scl_in(i2c_scl), .sda_in({i2c_sda_b, i2c_sda_a}),
                   .init_done(init_done), .dev_err(dev_err), .status0(st0), .status1(st1), .status_valid(st_valid),
                   .hold(1'b0), .op_mode_req(1'b0), .op_mode_vcr(1'b0), .active());
    assign i2c_scl = scl_low ? 1'b0 : 1'bz;
    assign i2c_sda_a = sda_low[0] ? 1'b0 : 1'bz;
    assign i2c_sda_b = sda_low[1] ? 1'b0 : 1'bz;
    // decoder lock for the heartbeat and the RX5808 tune: TVP status, and for B with DIGIN the
    // capture's own flywheel lock (mixer2 b_lock, task 69), since the sample bus has no TVP status
    wire lock_a_ok  = st_valid[0] && !dev_err[0] && st0[1] && st0[2];
    wire lock_b_tvp = st_valid[1] && !dev_err[1] && st1[1] && st1[2];
    wire b_lock, b_lock_c;                // b_clk domain, synchronised into the board clock
    sync2 blk_sync (.clk(clk), .d(b_lock), .q(b_lock_c));
    wire lock_b_ok  = B_DIGITAL ? b_lock_c : lock_b_tvp;
    wire locked_ok  = B_DIGITAL ? (lock_a_ok && lock_b_ok) :
                      (init_done && dev_err == 2'b00 && st_valid == 2'b11 && st0[1] && st0[2] && st1[1] && st1[2]);

    // ---- RX5808: F4 5800 MHz, as in M3 (board clock) ----
    wire [41:0] f4 = vtx_channel(6'd27);
    wire [1:0]  sel_n;
    wire        any_locked = lock_a_ok || lock_b_ok;
    rx5808_tune #(.CLK_HZ(CLK_HZ)) rx (
        .clk(clk), .rst(rst_c[2]), .synth(f4[19:0]), .write_now(1'b0), .any_locked(any_locked),
        .spi_clk(rx_spi_clk), .spi_data(rx_spi_data), .spi_sel_n(sel_n));
    assign rx_spi_sel_n = sel_n[0];       // both modules share one SEL line

    // ---- mixer (SDRAM clock domain) ----
    wire        m_empty, m_pop, a_lines, b_lines, alive_a, alive_b, cur, overflow;
    wire [51:0] m_data;
    wire        dec_valid, dec_field;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    // a decoder without a whole poll round reporting H and V lock loses against one that has it (dec_bad.v)
    wire nolock_a, nolock_b;
    dec_bad lockrule (.status_valid(st_valid), .status0(st0), .status1(st1), .bad({nolock_b, nolock_a}));
    mixer2 #(.B_DIGITAL(B_DIGITAL)) mix (.a_clk(tvpa_sclk), .a_d(tvpa_d), .b_clk(tvpb_sclk), .b_d(tvpb_d), .sys_clk(sd_clk), .rst_async(rst),
                .ext_bad_a(nolock_a), .ext_bad_b(nolock_b), .ext_weak_a(1'b0), .ext_weak_b(1'b0),
                .out_empty(m_empty), .out_data(m_data), .out_pop(m_pop),
                .a_lines(a_lines), .b_lines(b_lines), .b_lock(b_lock), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
                .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
                .dec_field(dec_field), .dec_line(dec_line));

    wire [7:0] r, g, b;
    wire de, hs, vs, have_video, sdram_ready, hz50, sdram_test_done;
    wire [2:0] sdram_test_ok;
    fb_backend #(.SELFTEST(1)) backend (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(clk_pixel), .rst_async(rst), .ll_mode(LOW_LATENCY[0]),
        .f_empty(m_empty), .f_data(m_data), .f_pop(m_pop),
        .SDRAM_DQ(IO_sdram_dq), .SDRAM_A(O_sdram_addr), .SDRAM_BA(O_sdram_ba), .SDRAM_nCS(O_sdram_cs_n),
        .SDRAM_nWE(O_sdram_wen_n), .SDRAM_nRAS(O_sdram_ras_n), .SDRAM_nCAS(O_sdram_cas_n),
        .SDRAM_CLK(O_sdram_clk), .SDRAM_CKE(O_sdram_cke), .SDRAM_DQM(O_sdram_dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hs), .vsync(vs),
        .have_video(have_video), .sdram_ready(sdram_ready), .hz50(hz50),
        .sdram_test_done(sdram_test_done), .sdram_test_ok(sdram_test_ok));

    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], rst};
    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst_sr[3]),
                      .de(de), .hsync(hs), .vsync(vs), .r(r), .g(g), .b(b), .hz50(hz50), .rgb_full(1'b1),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    // ---- LEDs: heartbeat (2 Hz both decoders locked, 1 Hz one, 4 Hz none), lines from A, lines from B
    // 1 Hz when one decoder is locked, 2 Hz when both are, 4 Hz when none (2026-10-21, hub LOGIKGRANSKNING F2:
    // until then 1 Hz only with both, so a bench with one module never saw the lock)
    localparam [24:0] BEAT_ONE = CLK_HZ / 2 - 1, BEAT_BOTH = CLK_HZ / 4 - 1, BEAT_FAST = CLK_HZ / 8 - 1;
    reg [24:0] beat_t;
    reg        beat;
    always @(posedge clk) begin
        if (beat_t >= (locked_ok ? BEAT_BOTH : any_locked ? BEAT_ONE : BEAT_FAST)) begin beat_t <= 0; beat <= ~beat; end
        else beat_t <= beat_t + 1'b1;
        if (rst_c[2]) begin beat_t <= 0; beat <= 1'b0; end
    end
    // the SDRAM self-test's result (sd domain, steady once done) for ST_SHOW_MS after it has run
    localparam ST_SHOW = CLK_HZ / 1000 * ST_SHOW_MS;
    wire st_done_c;
    sync2 st_sync (.clk(clk), .d(sdram_test_done), .q(st_done_c));
    reg        st_done_d, st_pass, st_other;
    reg [$clog2(ST_SHOW + 1)-1:0] st_show;
    always @(posedge clk) begin
        st_done_d <= st_done_c;
        if (st_done_c && !st_done_d) begin                 // ok has been steady since before done rose
            st_pass <= sdram_test_ok[1]; st_other <= sdram_test_ok[0] | sdram_test_ok[2]; st_show <= ST_SHOW;
        end else if (st_show != 0) st_show <= st_show - 1'b1;
        if (rst_c[2]) begin st_done_d <= 1'b0; st_show <= 0; end
    end
    wire [1:0] st_led = st_pass ? 2'b01 : st_other ? 2'b10 : 2'b11;     // {LED 2, LED 1} lit
    assign led = ~{st_show != 0 ? st_led : {b_lines, a_lines}, beat};
endmodule
`default_nettype wire
