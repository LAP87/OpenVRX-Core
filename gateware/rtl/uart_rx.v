// UART receiver, 8N1: one `valid` pulse with `data` per byte whose stop bit is high.
// The input passes two flops first (the BL616 drives it asynchronously). A start bit is a low level that is still
// low half a bit later; every bit is then sampled in its middle. A byte whose stop bit reads low (framing error,
// or a break) gives no pulse, and the receiver waits for the line to go high before looking for the next start bit,
// so a held-low line yields nothing.
`default_nettype none
module uart_rx #(
    parameter DIV = 234                    // clocks per bit: 27 MHz / 115200
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       rxd,
    output reg        valid,
    output reg  [7:0] data
);
    reg [2:0] s = 3'b111;                  // sync flops (start high: idle line)
    always @(posedge clk) s <= {s[1:0], rxd};
    wire r = s[2];
    localparam W = $clog2(DIV + 1);
    reg [W-1:0] t;
    reg [3:0]   n;                         // 0 start bit, 1..8 data, 9 stop bit
    reg         busy, wait_high;
    reg [7:0]   sh;
    always @(posedge clk) begin
        valid <= 1'b0;
        if (!busy) begin
            if (wait_high) begin if (r) wait_high <= 1'b0; end
            else if (!r) begin busy <= 1'b1; t <= 0; n <= 0; end
        end else if (t != ((n == 0) ? DIV / 2 - 1 : DIV - 1)) t <= t + 1'b1;
        else begin
            t <= 0;
            if (n == 0) begin
                if (r) busy <= 1'b0;                          // a glitch, not a start bit
                else n <= 1;
            end else if (n != 9) begin
                sh <= {r, sh[7:1]};                           // LSB first
                n <= n + 1'b1;
            end else begin
                busy <= 1'b0;
                if (r) begin valid <= 1'b1; data <= sh; end
                else wait_high <= 1'b1;                       // framing error or break
            end
        end
        if (rst) begin busy <= 1'b0; wait_high <= 1'b1; valid <= 1'b0; n <= 0; t <= 0; end
    end
endmodule
`default_nettype wire
