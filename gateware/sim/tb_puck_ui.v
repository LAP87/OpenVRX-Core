// puck_ui + ssd1306_text + I2C slave (logs the OLED writes) + a fake second I2C
// master that respects `hold` and reports `active`, like tvp_ctrl. Buttons are
// pressed from the initial block; SPI frames are decoded here and printed.
`timescale 1ns/1ps
`default_nettype none
module tb_puck_ui;
    reg clk = 0, rst = 1;
    always #500 clk = ~clk;                       // 1 MHz
    reg btn_ok = 0, btn_next = 0;
    reg view_b = 0;
    wire [1:0] force_bad, sel_n;
    wire sclk, sdat;
    wire [1:0] row;
    wire [4:0] col;
    wire [6:0] chr;
    wire [2:0] band, ch;
    wire [1:0] mode;
    wire [2:0] field;
    wire filter_vcr, filter_changed;
    wire       low_lat;
    wire [1:0] page;
    wire       rssi_cal;
    reg  tg = 0;                                  // snow meter windows every 100 ms
    always #100_000_000 tg = ~tg;
    wire osd_show, txd;
    wire [6:0] osd_char;
    reg [1:0] osd_row = 0;
    reg [4:0] osd_col = 0;
    integer filter_pulses = 0, filter_width_errors = 0;
    reg filter_changed_d = 0;
    always @(posedge clk) begin
        if (filter_changed) filter_pulses = filter_pulses + 1;
        if (filter_changed && filter_changed_d) filter_width_errors = filter_width_errors + 1;
        filter_changed_d = filter_changed;
    end
    reg  [1:0] dec_locked = 2'b01;                // decoder A locked, B not
    reg  mix_overflow = 0;                        // set after the "final" mark
    // decoder poll rounds (tvp_ctrl round_ok): both every 20 ms. A's round reads 88h bit 4 once,
    // after the "lat" mark. B's rounds stop at the "unlock" mark; its bit 4 then stays at 1
    // (a stale status word), which must not count without a round.
    reg  [1:0] dec_round = 2'b00;
    reg        lost_a = 0, lost_a_once = 0, rounds_b = 1;
    integer    rt = 0;
    always @(posedge clk) begin
        dec_round <= 2'b00;
        rt <= (rt == 19_999) ? 0 : rt + 1;
        if (rt == 19_999) begin
            dec_round <= {rounds_b, 1'b1}; lost_a <= lost_a_once; lost_a_once <= 0;
        end
    end
    wire [1:0] dec_lost = {!rounds_b, lost_a};
    // RX5808: first write 5 ms after reset, repeats every 40 ms while no decoder is locked
    puck_ui #(.CLK_HZ(1_000_000), .DEBOUNCE_MS(3), .OSD_MS(150), .BAUD(50_000),
              .RX_FIRST_MS(5), .RX_REPEAT_MS(40)) ui (
        .clk(clk), .rst(rst), .btn_ok(btn_ok), .btn_next(btn_next), .view_b(view_b),
        .dec_present(2'b11), .dec_locked(dec_locked), .dec_round(dec_round), .dec_lost(dec_lost),
        .rssi_a(16'd12000), .rssi_b(16'd4567), .rssi_valid(2'b11), .rssi_cal_ok(2'b11), .rssi_low(2'b10),
        .rssi_warn(2'b10), .rssi_pct_a(7'd75), .rssi_pct_b(7'd3), .rssi_cal(rssi_cal),
        .force_bad(force_bad),
        .snow_a(20'd12345), .snow_b(20'd2345), .use_a(11'd410), .use_b(11'd358), .use_mix(11'd256),
        .snow_toggle_a(tg), .snow_toggle_b(tg), .use_toggle(tg),
        .noise_a(20'd17), .noise_b(20'd654321), .noise_toggle_a(tg), .noise_toggle_b(tg),
        .rx_spi_clk(sclk), .rx_spi_data(sdat), .rx_spi_sel_n(sel_n),
        .text_row(row), .text_col(col), .text_char(chr),
        .osd_row(osd_row), .osd_col(osd_col), .osd_char(osd_char), .osd_show(osd_show),
        .mix_overflow(mix_overflow), .uart_txd(txd),
        .band(band), .ch(ch), .mode(mode), .field(field), .page(page), .low_lat(low_lat),
        .filter_vcr(filter_vcr), .filter_changed(filter_changed));

    wire scl_low, sda_low, s_low, hold, frame_done, nack_error;
    reg  other_active = 0;
    wire scl = scl_low ? 1'b0 : 1'b1;
    wire sda = (sda_low | s_low) ? 1'b0 : 1'b1;
    ssd1306_text #(.CLK_HZ(1_000_000), .I2C_DIV(2), .POWER_MS(1)) oled (
        .clk(clk), .rst(rst), .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl), .sda_in(sda),
        .hold_other(hold), .other_active(other_active), .text_row(row), .text_col(col), .text_char(chr),
        .frame_done(frame_done), .nack_error(nack_error));
    i2c_slave_model #(.ADDR(7'h3C), .LOG(1)) disp (.scl(scl), .sda(sda), .sda_low(s_low));

    // fake second master: every 700 clocks it wants a 60-clock transaction, starting only when !hold
    integer gap = 0, run = 0, collisions = 0;
    always @(posedge clk) begin
        if (run > 0) begin run <= run - 1; if (run == 1) other_active <= 0; end
        else if (gap < 700) gap <= gap + 1;
        else if (!hold) begin other_active <= 1; run <= 60; gap <= 0; end
        if (other_active && oled.i2c.busy) collisions <= collisions + 1;
    end

    // SPI decoder: bits on rising clock edges while SEL is low; printed with the time SEL rose
    reg [24:0] spi_bits;
    integer    spi_n = 0;
    always @(posedge sclk) if (sel_n != 2'b11) begin spi_bits[spi_n] <= sdat; spi_n <= spi_n + 1; end
    always @(posedge sel_n[0]) begin
        if (spi_n > 0) $display("SPI %0d %07x %0d", spi_n, spi_bits, $time);
        spi_n = 0;
    end
    // between frames: CLK low and DATA high (DATA shares its pin with an active-low LED)
    integer spi_idle_bad = 0;
    always @(posedge clk) if (!rst && sel_n == 2'b11 && (sclk !== 1'b0 || sdat !== 1'b1)) spi_idle_bad = spi_idle_bad + 1;

    // UART receiver (20 clocks per bit): print every received byte
    integer ub_t = 0, ub_n = 0; reg [7:0] ub_sh; reg ub_on = 0;
    always @(posedge clk) begin
        if (!ub_on) begin if (!txd) begin ub_on <= 1; ub_t <= 0; ub_n <= 0; end end
        else begin
            ub_t <= ub_t + 1;
            if (ub_t == 30 + 20 * ub_n && ub_n < 8) begin ub_sh <= {txd, ub_sh[7:1]}; ub_n <= ub_n + 1; end
            if (ub_t == 30 + 20 * 8) begin ub_on <= 0; $display("U %02x", ub_sh); end
        end
    end
    // OSD visibility changes
    always @(osd_show) $display("OSD %0t %0d", $time, osd_show);

    integer frames = 0;
    always @(posedge clk) if (frame_done) begin frames <= frames + 1; $display("FRAME %0d", frames + 1); end

    task press(input which);                      // 0 = OK, 1 = NEXT
        begin
            if (which) btn_next = 1; else btn_ok = 1;
            #8_000_000;                           // 8 ms > 3 ms debounce
            btn_next = 0; btn_ok = 0;
            #8_000_000;
        end
    endtask
    task wait_frames(input integer n);
        integer target;
        begin target = frames + n; wait (frames >= target); end
    endtask
    task sample_osd_row(input integer tag);
        integer k;
        reg [167:0] sampled;
        begin
            osd_row = 2'd3;
            sampled = {21{8'h20}};
            for (k = 0; k < 21; k = k + 1) begin
                osd_col = k;
                @(posedge clk);
                #1 sampled[(20 - k) * 8 +: 8] = {1'b0, osd_char};
            end
            $display("OSDROW %0d %s", tag, sampled);
        end
    endtask

    initial begin
        #3000 rst = 0;
        wait_frames(2);
        $display("MARK default");
        sample_osd_row(0);
        $display("FIELD %0d", field);
        repeat (6) begin press(0); $display("FIELD %0d", field); end
        press(1); press(1);                       // band F -> R -> L  (L4 5473, outside SE band)
        wait_frames(2);
        $display("MARK band_L force=%b", force_bad);
        press(0); press(0); press(0); press(0);    // field 4: filter
        press(1);                                 // TV -> VCR
        wait_frames(2);
        $display("MARK filter_oob");
        sample_osd_row(1);
        press(0); press(0);                       // filter -> page -> band
        press(1);                                 // band -> A (A4 5805)
        press(0);                                 // field -> channel
        press(1); press(1);                       // A5, A6 (5765)
        press(0);                                 // field -> mode
        press(1);                                 // mode -> A
        view_b = 1;
        wait_frames(2);
        $display("MARK final force=%b band=%0d ch=%0d mode=%0d field=%0d", force_bad, band, ch, mode, field);
        mix_overflow = 1;
        press(0);                                 // field -> latency
        press(1);                                 // BUF -> LOW
        wait_frames(2);
        $display("MARK lat low_lat=%0d", low_lat);
        lost_a_once = 1;                          // decoder A's next poll round reads 88h bit 4
        press(0);                                 // field -> filter
        wait_frames(2);
        $display("MARK filter_select_vcr");
        sample_osd_row(2);
        press(1);                                 // VCR -> TV
        wait_frames(2);
        $display("MARK filter_select_tv");
        sample_osd_row(3);
        press(0);                                 // field -> page
        wait_frames(2);
        $display("MARK page_selected");
        sample_osd_row(4);
        press(1);                                 // page -> meter
        wait_frames(2);
        $display("MARK meter page=%0d", page);
        dec_locked = 2'b00;                       // both decoders lose lock: the channel is written again
        $display("MARK unlock %0d", $time);
        rounds_b = 0;                             // decoder B's poll rounds stop (its last bit 4 stays 1)
        #130_000_000;                             // three repeats, 40 ms apart
        dec_locked = 2'b10;                       // B locks: no more repeats (the next was due after 30 ms)
        $display("MARK relock %0d", $time);
        #70_000_000;
        press(1);                                 // page -> RSSI
        wait_frames(2);
        $display("MARK rssi page=%0d cal=%0d", page, rssi_cal);
        press(0);                                 // field -> CAL (only on the RSSI page)
        wait_frames(2);
        $display("MARK cal_selected field=%0d", field);
        press(1);                                 // calibration on
        wait_frames(2);
        $display("MARK cal_on cal=%0d", rssi_cal);
        press(1);                                 // and off
        $display("MARK cal_off cal=%0d", rssi_cal);
        press(1);                                 // on again, then leave the page: it ends
        press(0);                                 // CAL -> band (the field wraps after CAL)
        $display("MARK wrapped field=%0d cal=%0d", field, rssi_cal);
        repeat (5) press(0);                      // -> page
        press(1);                                 // RSSI -> main
        wait_frames(2);
        $display("MARK left page=%0d cal=%0d", page, rssi_cal);
        $display("RESULT collisions=%0d nack=%0d spi_idle_bad=%0d filter_pulses=%0d filter_width_errors=%0d final_filter_vcr=%0d",
                 collisions, nack_error, spi_idle_bad, filter_pulses, filter_width_errors, filter_vcr);
        $finish;
    end
    initial begin #5_000_000_000 $display("RESULT timeout"); $finish; end
endmodule
`default_nettype wire
