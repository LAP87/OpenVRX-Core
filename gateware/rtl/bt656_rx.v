// BT.656 receiver + per-line metrics (8-bit, embedded sync, 27 MHz byte clock).
//
// Bit-exact hardware counterpart of gateware/model/bt656.py `Receiver`: for the
// same byte stream it reports the same per-line records (checked by
// gateware/sim/test_bt656_rx.py against gateware/vectors/*.expected.json).
//
// Timing reference: FF 00 00 XY, XY = 1 F V H P3 P2 P1 P0. Single-bit errors
// in XY are corrected, others flagged. Active bytes pass through a 3-byte
// delay so the FF 00 00 of the following EAV can be dropped before they are
// counted, exactly like the model deletes them.
`default_nettype none

module bt656_rx (
    input  wire        clk,            // TVP5150 SCLK (27 MHz)
    input  wire        rst,
    input  wire [7:0]  d,              // YOUT[7:0]

    // committed active-video bytes (Cb Y Cr Y ...), for the line buffer
    output reg         px_valid,
    output reg  [7:0]  px_data,
    output reg  [10:0] px_index,       // 0..1439 within the line
    output reg         px_field,
    output reg  [9:0]  px_line,        // active line within the field (same numbering as rec_line)

    // one record per active line, pulsed at the EAV that ends it
    output reg         rec_valid,
    output reg         rec_field,
    output reg  [9:0]  rec_line,       // active line within its field
    output reg  [15:0] rec_length,     // bytes between EAVs (0 = unknown)
    output reg  [10:0] rec_active,     // active bytes
    output reg  [7:0]  rec_xy_corrected,
    output reg  [7:0]  rec_xy_bad,
    output reg  [19:0] rec_hf          // sum |Y[n]-Y[n-1]|
);
    // ---- XY decode with single-error correction -------------------------
    function [7:0] xy_code(input f, input v, input h);
        xy_code = {1'b1, f, v, h, v ^ h, f ^ h, f ^ v, f ^ v ^ h};
    endfunction

    function [3:0] popcount8(input [7:0] x);
        integer i;
        begin
            popcount8 = 0;
            for (i = 0; i < 8; i = i + 1) popcount8 = popcount8 + x[i];
        end
    endfunction

    // returns {status[1:0], f, v, h}; status 0 = ok, 1 = corrected, 2 = bad
    function [4:0] xy_decode(input [7:0] b);
        integer k, hits;
        reg [7:0] c;
        reg [2:0] fvh;
        begin
            xy_decode = {2'd2, 3'b000};
            hits = 0;
            for (k = 0; k < 8; k = k + 1) begin
                c = xy_code(k[2], k[1], k[0]);
                if (c == b)
                    xy_decode = {2'd0, k[2], k[1], k[0]};
            end
            if (xy_decode[4:3] == 2'd2) begin
                for (k = 0; k < 8; k = k + 1) begin
                    c = xy_code(k[2], k[1], k[0]);
                    if (popcount8(c ^ b) == 1) begin
                        hits = hits + 1;
                        fvh = k[2:0];
                    end
                end
                if (hits == 1)
                    xy_decode = {2'd1, fvh};
            end
        end
    endfunction

    // ---- state ----------------------------------------------------------
    reg  [1:0]  state;          // matched bytes of FF 00 00
    reg  [15:0] pos;            // bytes since last EAV
    reg         seen_eav;
    reg         in_active;
    reg  [7:0]  dl0, dl1, dl2;  // 3-byte delay of active bytes (dl2 oldest)
    reg  [2:0]  dl_v;
    reg  [11:0] act_count;      // committed active bytes this line
    reg  [7:0]  prev_y;
    reg         have_prev_y;
    reg  [19:0] hf;
    reg  [7:0]  xy_corr_cnt, xy_bad_cnt;
    // line numbering counts line starts (see model/bt656.py): an active SAV, or an EAV with
    // no SAV since the previous EAV when that previous EAV said the line was active
    reg         ev_valid, ev_field;      // last line start
    reg  [9:0]  ev_line;
    reg         sav_since_eav;
    reg         last_eav_valid, last_eav_f, last_eav_v;

    wire [15:0] pos_n = (pos == 16'hFFFF) ? pos : pos + 16'd1;
    wire [4:0]  dec   = xy_decode(d);
    wire [1:0]  st    = dec[4:3];
    wire        f_d = dec[2], v_d = dec[1], h_d = dec[0];

    // commit the oldest delayed byte (used both when shifting and when not)
    task commit_oldest;
        begin
            px_valid <= 1'b1;
            px_data  <= dl2;
            px_index <= act_count[10:0];
            if (act_count[0]) begin                 // odd index = luma
                if (have_prev_y)
                    hf <= hf + ((dl2 > prev_y) ? dl2 - prev_y : prev_y - dl2);
                prev_y      <= dl2;
                have_prev_y <= 1'b1;
            end
            act_count <= act_count + 12'd1;
        end
    endtask

    always @(posedge clk) begin
        px_valid  <= 1'b0;
        rec_valid <= 1'b0;
        if (rst) begin
            state <= 0; pos <= 0; seen_eav <= 0; in_active <= 0;
            dl_v <= 0; act_count <= 0; hf <= 0; have_prev_y <= 0; prev_y <= 0;
            xy_corr_cnt <= 0; xy_bad_cnt <= 0;
            ev_valid <= 0; ev_field <= 0; ev_line <= 0; sav_since_eav <= 0;
            last_eav_valid <= 0; last_eav_f <= 0; last_eav_v <= 0;
        end else begin
            pos <= pos_n;
            if (state == 2'd3) begin
                // ---- XY byte ----
                state <= 2'd0;
                if (st == 2'd2) begin
                    xy_bad_cnt <= xy_bad_cnt + 8'd1;
                    in_active  <= 1'b0;
                    dl_v       <= 3'b000;
                end else begin
                    // the 3 delayed bytes are this timing code's FF 00 00: drop them
                    dl_v <= 3'b000;
                    if (h_d) begin                                  // EAV
                        if (in_active) begin
                            // the line's field is the F bit of its own SAV (px_field): the EAV
                            // ending a line already belongs to the next line
                            rec_valid        <= 1'b1;
                            rec_field        <= px_field;
                            rec_line         <= px_line;
                            rec_length       <= seen_eav ? pos_n : 16'd0;
                            rec_active       <= act_count[10:0];
                            rec_xy_corrected <= xy_corr_cnt + (st == 2'd1);
                            rec_xy_bad       <= xy_bad_cnt;
                            rec_hf           <= hf;
                            xy_corr_cnt      <= 0;
                            xy_bad_cnt       <= 0;
                        end else begin
                            if (st == 2'd1) xy_corr_cnt <= xy_corr_cnt + 8'd1;
                            if (!sav_since_eav && last_eav_valid && !last_eav_v) begin
                                // the line that began at the previous EAV lost its SAV: count it
                                ev_line  <= (ev_valid && last_eav_f == ev_field) ? ev_line + 10'd1 : 10'd0;
                                ev_field <= last_eav_f;
                                ev_valid <= 1'b1;
                            end
                        end
                        sav_since_eav  <= 1'b0;
                        last_eav_valid <= 1'b1;
                        last_eav_f     <= f_d;
                        last_eav_v     <= v_d;
                        in_active <= 1'b0;
                        seen_eav  <= 1'b1;
                        pos       <= 16'd0;
                    end else begin                                  // SAV
                        if (st == 2'd1) xy_corr_cnt <= xy_corr_cnt + 8'd1;
                        in_active   <= ~v_d;
                        act_count   <= 0;
                        hf          <= 0;
                        have_prev_y <= 1'b0;
                        px_field    <= f_d;
                        sav_since_eav <= 1'b1;
                        if (!v_d) begin                             // an active line starts
                            px_line  <= (ev_valid && f_d == ev_field) ? ev_line + 10'd1 : 10'd0;
                            ev_line  <= (ev_valid && f_d == ev_field) ? ev_line + 10'd1 : 10'd0;
                            ev_field <= f_d;
                            ev_valid <= 1'b1;
                        end else ev_valid <= 1'b0;                  // VBI also delimits constant-F (240p/288p) pictures
                    end
                end
            end else begin
                // ---- ordinary byte: preamble matcher ----
                if (state == 2'd0 && d == 8'hFF)                 state <= 2'd1;
                else if ((state == 2'd1 || state == 2'd2) && d == 8'h00) state <= state + 2'd1;
                else                                             state <= (d == 8'hFF) ? 2'd1 : 2'd0;
                // ---- active bytes through the 3-deep delay ----
                if (in_active) begin
                    if (dl_v[2]) commit_oldest;
                    dl2 <= dl1; dl1 <= dl0; dl0 <= d;
                    dl_v <= {dl_v[1:0], 1'b1};
                end
            end
        end
    end
endmodule
`default_nettype wire
