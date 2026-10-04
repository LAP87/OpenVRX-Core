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

    wire scl, sda_a, sda_b, txd, resetb, spi_clk;
    wire [5:0] led;
    pullup (scl); pullup (sda_a); pullup (sda_b);
    wire s_a, s_b;
    assign sda_a = s_a ? 1'b0 : 1'bz;
    assign sda_b = s_b ? 1'b0 : 1'bz;
    i2c_slave_model #(.ADDR(7'h5C)) tvp_a (.scl(scl), .sda(sda_a), .sda_low(s_a));
    i2c_slave_model #(.ADDR(7'h5C)) tvp_b (.scl(scl), .sda(sda_b), .sda_low(s_b));

    // CLK_HZ only scales the millisecond timers (I2C start-up, UART) so the run stays short
    m3_probe #(.CLK_HZ(2_700_000), .WINDOW(WINDOW), .BAUD(2_700_000 / DIV), .POWER_MS(1)) dut (
        .clk(clk), .tvpa_sclk(ca), .tvpa_d(da), .tvpb_sclk(cb), .tvpb_d(db),
        .i2c_scl(scl), .i2c_sda_a(sda_a), .i2c_sda_b(sda_b), .tvp_resetb(resetb),
        .rx_spi_clk(spi_clk), .led(led), .uart_txd(txd));

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
    // RX5808 frame at start-up: count SPI clocks while SEL (led[5]) is low
    integer spi_n = 0;
    always @(posedge spi_clk) if (!led[5]) spi_n = spi_n + 1;

    initial begin
        #(5 * WINDOW * 37 + 500_000);
        $display("RESULT spi=%0d", spi_n);
        $finish;
    end
endmodule
`default_nettype wire
