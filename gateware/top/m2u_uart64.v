// The same UART check as m2u_uart27, but clocked like memtest_core in M2a: from the SDRAM PLL
// (clocks_sdram.v, 64.8 MHz by design, DIV 562). If m2u_uart27 reads right and this one does not,
// the PLL clock is not what the design assumes (or something else in that domain is off).
// LED0 flips with every line, LED1 lit while the PLL is locked.
`default_nettype none
module m2u_uart64 (
    input  wire       clk,               // 27 MHz
    input  wire       rst_i,             // S1, high when pressed
    output wire [2:0] led,
    output wire       uart_txd
);
    wire sd_clk, sd_clk_shift, sd_locked;
    clocks_sdram sdclk (.clk_27(clk), .clk(sd_clk), .clk_shift(sd_clk_shift), .locked(sd_locked));
    wire      rst_async = rst_i | ~sd_locked;
    reg [2:0] rst_s;
    always @(posedge sd_clk or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    wire led_t;
    uart_line_check #(.CLK_HZ(64_800_000)) chk (.clk(sd_clk), .rst(rst_s[2]), .uart_txd(uart_txd), .line_toggle(led_t));
    assign led = ~{1'b0, sd_locked, led_t};
endmodule
`default_nettype wire
