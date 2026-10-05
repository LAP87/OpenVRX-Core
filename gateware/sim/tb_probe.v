// M3 probe: decoder A plays a clean NTSC frame; decoder B plays the same bytes
// with YOUT5 stuck low and YOUT2 stuck high (so no timing code survives), on a
// slightly faster clock that stops at STOP_B. Both I2C buses have a TVP5150
// model. The UART output is printed byte by byte ("U xx").
`timescale 1ns/1ps
`default_nettype none
module tb_probe;
    localparam WINDOW = 270_000, DIV = 20;
    localparam STOP_B = 3 * WINDOW * 37 + 1_000_000;          // ns: B's clock dies during the 4th window
    reg clk = 0, ca = 0, cb = 0;
    always #18.5 clk = ~clk;
    always #18.5 ca = ~ca;
    always #18.45 if ($time < STOP_B) cb = ~cb;

    reg [7:0] mem [0:1048575];
    integer n_bytes, ia = 0, ib = 0;
    reg [1023:0] vec;
    reg [7:0] da = 8'h80, db = 8'h80;
    initial begin
        if (!$value$plusargs("vec=%s", vec)) begin $display("RESULT novec"); $finish; end
        $readmemh(vec, mem);
        n_bytes = 0;
        while (mem[n_bytes] !== 8'bx && n_bytes < 1048575) n_bytes = n_bytes + 1;
        $display("VEC %0d bytes", n_bytes);
    end
    always @(posedge ca) begin da <= mem[ia]; ia <= (ia + 1 == n_bytes) ? 0 : ia + 1; end
    always @(posedge cb) begin db <= (mem[ib] & 8'hDF) | 8'h04; ib <= (ib + 1 == n_bytes) ? 0 : ib + 1; end

    wire scl, sda_a, sda_b, txd, resetb, spi_clk, spi_data, spi_sel_n;
    wire [2:0] led;
    pullup (scl); pullup (sda_a); pullup (sda_b);
    wire s_a, s_b;
    assign sda_a = s_a ? 1'b0 : 1'bz;
    assign sda_b = s_b ? 1'b0 : 1'bz;
    i2c_slave_model #(.ADDR(7'h5C)) tvp_a (.scl(scl), .sda(sda_a), .sda_low(s_a));
    i2c_slave_model #(.ADDR(7'h5C)) tvp_b (.scl(scl), .sda(sda_b), .sda_low(s_b));

    // CLK_HZ only scales the millisecond timers (I2C start-up, UART, RX5808 writes) so the run stays
    // short: one probe millisecond is 0.1 ms here. RX5808: first write after 2 ms, repeats 5 ms apart.
    m3_probe #(.CLK_HZ(2_700_000), .WINDOW(WINDOW), .BAUD(2_700_000 / DIV), .POWER_MS(1),
               .RX_FIRST_MS(20), .RX_REPEAT_MS(50)) dut (
        .clk(clk), .tvpa_sclk(ca), .tvpa_d(da), .tvpb_sclk(cb), .tvpb_d(db),
        .i2c_scl(scl), .i2c_sda_a(sda_a), .i2c_sda_b(sda_b), .tvp_resetb(resetb),
        .rx_spi_clk(spi_clk), .rx_spi_data(spi_data), .rx_spi_sel_n(spi_sel_n), .led(led), .uart_txd(txd));
    always @(led) $display("LED %0d %b", $time, led);

    // UART receiver, DIV clocks per bit
    integer ub_t = 0, ub_n = 0; reg [7:0] ub_sh; reg ub_on = 0;
    always @(posedge clk) begin
        if (!ub_on) begin if (!txd) begin ub_on <= 1; ub_t <= 0; ub_n <= 0; end end
        else begin
            ub_t <= ub_t + 1;
            if (ub_t == DIV + DIV / 2 + DIV * ub_n && ub_n < 8) begin ub_sh <= {txd, ub_sh[7:1]}; ub_n <= ub_n + 1; end
            if (ub_t == DIV + DIV / 2 + DIV * 8) begin ub_on <= 0; $display("U %02x", ub_sh); end
        end
    end
    // RX5808 frames: bits on rising clock edges while SEL is low, printed when SEL rises
    reg [24:0] spi_bits;
    integer    spi_n = 0, spi_idle_bad = 0;
    always @(posedge spi_clk) if (!spi_sel_n) begin spi_bits[spi_n] <= spi_data; spi_n <= spi_n + 1; end
    always @(posedge spi_sel_n) begin
        if (spi_n > 0) $display("SPI %0d %0d %07x", $time, spi_n, spi_bits);
        spi_n = 0;
    end
    // between frames: CLK low and DATA high, so that LED4 (on DATA's pin) stays dark
    always @(posedge clk) if (spi_sel_n === 1'b1 && (spi_clk !== 1'b0 || spi_data !== 1'b1)) spi_idle_bad = spi_idle_bad + 1;

    // both decoders report lock from the start (the model's default) and lose it at UNLOCK
    localparam UNLOCK = 32_000_000;
    initial begin
        #(UNLOCK);
        tvp_a.regs[8'h88] = 8'h00; tvp_b.regs[8'h88] = 8'h00;
        $display("UNLOCK %0d", $time);
    end

    initial begin
        #(5 * WINDOW * 37 + 500_000);
        $display("RESULT spi_idle_bad=%0d", spi_idle_bad);
        $finish;
    end
endmodule
`default_nettype wire
