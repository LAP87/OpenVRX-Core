// SDRAM read self-test, run once after the controller's start-up (init_done):
// two 8-word bursts are written to a row the field store never uses, then each
// is read back at the sample points T_RCD+CAS, +1 and +2 (4, 5 and 6 with the
// defaults; sdram_burst.v rd_sample). ok[i] is 1 when sample point T_RCD+CAS+i
// returned both bursts word for word. In a burst every word differs from its
// neighbours, so a point one clock early or late fails, and at most one point
// passes; on a working board that is the build's own read point. Then done
// goes high and stays high until reset, and the request port belongs to the
// field store (fb_backend.v holds fb_sdram in reset until then).
//
// Why: the read window depends on where each build puts its DQ flops (hub
// docs/design/2026-10-21/LOGIKGRANSKNING.md F1). M2a sweeps phases and sample
// points in its own build; this test shows in every build of M4 and M6 whether
// the read point works there (M4: LED 1/2, M6: the log line).
//
// Address: field buffer 3, line 1023, words 0..15 (fb_sdram.v's map: bank 3,
// row 2046). Fields have at most 625 lines. Data: burst 0 has a walking one in
// every byte (word k = 01010101h << k), burst 1 the word address and its
// complement as memtest_core.v. A read that is not word for word right,
// including an undefined one in simulation, fails.
`default_nettype none
module sdram_selftest #(
    parameter [3:0]  T_RCD = 4'd2,
    parameter [3:0]  CAS   = 4'd2,
    parameter [20:0] ADDR  = {2'd3, 10'd1023, 9'd0}
) (
    input  wire        clk,
    input  wire        rst,                 // synchronous, active high
    input  wire        init_done,
    output wire        req_valid,
    output wire        req_write,
    output wire [20:0] req_addr,
    output wire [4:0]  rd_sample,
    input  wire        req_ready,
    output wire [31:0] wdata,
    input  wire        wdata_take,
    input  wire [31:0] rdata,
    input  wire        rdata_valid,
    output reg         done,
    output reg  [2:0]  ok                   // ok[i]: sample point T_RCD + CAS + i read both bursts right
);
    localparam S_WAIT = 3'd0, S_WREQ = 3'd1, S_WDATA = 3'd2, S_RREQ = 3'd3, S_RDATA = 3'd4, S_DONE = 3'd5;
    reg  [2:0] st;
    reg        b;                           // burst 0 or 1
    reg  [2:0] k;                           // word in the burst
    reg  [1:0] pt;                          // sample point T_RCD + CAS + pt
    reg        bad;                         // a word of this sample point was wrong

    wire [20:0] word_addr = ADDR + {17'd0, b, k};
    wire [31:0] want = b ? {~word_addr[10:0], word_addr} : (32'h01010101 << k);
    reg         word_ok;                    // if/else: an undefined read (X in simulation) is not ok
    always @(*) begin
        word_ok = 1'b0;
        if (rdata == want) word_ok = 1'b1;
    end
    assign req_valid = (st == S_WREQ) || (st == S_RREQ);
    assign req_write = (st == S_WREQ);
    assign req_addr  = ADDR + {17'd0, b, 3'd0};
    assign rd_sample = T_RCD + CAS + {3'd0, pt};
    assign wdata     = want;

    always @(posedge clk) begin
        case (st)
        S_WAIT:  if (init_done) begin b <= 1'b0; k <= 3'd0; pt <= 2'd0; bad <= 1'b0; st <= S_WREQ; end
        S_WREQ:  if (req_ready) st <= S_WDATA;
        S_WDATA: if (wdata_take) begin
            k <= k + 3'd1;
            if (k == 3'd7) begin b <= ~b; st <= b ? S_RREQ : S_WREQ; end
        end
        S_RREQ:  if (req_ready) st <= S_RDATA;
        S_RDATA: if (rdata_valid) begin
            if (!word_ok) bad <= 1'b1;
            k <= k + 3'd1;
            if (k == 3'd7) begin
                b <= ~b;
                st <= S_RREQ;
                if (b) begin                                       // both bursts read at this point
                    ok[pt] <= !bad && word_ok;
                    bad <= 1'b0;
                    pt <= pt + 2'd1;
                    if (pt == 2'd2) st <= S_DONE;
                end
            end
        end
        S_DONE:  done <= 1'b1;
        default: st <= S_WAIT;
        endcase
        if (rst) begin st <= S_WAIT; done <= 1'b0; ok <= 3'b000; end
    end
endmodule
`default_nettype wire
