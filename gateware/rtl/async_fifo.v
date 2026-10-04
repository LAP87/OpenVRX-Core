// Dual-clock FIFO with Gray-coded pointers (Cummings style), first-word
// fall-through: rd_data is valid whenever !empty; rd_en pops it.
`default_nettype none
module async_fifo #(
    parameter W = 32,
    parameter AW = 9              // depth 2^AW
) (
    input  wire         wclk,
    input  wire         wrst,
    input  wire         wr_en,
    input  wire [W-1:0] wr_data,
    output wire         full,
    output wire [AW:0]  wr_level,  // approximate fill level seen from the write side

    input  wire         rclk,
    input  wire         rrst,
    input  wire         rd_en,
    output wire [W-1:0] rd_data,
    output wire         empty,
    output wire [AW:0]  rd_level   // approximate fill level seen from the read side
);
    reg [W-1:0] mem [0:(1<<AW)-1];

    reg [AW:0] wbin, wgray, rbin, rgray;
    reg [AW:0] rgray_w1, rgray_w2, wgray_r1, wgray_r2;

    function [AW:0] g2b(input [AW:0] g);
        integer i;
        begin
            g2b[AW] = g[AW];
            for (i = AW - 1; i >= 0; i = i - 1) g2b[i] = g2b[i + 1] ^ g[i];
        end
    endfunction

    // write side
    wire [AW:0] wbin_n  = wbin + (wr_en & ~full);
    wire [AW:0] wgray_n = (wbin_n >> 1) ^ wbin_n;
    assign full = (wgray == {~rgray_w2[AW:AW-1], rgray_w2[AW-2:0]});
    assign wr_level = wbin - g2b(rgray_w2);
    always @(posedge wclk) begin
        if (wr_en && !full) mem[wbin[AW-1:0]] <= wr_data;
        if (wrst) begin wbin <= 0; wgray <= 0; end
        else begin wbin <= wbin_n; wgray <= wgray_n; end
        {rgray_w2, rgray_w1} <= {rgray_w1, rgray};
    end

    // read side
    wire [AW:0] rbin_n  = rbin + (rd_en & ~empty);
    wire [AW:0] rgray_n = (rbin_n >> 1) ^ rbin_n;
    assign empty = (rgray == wgray_r2);
    assign rd_data = mem[rbin[AW-1:0]];
    assign rd_level = g2b(wgray_r2) - rbin;
    always @(posedge rclk) begin
        if (rrst) begin rbin <= 0; rgray <= 0; end
        else begin rbin <= rbin_n; rgray <= rgray_n; end
        {wgray_r2, wgray_r1} <= {wgray_r1, wgray};
    end
endmodule
`default_nettype wire
