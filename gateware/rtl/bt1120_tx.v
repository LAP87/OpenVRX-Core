// BT.1120-style 16-bit YCbCr 4:2:2 output with embedded sync (to an HDMI
// transmitter such as LT8618SX): Y lane and C lane (Cb on even, Cr on odd
// pixels). Timing codes FF 00 00 XY on both lanes: EAV in the 4 clocks after
// active video, SAV in the last 4 clocks of horizontal blanking, every line.
// XY = 1 F V H P3..P0 (F = 0, progressive). Our timing rows are "active then
// blanking", so both codes in row y belong to the line whose active video
// follows them: V = 1 when row y+1 is a vertical blanking row.
//
// x/y come straight from video_timing; the pixel data arrives LAT clocks later
// (fb_display's pipeline), so the code positions are delayed by LAT as well.
// No line-number or CRC words (SMPTE 274M LN/CRC) — not known whether the
// LT8618SX needs them; add if the chip's video check fails.
`default_nettype none
module bt1120_tx #(
    parameter H_ACTIVE = 1920, H_TOTAL = 2200,
    parameter V_ACTIVE = 1080, V_TOTAL = 1125,
    parameter LAT = 5
) (
    input  wire        clk,
    input  wire [11:0] x, y,
    input  wire [7:0]  yy, cb, cr,         // pixel LAT clocks after its x/y (blank levels outside the picture)
    output reg  [7:0]  out_y,
    output reg  [7:0]  out_c
);
    function [7:0] xy(input f, input v, input h);
        xy = {1'b1, f, v, h, v ^ h, f ^ h, f ^ v, f ^ v ^ h};
    endfunction

    // what to send at this x/y: 0 = pixel/blank data, 1..4 = code word 0..3
    wire [11:0] y_next = (y == V_TOTAL - 1) ? 12'd0 : y + 12'd1;
    wire        v_next = (y_next >= V_ACTIVE);
    wire        in_eav = (x >= H_ACTIVE) && (x < H_ACTIVE + 4);
    wire        in_sav = (x >= H_TOTAL - 4);
    wire [1:0]  word   = in_eav ? x - H_ACTIVE : x - (H_TOTAL - 4);
    reg  [7:0]  code;
    always @* case (word)
        2'd0: code = 8'hFF;
        2'd1: code = 8'h00;
        2'd2: code = 8'h00;
        default: code = xy(1'b0, v_next, in_eav);
    endcase
    wire       is_code = in_eav || in_sav;
    wire       active  = (x < H_ACTIVE) && (y < V_ACTIVE);

    reg [LAT-1:0] c_p, a_p, odd_p;
    reg [7:0]     code_p [0:LAT-1];
    integer i;
    always @(posedge clk) begin
        c_p <= {c_p[LAT-2:0], is_code};
        a_p <= {a_p[LAT-2:0], active};
        odd_p <= {odd_p[LAT-2:0], x[0]};
        code_p[0] <= code;
        for (i = 1; i < LAT; i = i + 1) code_p[i] <= code_p[i - 1];
    end
    always @(posedge clk) begin
        if (c_p[LAT-1])      begin out_y <= code_p[LAT-1]; out_c <= code_p[LAT-1]; end
        else if (a_p[LAT-1]) begin out_y <= yy; out_c <= odd_p[LAT-1] ? cr : cb; end
        else                 begin out_y <= 8'h10; out_c <= 8'h80; end
    end
endmodule
`default_nettype wire
