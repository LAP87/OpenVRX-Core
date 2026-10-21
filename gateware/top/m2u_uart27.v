// Bench check of the onboard USB-UART path (PIN69 -> BL616, 115200 8N1) from the 27 MHz board
// clock, written for the home bench 2026-10-20 where M2a's report arrived as 82-byte lines with
// scrambled bits. Sends a fixed 82-character line of the same shape as memtest_core.v's, with the
// fields filled with known text (rtl/uart_line_check.v), four times a second. If this line reads
// right, the transmitter and the bridge are fine at this clock; m2u_uart64 does the same from the
// SDRAM PLL clock. LED0 flips with every line. No SDRAM, no video; S1 = reset.
`default_nettype none
module m2u_uart27 (
    input  wire       clk,               // 27 MHz
    input  wire       rst_i,             // S1, high when pressed
    output wire [2:0] led,
    output wire       uart_txd
);
    reg [2:0] rst_s;
    always @(posedge clk or posedge rst_i) if (rst_i) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    wire led_t;
    uart_line_check #(.CLK_HZ(27_000_000)) chk (.clk(clk), .rst(rst_s[2]), .uart_txd(uart_txd), .line_toggle(led_t));
    assign led = ~{1'b0, 1'b1, led_t};
endmodule
`default_nettype wire
