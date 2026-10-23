// field_dump.v on its own: two taps, each on its own clock, play word streams from tap0.hex / tap1.hex in a loop;
// the dump of tap 0 is asked for, then the dump of tap 1. sim/test_field_dump.py checks the bytes on txd.
// tapN.hex: one 64-bit word per stream word, {gap in tap clocks before it [63:56], 4'd0, word [51:0]}.
// Printed: TX <t> <byte> for each byte on txd (time of its start bit), BUSY <t> <v>, OWNS <t> <v>, END.
`timescale 1ns/1ps
`default_nettype none
module tb_field_dump;
    parameter CLK_HZ = 1_000_000;
    parameter BAUD = 250_000;
    parameter N_LINES = 12;
    parameter TIMEOUT_MS = 30;
    localparam DIV = CLK_HZ / BAUD;

    reg clk = 0, c0 = 0, c1 = 0, rst = 1;
    always #500 clk = ~clk;               // 1 MHz board clock
    always #365 c0 = ~c0;                 // tap 0, about 1.37 MHz
    always #290 c1 = ~c1;                 // tap 1, about 1.72 MHz
    integer t = 0;
    always @(posedge clk) t <= t + 1;

    reg [63:0] m0 [0:16383];
    reg [63:0] m1 [0:16383];
    integer n0, n1;
    initial begin
        for (n0 = 0; n0 < 16384; n0 = n0 + 1) begin m0[n0] = 64'hx; m1[n0] = 64'hx; end
        $readmemh("tap0.hex", m0);
        $readmemh("tap1.hex", m1);
        n0 = 0; while (n0 < 16384 && m0[n0] !== 64'hx) n0 = n0 + 1;
        n1 = 0; while (n1 < 16384 && m1[n1] !== 64'hx) n1 = n1 + 1;
    end
    // stream players
    reg        v0 = 0, v1 = 0;
    reg [51:0] w0, w1;
    integer i0 = 0, g0 = 0, i1 = 0, g1 = 0;
    always @(posedge c0) begin
        v0 <= 1'b0;
        if (g0 < m0[i0][63:56]) g0 <= g0 + 1;
        else begin v0 <= 1'b1; w0 <= m0[i0][51:0]; g0 <= 0; i0 <= (i0 + 1 == n0) ? 0 : i0 + 1; end
    end
    always @(posedge c1) begin
        v1 <= 1'b0;
        if (g1 < m1[i1][63:56]) g1 <= g1 + 1;
        else begin v1 <= 1'b1; w1 <= m1[i1][51:0]; g1 <= 0; i1 <= (i1 + 1 == n1) ? 0 : i1 + 1; end
    end

    reg  [1:0] req = 2'b00;
    wire busy, owns, txd;
    field_dump #(.CLK_HZ(CLK_HZ), .BAUD(BAUD), .N_LINES(N_LINES), .TIMEOUT_MS(TIMEOUT_MS)) dut (
        .clk(clk), .rst(rst), .req(req), .busy(busy), .tx_idle(1'b1), .owns_tx(owns), .txd(txd),
        .t0_clk(c0), .t0_rst(rst), .t0_valid(v0), .t0_word(w0),
        .t1_clk(c1), .t1_rst(rst), .t1_valid(v1), .t1_word(w1));

    always @(busy) if (!rst) $display("BUSY %0d %0d", t, busy);
    always @(owns) if (!rst) $display("OWNS %0d %0d", t, owns);

    integer tx_t0, k;
    reg [7:0] b;
    initial begin
        @(negedge rst);
        forever begin
            @(negedge txd);
            tx_t0 = t;
            repeat (DIV / 2) @(posedge clk);
            for (k = 0; k < 8; k = k + 1) begin repeat (DIV) @(posedge clk); b[k] = txd; end
            repeat (DIV) @(posedge clk);
            $display("TX %0d %02x", tx_t0, b);
        end
    end

    initial begin
        repeat (30) @(posedge clk);
        rst = 0;
        repeat (2000) @(posedge clk);
        @(negedge clk) req = 2'b01;                  // set between edges: the module samples it once
        @(negedge clk) req = 2'b00;
        @(negedge busy);
        repeat (1000) @(posedge clk);
        @(negedge clk) req = 2'b10;
        @(negedge clk) req = 2'b00;
        @(negedge busy);
        repeat (200) @(posedge clk);
        $display("END %0d", t);
        $finish;
    end
    initial begin #(4_000_000_000.0); $display("TIMEOUT"); $finish; end
endmodule
`default_nettype wire
