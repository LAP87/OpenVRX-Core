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
    wire       low_lat;
    wire       page;
    reg  tg = 0;                                  // snow meter windows every 100 ms
    always #100_000_000 tg = ~tg;
    wire osd_show, txd;
    wire [6:0] osd_char;
    puck_ui #(.CLK_HZ(1_000_000), .DEBOUNCE_MS(3), .OSD_MS(150), .BAUD(50_000)) ui (
        .clk(clk), .rst(rst), .btn_ok(btn_ok), .btn_next(btn_next), .view_b(view_b),
        .dec_present(2'b11), .dec_locked(2'b01), .force_bad(force_bad),
        .snow_a(20'd12345), .snow_b(20'd2345), .use_a(11'd410), .use_b(11'd358), .use_mix(11'd256),
        .snow_toggle_a(tg), .snow_toggle_b(tg), .use_toggle(tg),
        .rx_spi_clk(sclk), .rx_spi_data(sdat), .rx_spi_sel_n(sel_n),
        .text_row(row), .text_col(col), .text_char(chr),
        .osd_row(2'd0), .osd_col(5'd0), .osd_char(osd_char), .osd_show(osd_show), .uart_txd(txd),
        .band(band), .ch(ch), .mode(mode), .field(field), .page(page), .low_lat(low_lat));

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

    // SPI decoder: bits on rising clock edges while SEL is low
    reg [24:0] spi_bits;
    integer    spi_n = 0;
    always @(posedge sclk) if (sel_n != 2'b11) begin spi_bits[spi_n] <= sdat; spi_n <= spi_n + 1; end
    always @(posedge sel_n[0]) begin
        if (spi_n > 0) $display("SPI %0d %07x", spi_n, spi_bits);
        spi_n = 0;
    end

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

    initial begin
        #3000 rst = 0;
        wait_frames(2);
        $display("MARK default");
        press(1); press(1);                       // band F -> R -> L  (L4 5473, outside SE band)
        wait_frames(2);
        $display("MARK band_L force=%b", force_bad);
        press(1);                                 // band -> A (A4 5805)
        press(0);                                 // field -> channel
        press(1); press(1);                       // A5, A6 (5765)
        press(0);                                 // field -> mode
        press(1);                                 // mode -> A
        view_b = 1;
        wait_frames(2);
        $display("MARK final force=%b band=%0d ch=%0d mode=%0d field=%0d", force_bad, band, ch, mode, field);
        press(0);                                 // field -> latency
        press(1);                                 // BUF -> LOW
        wait_frames(2);
        $display("MARK lat low_lat=%0d", low_lat);
        press(0);                                 // field -> page
        press(1);                                 // page -> meter
        wait_frames(2);
        $display("MARK meter page=%0d", page);
        $display("RESULT collisions=%0d nack=%0d", collisions, nack_error);
        $finish;
    end
    initial begin #5_000_000_000 $display("RESULT timeout"); $finish; end
endmodule
`default_nettype wire
