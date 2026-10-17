// TMDS symbols for the three channels: DVI 1.0, or HDMI with an AVI InfoFrame (HDMI = 1).
//
// DVI (HDMI = 0, the default): three tmds_encoder.v, control codes outside DE; one clock from the
// inputs to the symbols. This is what every build used until 2026-10-12.
//
// HDMI (HDMI = 1, build.sh HDMI=1): the video is delayed 10 clocks so that the undelayed DE can
// announce each active line. The 10 clocks before it carry the video preamble (8 clocks, CTL0 = 1)
// and the video guard band (2 clocks). After each vsync rising edge one data island is sent in the
// vertical blanking: preamble (8 clocks, CTL0 = CTL2 = 1), guard band (2), one packet (32 clocks of
// TERC4) and guard band (2). The packet is an AVI InfoFrame (type 82h, version 2, length 13): RGB,
// 16:9, active format as the picture, VIC 4 (720p60) or VIC 19 (720p50 while hz50 is high), no
// pixel repetition, and the quantization range the pixels carry: full with RGB_FULL = 1 (what
// ycbcr2rgb.v puts out), limited with RGB_FULL = 0, which then scales 0..255 to 16..235 (a sink
// that ignores the flag reads limited RGB right; 720p's default is limited either way).
// Header and subpackets carry BCH parity (G(x) = 1 + x^6 + x^7 + x^8, bits in transmission order).
// Tables and packet layout from HDMI 1.4: TERC4 (table 5-18), guard bands (5.2.2.1, 5.2.3.3),
// packet bit layout (figure 5-5), AVI InfoFrame (CEA-861). Compared with a decoder written from the
// same sections in sim/test_hdmi.py; not seen by a real sink.
// Unsigned arithmetic only (Apicula).
`default_nettype none
`ifndef HDMI
`define HDMI 0
`endif
module tmds_link #(
    parameter HDMI = `HDMI,
    parameter RGB_FULL = 1
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       de,
    input  wire       hsync,
    input  wire       vsync,
    input  wire [7:0] r,
    input  wire [7:0] g,
    input  wire [7:0] b,
    input  wire       hz50,          // the timing is 720p50 (VIC 19); else 720p60 (VIC 4)
    output wire [9:0] sym0,          // blue, with hsync/vsync
    output wire [9:0] sym1,          // green
    output wire [9:0] sym2           // red
);
    generate if (HDMI == 0) begin : dvi
        tmds_encoder enc_b (.clk(clk), .rst(rst), .de(de), .data(b), .ctrl({vsync, hsync}), .q(sym0));
        tmds_encoder enc_g (.clk(clk), .rst(rst), .de(de), .data(g), .ctrl(2'b00),          .q(sym1));
        tmds_encoder enc_r (.clk(clk), .rst(rst), .de(de), .data(r), .ctrl(2'b00),          .q(sym2));
    end else begin : hdmi
        localparam [9:0] GB_VIDEO_02 = 10'b1011001100;   // video guard band, channels 0 and 2
        localparam [9:0] GB_VIDEO_1  = 10'b0100110011;   // video guard band, channel 1
        localparam [9:0] GB_ISLAND   = 10'b0100110011;   // data island guard band, channels 1 and 2

        function [9:0] terc4(input [3:0] d);
            case (d)
                4'h0: terc4 = 10'b1010011100;  4'h1: terc4 = 10'b1001100011;
                4'h2: terc4 = 10'b1011100100;  4'h3: terc4 = 10'b1011100010;
                4'h4: terc4 = 10'b0101110001;  4'h5: terc4 = 10'b0100011110;
                4'h6: terc4 = 10'b0110001110;  4'h7: terc4 = 10'b0100111100;
                4'h8: terc4 = 10'b1011001100;  4'h9: terc4 = 10'b0100111001;
                4'hA: terc4 = 10'b0110011100;  4'hB: terc4 = 10'b1011000110;
                4'hC: terc4 = 10'b1010001110;  4'hD: terc4 = 10'b1001110001;
                4'hE: terc4 = 10'b0101100011;  default: terc4 = 10'b1011000011;
            endcase
        endfunction

        // BCH parity of the first n data bits, bit 0 sent first
        function [7:0] bch(input [55:0] data, input integer n);
            integer i;
            reg [7:0] s;
            begin
                s = 8'd0;
                for (i = 0; i < 56; i = i + 1)
                    if (i < n) s = (s >> 1) ^ ((s[0] ^ data[i]) ? 8'h83 : 8'h00);
                bch = s;
            end
        endfunction

        // ---- delay line: the outputs follow the inputs by 10 clocks (plus the encoders' one)
        reg [9:0] de_sr, hs_sr, vs_sr;
        reg [23:0] rgb_sr [0:9];
        integer k;
        always @(posedge clk) begin
            de_sr <= {de_sr[8:0], de};
            hs_sr <= {hs_sr[8:0], hsync};
            vs_sr <= {vs_sr[8:0], vsync};
            rgb_sr[0] <= {r, g, b};
            for (k = 1; k < 10; k = k + 1) rgb_sr[k] <= rgb_sr[k - 1];
            if (rst) begin de_sr <= 10'd0; hs_sr <= 10'd0; vs_sr <= 10'd0; end
        end
        wire       de_d = de_sr[9], hs_d = hs_sr[9], vs_d = vs_sr[9];
        wire [23:0] rgb_d = rgb_sr[9];
        // limited range: (c * 219 + 128) / 255 + 16, rounded; 257 = 2^16 / 255 rounded up, so the
        // shift does the division: the exact inverse of the standard (v - 16) * 255 / 219
        function [7:0] lim(input [7:0] c);
            reg [23:0] t;
            begin
                if (RGB_FULL != 0) lim = c;
                else begin
                    t = ({16'd0, c} * 24'd219 + 24'd128) * 24'd257;
                    lim = t[23:16] + 8'd16;
                end
            end
        endfunction
        wire [7:0] r_d = lim(rgb_d[23:16]), g_d = lim(rgb_d[15:8]), b_d = lim(rgb_d[7:0]);

        // ---- video lead-in: the undelayed DE rises 10 clocks before the delayed one
        reg       de_q;
        reg [3:0] vcnt;
        wire      de_rise = de && !de_q;
        wire [3:0] lead = de_rise ? 4'd10 : vcnt;             // clocks until the delayed DE rises
        wire      v_pre = lead >= 4'd3;                        // video preamble
        wire      v_gb  = lead == 4'd1 || lead == 4'd2;        // video guard band
        always @(posedge clk) begin
            de_q <= de;
            vcnt <= de_rise ? 4'd9 : (vcnt != 4'd0 ? vcnt - 4'd1 : 4'd0);
            if (rst) begin de_q <= 1'b0; vcnt <= 4'd0; end
        end

        // ---- data island after each delayed vsync rising edge: 1..8 preamble, 9..10 guard band,
        // 11..42 packet, 43..44 guard band
        reg       vs_q, hz50_l;
        reg [5:0] icnt;
        wire      vs_rise = vs_d && !vs_q;
        always @(posedge clk) begin
            vs_q <= vs_d;
            if (vs_rise) begin icnt <= 6'd1; hz50_l <= hz50; end
            else if (icnt != 6'd0) icnt <= (icnt == 6'd44) ? 6'd0 : icnt + 6'd1;
            if (rst) begin vs_q <= 1'b0; icnt <= 6'd0; hz50_l <= 1'b0; end
        end
        wire       i_pre  = icnt >= 6'd1 && icnt <= 6'd8;
        wire       i_gb   = icnt == 6'd9 || icnt == 6'd10 || icnt == 6'd43 || icnt == 6'd44;
        wire       i_data = icnt >= 6'd11 && icnt <= 6'd42;
        wire [4:0] px     = icnt - 6'd11;                     // packet clock 0..31

        // ---- the AVI InfoFrame
        wire [7:0] pb1 = 8'h10;                                // RGB, active format present, no bars or scan info
        wire [7:0] pb2 = 8'h28;                                // no colorimetry, 16:9, active format as the picture
        wire [7:0] pb3 = (RGB_FULL != 0) ? 8'h08 : 8'h04;      // quantization range full / limited
        wire [7:0] pb4 = hz50_l ? 8'd19 : 8'd4;                // VIC
        wire [7:0] pb5 = 8'h00;                                // no pixel repetition
        wire [7:0] pb0 = 8'h00 - (8'h82 + 8'h02 + 8'h0D + pb1 + pb2 + pb3 + pb4 + pb5);   // checksum
        wire [23:0] hdr = {8'h0D, 8'h02, 8'h82};
        wire [31:0] hdr_b = {bch({32'd0, hdr}, 24), hdr};
        wire [55:0] sp0 = {8'h00, pb5, pb4, pb3, pb2, pb1, pb0};      // PB0..PB6 (PB6 = 0)
        wire [63:0] s0 = {bch(sp0, 56), sp0};
        wire [63:0] s1 = {bch(56'd0, 56), 56'd0};                     // PB7..PB13: no bar data
        wire [63:0] s2 = s1, s3 = s1;                                  // PB14..PB27: unused
        wire [3:0] d0 = {px != 5'd0, hdr_b[px], vs_d, hs_d};
        wire [3:0] d1 = {s3[{px, 1'b0}], s2[{px, 1'b0}], s1[{px, 1'b0}], s0[{px, 1'b0}]};
        wire [3:0] d2 = {s3[{px, 1'b1}], s2[{px, 1'b1}], s1[{px, 1'b1}], s0[{px, 1'b1}]};

        // ---- encoders on the delayed stream; preambles as control codes, the rest overrides their output
        wire [9:0] q0, q1, q2;
        wire [1:0] ctl01 = (v_pre || i_pre) ? 2'b01 : 2'b00;   // {CTL1, CTL0}
        wire [1:0] ctl23 = i_pre ? 2'b01 : 2'b00;              // {CTL3, CTL2}
        tmds_encoder enc_b (.clk(clk), .rst(rst), .de(de_d), .data(b_d), .ctrl({vs_d, hs_d}), .q(q0));
        tmds_encoder enc_g (.clk(clk), .rst(rst), .de(de_d), .data(g_d), .ctrl(ctl01),        .q(q1));
        tmds_encoder enc_r (.clk(clk), .rst(rst), .de(de_d), .data(r_d), .ctrl(ctl23),        .q(q2));
        reg       ov;
        reg [9:0] o0, o1, o2;
        always @(posedge clk) begin
            ov <= v_gb || i_gb || i_data;
            if (v_gb)        begin o0 <= GB_VIDEO_02;              o1 <= GB_VIDEO_1; o2 <= GB_VIDEO_02; end
            else if (i_gb)   begin o0 <= terc4({2'b11, vs_d, hs_d}); o1 <= GB_ISLAND;  o2 <= GB_ISLAND;  end
            else             begin o0 <= terc4(d0);                o1 <= terc4(d1);  o2 <= terc4(d2);   end
            if (rst) ov <= 1'b0;
        end
        assign sym0 = ov ? o0 : q0;
        assign sym1 = ov ? o1 : q1;
        assign sym2 = ov ? o2 : q2;
    end endgenerate
endmodule
`default_nettype wire
