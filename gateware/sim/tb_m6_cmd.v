// puck_ui with the development command channel (DEVCMD = 1, or 0 for the control): bytes from cmds.hex go to
// uart_rxd at BAUD 8N1, each after its own delay; sim/test_m6_cmd.py reads what comes out.
// cmds.hex: one 32-bit word per byte, {delay in clocks after the previous byte's stop bit [31:8], byte [7:0]}.
// Printed: SEND <t> <byte> at each start bit sent, RX <t> <byte> <cmd> when the receiver delivers a byte
// (puck_ui rx_valid; cmd = it is a command), TX <t> <byte> for every byte on uart_txd with the time of its
// start bit, SIG <t> <name> <value> when an output changes, SPI <t> at the end of each RX5808 frame,
// DUMP <t> <bits> for dump_req, and END at the end.
// No mixer window comes (the toggles stand still), so the log lines are the heartbeat's, one per HEARTBEAT_MS.
`timescale 1ns/1ps
`default_nettype none
module tb_m6_cmd;
    parameter DEVCMD = 1;
    parameter CLK_HZ = 1_000_000;
    parameter BAUD = 62_500;              // 16 clocks per bit
    parameter END_CLK = 1_500_000;
    localparam DIV = CLK_HZ / BAUD;

    reg clk = 0, rst = 1;
    always #500 clk = ~clk;               // 1 MHz
    integer t = 0;
    always @(posedge clk) t <= t + 1;

    reg  rxd = 1'b1;
    wire txd, sclk, sdat, osd_show, filter_vcr, filter_changed, low_lat, hdmi_ltd, rssi_cal, scan_busy, ch_hold;
    wire [1:0] sel_n, force_bad, mode, page, text_big, dump_req;
    wire [2:0] band, ch, field;
    wire [6:0] text_char, osd_char;
    puck_ui #(.CLK_HZ(CLK_HZ), .DEBOUNCE_MS(3), .OSD_MS(2), .MENU_MS(1000), .HDMI_BUILD(0), .BAUD(BAUD),
              .RX_FIRST_MS(1), .RX_REPEAT_MS(1000), .HEARTBEAT_MS(20), .DEVCMD(DEVCMD), .TVP_FIRST(7'h5C)) dut (
        .clk(clk), .rst(rst), .btn_down(1'b0), .btn_up(1'b0), .view_b(1'b0),
        .dec_present(2'b11), .dec_locked(2'b11), .dec_round(2'b00), .dec_lost(2'b00),
        .snow_a(20'd0), .snow_b(20'd0), .use_a(11'd0), .use_b(11'd0), .use_mix(11'd0),
        .snow_toggle_a(1'b0), .snow_toggle_b(1'b0), .use_toggle(1'b0),
        .noise_a(20'd0), .noise_b(20'd0), .noise_toggle_a(1'b0), .noise_toggle_b(1'b0),
        .rssi_a(16'd0), .rssi_b(16'd0), .rssi_valid(2'b00), .rssi_cal_ok(2'b00), .rssi_low(2'b00),
        .rssi_warn(2'b00), .rssi_pct_a(7'd0), .rssi_pct_b(7'd0), .rssi_cal(rssi_cal),
        .set_load(1'b0), .set_band(3'd0), .set_ch(3'd0), .set_mode(2'd0), .set_low_lat(1'b0), .set_filter(1'b0),
        .set_hdmi(1'b0), .set_ready(1'b1), .set_dirty(1'b0), .set_stored(1'b0), .set_err(1'b0),
        .scan_busy(scan_busy), .ch_hold(ch_hold), .force_bad(force_bad),
        .rx_spi_clk(sclk), .rx_spi_data(sdat), .rx_spi_sel_n(sel_n),
        .text_row(2'd0), .text_col(5'd0), .text_char(text_char), .text_big(text_big),
        .osd_row(2'd0), .osd_col(5'd0), .osd_char(osd_char), .osd_show(osd_show),
        .mix_overflow(1'b0), .sdram_test(4'b1010), .uart_txd(txd),
        .band(band), .ch(ch), .mode(mode), .field(field), .page(page), .low_lat(low_lat),
        .filter_vcr(filter_vcr), .filter_changed(filter_changed), .hdmi_ltd(hdmi_ltd),
        // status line inputs: A answers at 5D (address search found the other one), whole round, 03h = 0Dh;
        // B gave no answer
        .uart_rxd(rxd), .dec_init_done(1'b1), .dec_err(2'b10), .dec_valid(2'b01), .dec_alt(2'b01),
        .dec_misc_ok(2'b01), .dec_st0(16'h100E), .dec_st1(16'h0000), .dec_misc0(8'h0D), .dec_misc1(8'h00),
        .dec_ri0(8'h00), .dec_ri1(8'h03), .dump_req(dump_req), .tx_pause(1'b0), .tx_idle());   // no field dump here

    // ---- commands
    reg [31:0] cmds [0:255];
    integer n_cmds, k, b;
    initial begin
        for (k = 0; k < 256; k = k + 1) cmds[k] = 32'hxxxxxxxx;
        $readmemh("cmds.hex", cmds);
        n_cmds = 0;
        while (n_cmds < 256 && cmds[n_cmds] !== 32'hxxxxxxxx) n_cmds = n_cmds + 1;
        repeat (20) @(posedge clk);
        rst = 0;
        for (k = 0; k < n_cmds; k = k + 1) begin
            repeat (cmds[k][31:8]) @(posedge clk);
            $display("SEND %0d %02x", t, cmds[k][7:0]);
            rxd = 1'b0; repeat (DIV) @(posedge clk);                       // start bit
            for (b = 0; b < 8; b = b + 1) begin rxd = cmds[k][b]; repeat (DIV) @(posedge clk); end
            rxd = 1'b1; repeat (DIV) @(posedge clk);                       // stop bit
        end
    end
    generate if (DEVCMD != 0) begin : g_rx_mon
        always @(posedge clk) if (dut.rx_valid) $display("RX %0d %02x %0d", t, dut.rx_byte, dut.cmd);
    end endgenerate

    // ---- log bytes (start bit time, sampled in the middle of each bit)
    integer tx_t0, i;
    reg [7:0] tx_b;
    initial begin
        @(negedge rst);
        forever begin
            @(negedge txd);
            tx_t0 = t;
            repeat (DIV / 2) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin repeat (DIV) @(posedge clk); tx_b[i] = txd; end
            repeat (DIV) @(posedge clk);
            $display("TX %0d %02x", tx_t0, tx_b);
        end
    end

    // ---- outputs
    always @(posedge clk) if (!rst) begin
        if (filter_changed) $display("SIG %0d filter_changed %0d", t, filter_vcr);
        if (dump_req != 2'b00) $display("DUMP %0d %0d", t, dump_req);
    end
    always @(low_lat)   if (!rst) $display("SIG %0d low_lat %0d", t, low_lat);
    always @(filter_vcr) if (!rst) $display("SIG %0d filter_vcr %0d", t, filter_vcr);
    always @(mode)      if (!rst) $display("SIG %0d mode %0d", t, mode);
    always @(force_bad) if (!rst) $display("SIG %0d force_bad %0d", t, force_bad);
    always @(ch_hold)   if (!rst) $display("SIG %0d ch_hold %0d", t, ch_hold);
    always @(osd_show)  if (!rst) $display("SIG %0d osd_show %0d", t, osd_show);
    always @(band or ch) if (!rst) $display("SIG %0d chan %0d", t, {band, ch});
    always @(posedge sel_n[0]) if (!rst) $display("SPI %0d", t);

    initial begin
        #(END_CLK * 1000.0);
        $display("END %0d", t);
        $finish;
    end
endmodule
`default_nettype wire
