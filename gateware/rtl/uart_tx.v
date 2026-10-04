// UART transmitter, 8N1, one byte per `send` pulse (while !busy).
`default_nettype none
module uart_tx #(
    parameter DIV = 234                    // clocks per bit: 27 MHz / 115200
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       send,
    input  wire [7:0] data,
    output reg        busy,
    output reg        txd
);
    reg [9:0] sh;
    reg [3:0] n;
    reg [$clog2(DIV+1)-1:0] t;
    always @(posedge clk) begin
        if (rst) begin busy <= 1'b0; txd <= 1'b1; end
        else if (!busy) begin
            if (send) begin busy <= 1'b1; sh <= {1'b1, data, 1'b0}; n <= 0; t <= 0; end
        end else if (t != DIV - 1) t <= t + 1'b1;
        else begin
            t <= 0;
            if (n == 4'd10) busy <= 1'b0;
            else begin txd <= sh[0]; sh <= sh >> 1; n <= n + 1'b1; end
        end
    end
endmodule
`default_nettype wire
