// Sends one fixed 82-character line over uart_tx every PERIOD_MS, for the bench checks
// top/m2u_uart27.v and top/m2u_uart64.v (2026-10-20): the shape of memtest_core.v's report with
// every field a known text, so that a scrambled reception can be told from a wrong report.
//   M rs=5 pass=0012 err=00000000 bits=0123456789ABCDEF0123456789ABCDEF pos=UUUUUUUU
// (U = 55h, alternating bits). line_toggle flips at the start of every line.
`default_nettype none
module uart_line_check #(
    parameter CLK_HZ = 27_000_000,
    parameter BAUD = 115_200,
    parameter PERIOD_MS = 250
) (
    input  wire clk,
    input  wire rst,
    output wire uart_txd,
    output reg  line_toggle
);
    localparam LEN = 82;
    localparam [LEN*8-1:0] TEXT = {"M rs=5 pass=0012 err=00000000 bits=0123456789ABCDEF0123456789ABCDEF pos=UUUUUUUU", 16'h0D0A};
    localparam MS = CLK_HZ / 1000;
    reg  [6:0]  idx;
    reg  [7:0]  ch;
    reg         u_send, active;
    wire        u_busy;
    reg  [$clog2(PERIOD_MS * MS + 1)-1:0] t;
    uart_tx #(.DIV(CLK_HZ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(ch), .busy(u_busy), .txd(uart_txd));
    always @(posedge clk) begin
        u_send <= 1'b0;
        if (rst) begin t <= 0; idx <= 0; active <= 1'b0; line_toggle <= 1'b0; ch <= 8'h20; end
        else begin
            if (t == PERIOD_MS * MS) begin t <= 0; active <= 1'b1; idx <= 0; line_toggle <= ~line_toggle; end
            else t <= t + 1'b1;
            if (active && !u_busy && !u_send) begin
                ch <= TEXT[(LEN - 1 - idx) * 8 +: 8];
                u_send <= 1'b1;
                if (idx == LEN - 1) active <= 1'b0; else idx <= idx + 1'b1;
            end
        end
    end
endmodule
`default_nettype wire
