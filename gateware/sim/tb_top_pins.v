// What the pins of m4_dual_mix (TOP = 4) or m6_puck_proto (TOP = 6) do: the real
// top with everything below it, Gowin primitives replaced by gowin_prim_stubs.v,
// two I2C register models as the decoders (and one as the OLED for M6), a clean
// NTSC stream on decoder A from the start and on decoder B from T_B_NS on
// (before that B has a clock but no timing codes).
//
// The decoders report no lock until T_LOCK_NS (0 = never); with LOCK_B = 0 decoder B never does.
// M6: every log line taken (LOGLINE) and, at the end, the OSD text RAM (OSDTEXT, 128 hex characters).
// +pll_stop_ns=<t>
// stops the PLL outputs and the decoder clocks at t, so the rest of the run
// only costs the board-clock logic. Every change of RESETB and of the LEDs and
// every RX5808 frame is printed for sim/test_top_pins.py; the video path has
// its own tests.
//
// SDRAM = 1 puts sim/sdram_model.v (its default board delays, 3 + 3 ns) on the
// SDRAM pins; with 0 they are open. The SDRAM self-test's result is printed
// (SDRAMTEST), and M4 shows it on LED 1/2 for ST_SHOW_MS.
//
// M6: the onboard flash reads as erased (FLASH = 0), or is sim/spi_flash_model.v
// loaded from mem.hex (FLASH = 1, sim/test_m6_settings.py). The flash load, the
// menu's HDMI range and the transmitter's rgb_full are printed, and the flash's
// program and erase counts at the end.
//
// M6 built with the define DEVCMD (and UART_BAUD): +cmd=<hex byte> +cmd_ns=<t> sends that byte to uart_rxd at t
// (CMD <t> <byte>), and every byte on uart_txd is printed (TXB <t> <byte>, time of the start bit). DUMP_LINES
// shortens the field dump to that many lines (sim/test_field_dump.py).
`timescale 1ns/1ps
`default_nettype none
module tb_top_pins;
    parameter TOP = 4;
    parameter CLK_HZ = 27_000;                    // scales the tops' millisecond timers
    parameter T_B_NS = 300_000;
    parameter T_LOCK_NS = 0;
    parameter T_END_NS = 1_000_000;
    parameter FLASH = 0;
    parameter LOCK_B = 1;
    parameter SDRAM = 0;
    parameter ST_SHOW_MS = 5;                     // M4: LED 1/2 show the SDRAM self-test this long (CLK_HZ ms)

    time stop_ns;
    initial if (!$value$plusargs("pll_stop_ns=%d", stop_ns)) stop_ns = 0;

    reg clk = 0, ca = 0, cb = 0;
    always #18.5 clk = ~clk;
    always #18.5 if (stop_ns == 0 || $time < stop_ns) ca = ~ca;
    always #18.45 if (stop_ns == 0 || $time < stop_ns) cb = ~cb;

    localparam START = 39 * 1716;                 // line 40 of the frame: active picture, so lines count at once
    reg [7:0] mem [0:1048575];
    integer n_bytes, ia = START, ib = START, vec_fd;
    string vec;
    reg [7:0] da = 8'h80, db = 8'h80;
    initial begin
        if (!$value$plusargs("vec=%s", vec)) $fatal(1, "missing +vec=<file>");
        vec_fd = $fopen(vec, "r");
        if (vec_fd == 0) $fatal(1, "cannot open vector: %0s", vec);
        $fclose(vec_fd);
        $readmemh(vec, mem);
        n_bytes = 0;
        while (mem[n_bytes] !== 8'bx && n_bytes < 1048575) n_bytes = n_bytes + 1;
    end
    always @(posedge ca) begin da <= mem[ia]; ia <= (ia + 1 == n_bytes) ? 0 : ia + 1; end
    always @(posedge cb) if ($time >= T_B_NS) begin db <= mem[ib]; ib <= (ib + 1 == n_bytes) ? 0 : ib + 1; end

    wire scl, sda_a, sda_b, resetb;
    wire [2:0] led;
    pullup (scl); pullup (sda_a); pullup (sda_b);
    wire s_a, s_b;
    assign sda_a = s_a ? 1'b0 : 1'bz;
    assign sda_b = s_b ? 1'b0 : 1'bz;
    i2c_slave_model #(.ADDR(7'h5C)) tvp_a (.scl(scl), .sda(sda_a), .sda_low(s_a));
    i2c_slave_model #(.ADDR(7'h5C)) tvp_b (.scl(scl), .sda(sda_b), .sda_low(s_b));
    initial begin
        #1 tvp_a.regs[8'h88] = 8'h00; tvp_b.regs[8'h88] = 8'h00;        // no lock
        if (T_LOCK_NS != 0) begin
            #(T_LOCK_NS);
            tvp_a.regs[8'h88] = 8'h0E;                                     // H, V and colour lock
            if (LOCK_B) tvp_b.regs[8'h88] = 8'h0E;
            $display("LOCK %0d", $time);
        end
    end

    wire [3:0]  tmds_p, tmds_n;
    wire [31:0] dq;
    wire        sd_clk, sd_cke, sd_cs_n, sd_cas_n, sd_ras_n, sd_we_n;
    wire [3:0]  sd_dqm;
    wire [10:0] sd_a;
    wire [1:0]  sd_ba;
    generate if (SDRAM) begin : sd
        sdram_model #(.AW(21)) mem (.clk(sd_clk), .cke(sd_cke), .ncs(sd_cs_n), .nras(sd_ras_n), .ncas(sd_cas_n),
                                    .nwe(sd_we_n), .ba(sd_ba), .a(sd_a), .dqm(sd_dqm), .dq(dq));
    end endgenerate
    wire        spi_clk, spi_data, spi_sel_n;
    generate
        if (TOP == 4) begin : g
            m4_dual_mix #(.CLK_HZ(CLK_HZ), .ST_SHOW_MS(ST_SHOW_MS)) dut (
                .clk(clk), .rst_i(1'b0), .tvpa_sclk(ca), .tvpa_d(da), .tvpb_sclk(cb), .tvpb_d(db),
                .i2c_scl(scl), .i2c_sda_a(sda_a), .i2c_sda_b(sda_b), .tvp_resetb(resetb),
                .rx_spi_clk(spi_clk), .rx_spi_data(spi_data), .rx_spi_sel_n(spi_sel_n),
                .tmds_clk_p(tmds_p[3]), .tmds_clk_n(tmds_n[3]), .tmds_d_p(tmds_p[2:0]), .tmds_d_n(tmds_n[2:0]),
                .led(led),
                .O_sdram_clk(sd_clk), .O_sdram_cke(sd_cke), .O_sdram_cs_n(sd_cs_n), .O_sdram_cas_n(sd_cas_n),
                .O_sdram_ras_n(sd_ras_n), .O_sdram_wen_n(sd_we_n), .O_sdram_dqm(sd_dqm), .O_sdram_addr(sd_a),
                .O_sdram_ba(sd_ba), .IO_sdram_dq(dq));
        end else begin : g
            wire s_oled, txd;
            assign sda_a = s_oled ? 1'b0 : 1'bz;
            i2c_slave_model #(.ADDR(7'h3C)) oled (.scl(scl), .sda(sda_a), .sda_low(s_oled));
            wire f_cs_n, f_clk, f_mosi, f_miso, f_wp_n;
            if (FLASH) begin : fl
                spi_flash_model #(.LOAD(1)) flash (.cs_n(f_cs_n), .clk(f_clk), .mosi(f_mosi), .miso(f_miso),
                                                   .wp_n(f_wp_n));
                initial begin
                    #(T_END_NS - 100);
                    $display("FLASH programs=%0d erases=%0d", flash.programs, flash.erases);
                end
            end else begin : fl
                assign f_miso = 1'b1;                                                    // erased flash
            end
            always @(posedge clk) if (dut.set_load) $display("SETLOAD %0d %020x", $time, dut.saved);
            always @(posedge clk) if (dut.ui.log_take) $display("LOGLINE %0d", $time);
            integer oi;
            initial begin
                #(T_END_NS - 1000);
                $write("OSDTEXT ");
                for (oi = 0; oi < 128; oi = oi + 1) $write("%h", dut.osd.text[oi]);
                $write("\n");
            end
`ifdef DEVCMD
            reg cmd_rxd = 1'b1;
            localparam UDIV = CLK_HZ / `UART_BAUD;
            integer cmd_ns, cmd_b, ck, tk;
            reg [7:0] tb8;
            time tt;
            initial if ($value$plusargs("cmd_ns=%d", cmd_ns) && $value$plusargs("cmd=%h", cmd_b)) begin
                #(cmd_ns);
                @(posedge clk) cmd_rxd = 1'b0;
                repeat (UDIV) @(posedge clk);
                for (ck = 0; ck < 8; ck = ck + 1) begin cmd_rxd = cmd_b[ck]; repeat (UDIV) @(posedge clk); end
                cmd_rxd = 1'b1;
                $display("CMD %0d %02x", $time, cmd_b[7:0]);
            end
            initial begin
                #100_000;
                forever begin
                    @(negedge txd);
                    tt = $time;
                    repeat (UDIV / 2) @(posedge clk);
                    for (tk = 0; tk < 8; tk = tk + 1) begin repeat (UDIV) @(posedge clk); tb8[tk] = txd; end
                    repeat (UDIV) @(posedge clk);
                    $display("TXB %0d %02x", tt, tb8);
                end
            end
`ifdef DUMP_LINES
            defparam dut.dump.N_LINES = `DUMP_LINES;
`endif
`endif
            always @(dut.hdmi_ltd) $display("HDMI %0d %b", $time, dut.hdmi_ltd);
            always @(dut.dvi.rgb_full) $display("RGBFULL %0d %b", $time, dut.dvi.rgb_full);
            m6_puck_proto #(.CLK_HZ(CLK_HZ)) dut (
                .clk(clk), .rst_i(1'b0), .key_i(1'b0),
                .rx_spi_clk(spi_clk), .rx_spi_data(spi_data), .rx_spi_sel_n(spi_sel_n),
                .tvpa_sclk(ca), .tvpa_d(da), .tvpb_sclk(cb), .tvpb_d(db),
                .i2c_scl(scl), .i2c_sda_a(sda_a), .i2c_sda_b(sda_b), .tvp_resetb(resetb),
                .tmds_clk_p(tmds_p[3]), .tmds_clk_n(tmds_n[3]), .tmds_d_p(tmds_p[2:0]), .tmds_d_n(tmds_n[2:0]),
                .led(led), .uart_txd(txd),
`ifdef DEVCMD
                .uart_rxd(cmd_rxd),
`endif
                .flash_cs_n(f_cs_n), .flash_clk(f_clk), .flash_mosi(f_mosi), .flash_miso(f_miso), .flash_wp_n(f_wp_n),
                .O_sdram_clk(sd_clk), .O_sdram_cke(sd_cke), .O_sdram_cs_n(sd_cs_n), .O_sdram_cas_n(sd_cas_n),
                .O_sdram_ras_n(sd_ras_n), .O_sdram_wen_n(sd_we_n), .O_sdram_dqm(sd_dqm), .O_sdram_addr(sd_a),
                .O_sdram_ba(sd_ba), .IO_sdram_dq(dq));
        end
    endgenerate

    always @(posedge g.dut.sdram_test_done) $display("SDRAMTEST %0d %b", $time, g.dut.sdram_test_ok);
    always @(resetb) $display("RESETB %0d %b", $time, resetb);
    always @(led)    $display("LED %0d %b", $time, led);

    // RX5808 frames: bits on rising clock edges while SEL is low, printed when SEL rises
    reg [24:0] spi_bits;
    integer    spi_n = 0;
    always @(posedge spi_clk) if (!spi_sel_n) begin spi_bits[spi_n] <= spi_data; spi_n <= spi_n + 1; end
    always @(posedge spi_sel_n) begin
        if (spi_n > 0) $display("SPI %0d %0d %07x", $time, spi_n, spi_bits);
        spi_n = 0;
    end
    // between frames: CLK low and DATA high, so that LED4 (on DATA's pin) and LED5 (SEL) stay dark
    integer spi_idle_bad = 0;
    always @(posedge clk) if (spi_sel_n === 1'b1 && (spi_clk !== 1'b0 || spi_data !== 1'b1)) spi_idle_bad = spi_idle_bad + 1;

    initial begin
        #(T_END_NS);
        $display("RESULT done spi_idle_bad=%0d", spi_idle_bad);
        $finish;
    end
endmodule
`default_nettype wire
