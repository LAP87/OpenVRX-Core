// Dual-clock FIFO with Gray-coded pointers (Cummings style), first-word
// fall-through: rd_data is valid whenever !empty; rd_en pops it.
//
// RD_REG = 0 (default): rd_data is an asynchronous read of the word at the read pointer, so the
// memory can only be LUT RAM (RAM16SDP4 on the GW2A: one CFU, 8 LUT positions, per 16 x 4 bits).
// RD_REG = 1: every read clock loads the word at the pointer's next value into a register, which
// lets the memory go into block RAM. rd_data is the same as with RD_REG = 0 on every clock while
// !empty: the word at the read pointer was written before the first synchroniser stage saw it, and
// the writer never writes a word the reader has not popped (proven by formal/run.sh for both).
// mixer2.v uses it for the two input FIFOs (2026-10-14: M6 with HDMI and VINTERP did not place;
// gateware/README.md, "Bygget av M6").
`default_nettype none
module async_fifo #(
    parameter W = 32,
    parameter AW = 9,             // depth 2^AW
    parameter RD_REG = 0
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
    assign rd_level = g2b(wgray_r2) - rbin;
    always @(posedge rclk) begin
        if (rrst) begin rbin <= 0; rgray <= 0; end
        else begin rbin <= rbin_n; rgray <= rgray_n; end
        {wgray_r2, wgray_r1} <= {wgray_r1, wgray};
    end
    wire [AW-1:0] rd_next = rrst ? {AW{1'b0}} : rbin_n[AW-1:0];   // rbin after this clock
    reg  [W-1:0]  rd_q;
    generate if (RD_REG != 0) begin : rd_reg
        always @(posedge rclk) rd_q <= mem[rd_next];
        assign rd_data = rd_q;
    end else begin : rd_async
        assign rd_data = mem[rbin[AW-1:0]];
    end endgenerate

`ifdef FORMAL
    // Proven by formal/run.sh for RD_REG = 0 and 1 (formal/fifo_props.v starts all pointers at 0
    // and drives both clocks, enables and data freely):
    //   occupancy  real pointers never differ by more than the depth: no overflow, no underflow
    //   views      each side's view of the other pointer lags the real one (full/empty are conservative)
    //   gray       Gray pointers match their counters and move one step per own-clock edge
    //   data       a word at a free address reads back unchanged until it is overwritten
    localparam [AW:0] DEPTH = 1 << AW;
    wire [AW:0] f_occ    = wbin - rbin;
    wire [AW:0] f_w_view = wbin - g2b(rgray_w2);
    wire [AW:0] f_r_view = g2b(wgray_r2) - rbin;
    wire [AW:0] f_r_lag  = rbin - g2b(rgray_w2);
    wire [AW:0] f_w_lag  = wbin - g2b(wgray_r2);
    wire [AW:0] f_r_lag1 = rbin - g2b(rgray_w1);         // first synchroniser stages: newer than the second
    wire [AW:0] f_w_lag1 = wbin - g2b(wgray_r1);
    wire [AW:0] f_age    = wbin - f_at;                  // writes since the watched word
    (* anyconst *) wire [AW-1:0] f_watch;
    reg         f_armed;
    reg [W-1:0] f_value;
    reg [AW:0]  f_at;
    always @(posedge wclk) if (!wrst && wr_en && !full && wbin[AW-1:0] == f_watch) begin
        f_armed <= 1'b1; f_value <= wr_data; f_at <= wbin;
    end
    always @* begin
        assert (f_occ <= DEPTH);
        assert (f_w_view <= DEPTH && f_w_view >= f_occ);
        assert (f_r_view <= f_occ);
        assert (f_r_lag <= DEPTH && f_w_lag <= DEPTH);
        assert (f_r_lag1 <= f_r_lag && f_w_lag1 <= f_w_lag);
        assert (wgray == ((wbin >> 1) ^ wbin));
        assert (rgray == ((rbin >> 1) ^ rbin));
        assert ($countones(wgray_n ^ wgray) <= 1);
        assert ($countones(rgray_n ^ rgray) <= 1);
        if (f_armed && !empty && rbin == f_at) assert (rd_data == f_value);
        // induction strengthening for the data property
        if (f_armed) begin
            assert (f_at[AW-1:0] == f_watch && f_age != 0 && f_age <= DEPTH);
            assert (mem[f_watch] == f_value);
        end
        // RD_REG = 1: once the first synchroniser stage has seen the word at the read pointer
        // written, the read register holds it
        if (RD_REG != 0 && g2b(wgray_r1) != rbin) assert (rd_q == mem[rbin[AW-1:0]]);
    end
`endif
endmodule
`default_nettype wire
