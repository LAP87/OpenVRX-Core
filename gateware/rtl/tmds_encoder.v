// DVI 1.0 TMDS encoder (8b/10b with running-disparity DC balance).
// Checked against a Python implementation of the DVI spec in
// gateware/sim/test_video.py.
`default_nettype none

module tmds_encoder (
    input  wire       clk,
    input  wire       rst,
    input  wire       de,        // 1 = video data, 0 = control period
    input  wire [7:0] data,
    input  wire [1:0] ctrl,      // {c1, c0}: {vsync, hsync} on channel 0
    output reg  [9:0] q
);
    function [3:0] ones8(input [7:0] x);
        integer i;
        begin
            ones8 = 0;
            for (i = 0; i < 8; i = i + 1) ones8 = ones8 + x[i];
        end
    endfunction

    // stage 1: transition minimisation (XOR or XNOR chain)
    wire [3:0] n1d    = ones8(data);
    wire       use_xnor = (n1d > 4) || (n1d == 4 && data[0] == 1'b0);
    wire [8:0] qm;
    assign qm[0] = data[0];
    genvar i;
    generate
        for (i = 1; i < 8; i = i + 1) begin : chain
            assign qm[i] = use_xnor ? ~(qm[i-1] ^ data[i]) : (qm[i-1] ^ data[i]);
        end
    endgenerate
    assign qm[8] = ~use_xnor;

    // stage 2: DC balance
    // cnt is the running disparity in 6-bit two's complement, kept in plain
    // (unsigned) vectors: add/subtract give the same bits either way, and the
    // sign is tested on bit 5 instead of with signed compares, which Apicula
    // has been seen to miscompile (otanl/CVBS2HDMI).
    wire [3:0] n1q = ones8(qm[7:0]);
    wire [3:0] n0q = 4'd8 - n1q;
    reg  [5:0] cnt;                         // running disparity
    wire [5:0] diff = {2'b00, n1q} - {2'b00, n0q};
    wire       cnt_neg = cnt[5];
    wire       cnt_pos = !cnt[5] && cnt != 6'd0;

    always @(posedge clk) begin
        if (rst) begin
            cnt <= 0;
            q   <= 10'b1101010100;
        end else if (!de) begin
            cnt <= 0;
            case (ctrl)
                2'b00: q <= 10'b1101010100;
                2'b01: q <= 10'b0010101011;
                2'b10: q <= 10'b0101010100;
                default: q <= 10'b1010101011;
            endcase
        end else if (cnt == 0 || n1q == 4) begin
            q   <= {~qm[8], qm[8], qm[8] ? qm[7:0] : ~qm[7:0]};
            cnt <= qm[8] ? cnt + diff : cnt - diff;
        end else if ((cnt_pos && n1q > 4) || (cnt_neg && n1q < 4)) begin
            q   <= {1'b1, qm[8], ~qm[7:0]};
            cnt <= cnt + {4'b0, qm[8], 1'b0} - diff;
        end else begin
            q   <= {1'b0, qm[8], qm[7:0]};
            cnt <= cnt - {4'b0, ~qm[8], 1'b0} + diff;
        end
    end
endmodule
`default_nettype wire
