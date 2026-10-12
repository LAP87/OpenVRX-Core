// Field store in SDRAM (SDRAM clock domain): four field buffers.
//
// Writer: pops tagged words {field, line, idx, data} from the input FIFO,
// groups them into aligned 8-word bursts and writes them to the current
// buffer. A line counts as stored when its last group (words 352..359) has
// been written and its word 0 was taken in the same field; that sets its bit
// in `ok`. Lines come whole from the mixer, except the one the writer joins in
// the middle after reset or LOW: its first words were never written, and it
// is not stored (until 2026-10-12 it was, and a frame showing the joined field
// read those words from the SDRAM; test_fuzz_chain seeds 1437, 1445). When a new field starts (field bit
// flips or the line number goes backwards) the buffer is published and the
// next one is chosen: never the one just published, the one on screen or its
// fallback. The `ok` bits of the new buffer are cleared before words are taken
// again (128 cycles). The field the writer joined after reset (its first word
// was not the field's first line) is not published: its missing lines have no
// fallback field, and the buffer holds whatever was there before. The writer
// moves to a free buffer and starts over with the next field.
//
// Frame start (the display's first line request of a frame) decides what the
// frame shows:
//   * the field being written, if the writer has completed enough lines for
//     the display not to catch up with it: RT_NTSC lines, or RT_PAL for fields
//     of more than RT_SPLIT lines (a 60 Hz output reads those faster than they
//     arrive), plus RT_HYST lines if the previous frame showed a finished field;
//   * else the latest published field.
// The fallback is the field before the one shown. Both are fixed for the frame.
//
// Line requests: a line that is stored in the shown field is read from it. A
// line that is not is replaced by the line above for up to two lines in a row,
// then by the same line of the fallback field if that one is stored, else by
// the line above again. Where there is no line above in this frame and no
// stored line in the fallback (a missing first line of the first field), a
// black line is written into the line buffer without reading the SDRAM. So the
// display never shows a line that was not written as a whole, whatever the
// writer is doing.
//
// Line count: the display scales by `pub_lines`, the smaller of the last two
// fields' line counts when they differ by at most 2 (243/244, 287/288). A
// field that was cut short does not change it.
//
// `frame_low`: the field shown is the lower one of an interlaced pair
// (field_phase.v; decided from arrival times, not from the field bit).
//
// Word address map (21 bits): buf * 2^19 + line * 512 + idx (idx < 360), so
// 8-word groups never cross an SDRAM row and four buffers fill 2^21 words.
`default_nettype none
module fb_sdram #(
    parameter RT_EN    = 1,
    parameter RT_NTSC  = 4,
    parameter RT_PAL   = 44,
    parameter RT_HYST  = 16,
    parameter RT_SPLIT = 270,
    parameter REF_LINE = 1               // field_phase.v times the first word of this line (the writer is idle then)
) (
    input  wire        clk,
    input  wire        resetn,

    input  wire        in_empty,
    input  wire [51:0] in_data,          // {field, line[9:0], idx[8:0], data[31:0]}
    output reg         in_pop,

    input  wire        fetch_req,        // pulse (synchronised into this domain)
    input  wire        fetch_first,      // with fetch_req: first request of an output frame
    input  wire [9:0]  fetch_line,
    input  wire [1:0]  fetch_slot,
    output reg         lb_we,
    output reg  [10:0] lb_addr,          // {slot, idx}
    output reg  [31:0] lb_data,

    output reg         pub_valid,        // a field was published
    output reg  [9:0]  pub_lines,
    output reg         frame_low,

    output reg         req_valid,
    output reg         req_write,
    output reg  [20:0] req_addr,
    input  wire        req_ready,
    output wire [31:0] wdata,
    input  wire        wdata_take,
    input  wire [31:0] rdata,
    input  wire        rdata_valid
);
    wire        e_field = in_data[51];
    wire [9:0]  e_line  = in_data[50:41];
    wire [8:0]  e_idx   = in_data[40:32];
    wire [31:0] e_data  = in_data[31:0];

    function [1:0] pick_free(input [1:0] a, input [1:0] b, input [1:0] c);   // lowest buffer that is none of a, b, c
        begin
            if (2'd0 != a && 2'd0 != b && 2'd0 != c) pick_free = 2'd0;
            else if (2'd1 != a && 2'd1 != b && 2'd1 != c) pick_free = 2'd1;
            else if (2'd2 != a && 2'd2 != b && 2'd2 != c) pick_free = 2'd2;
            else pick_free = 2'd3;
        end
    endfunction

    function [20:0] word_addr(input [1:0] b, input [9:0] line, input [5:0] grp);
        word_addr = {b, 19'd0} + {2'b00, line, 9'd0} + {12'd0, grp, 3'd0};
    endfunction

    // writer state
    reg [1:0]  cur_buf;
    reg        cur_field, have_field;
    reg        joined;                   // the current field is the one the writer joined after reset
    reg [9:0]  last_line, max_line;
    reg [31:0] grp [0:7];
    reg [7:0]  grp_mask;
    reg [9:0]  grp_line;
    reg [5:0]  grp_base;
    reg        grp_ready, writing;
    reg [2:0]  wr_k;
    assign wdata = grp[wr_k];
    reg        whole_v;                  // word 0 of line `whole_line` was taken in this field
    reg [9:0]  whole_line;
    reg        done_any;                 // a line of the current field is stored
    reg [9:0]  max_done;                 // the highest such line
    reg        sweeping;
    reg [6:0]  sweep_i;
    reg        mk_have;                  // `ok` byte of the lines being written (lines only go up)
    reg [6:0]  mk_grp;
    reg [7:0]  mk_bits;

    // published fields, newest first
    reg [1:0]  latest, older;
    reg        latest_v, older_v;
    reg [3:0]  low_of;                   // per buffer: lower field
    reg [9:0]  n1;                       // line count of the previous field
    reg        n1_v;

    // what the frame shows
    reg [1:0]  show_buf, prev_buf;
    reg        prev_ok, rt_prev;

    // fetcher state
    reg [1:0]  look;                     // 1..3: looking up `ok`, see below
    reg        fetching, rd_inflight;
    reg [1:0]  f_buf, f_slot;
    reg [9:0]  f_line, f_src;
    reg [5:0]  f_burst;
    reg [8:0]  f_idx;
    reg        ok_s;
    reg        f_blank;                  // this fetch writes a black line instead of reading the SDRAM
    localparam [31:0] BLACK = 32'h10801080;   // {Y1, Cr, Y0, Cb} = 16, 128, 16, 128
    reg        rep_v;                    // the source of the line fetched last in this frame
    reg [1:0]  rep_buf;
    reg [9:0]  rep_line;
    reg [1:0]  miss;                     // lines in a row missing from the shown field (saturates)

    // stored-line bits: 4 buffers x 1024 lines, 8 lines per byte. A byte that is read in the
    // cycle it is written comes from the write (what a block RAM returns then is not defined).
    reg        ok_we, fw_hit;
    reg [8:0]  ok_wa, ok_ra;
    reg [7:0]  ok_wd, fw_data;
    wire [7:0] ok_q;
    dual_clock_ram #(.DEPTH(512), .AW(9), .W(8)) okram (
        .wclk(clk), .we(ok_we), .waddr(ok_wa), .wdata(ok_wd), .rclk(clk), .raddr(ok_ra), .rdata(ok_q));
    always @(posedge clk) begin fw_hit <= ok_we && ok_wa == ok_ra; fw_data <= ok_wd; end
    wire [7:0] ok_rd = fw_hit ? fw_data : ok_q;

    wire new_field  = e_field != cur_field || e_line < last_line;
    wire breaks_grp = (grp_mask != 0) && (e_line != grp_line || e_idx[8:3] != grp_base);
    wire look_in    = resetn && !sweeping && !grp_ready && !in_empty && !in_pop;   // the writer looks at the FIFO head
    wire first_word = look_in && !have_field;
    wire field_end  = look_in && have_field && new_field && grp_mask == 0;
    wire publish    = field_end && !joined;
    wire discard    = field_end && joined;
    wire take       = look_in && have_field && !new_field && !breaks_grp;
    wire stored     = resetn && writing && wdata_take && wr_k == 3'd7 && grp_base == 6'd44 &&   // a line is complete
                      whole_v && whole_line == grp_line;                                     // from its word 0
    wire ph_low;
    field_phase phase (.clk(clk), .rst(!resetn), .nf(first_word || field_end),
                       .at_ref(take && e_line == REF_LINE && e_idx == 9'd0),
                       .low(ph_low), .low_now(), .il(), .early(), .dly());
    wire [9:0] n_now = max_line + 10'd1;
    wire [9:0] n_gap = (n_now > n1) ? n_now - n1 : n1 - n_now;

    // frame decision, valid in the cycle a first request is accepted
    wire [10:0] thr0   = (pub_lines > RT_SPLIT) ? RT_PAL : RT_NTSC;
    wire [10:0] thr    = rt_prev ? thr0 : thr0 + RT_HYST;
    wire        rt_now = (RT_EN != 0) && have_field && done_any && ({1'b0, max_done} + 11'd1 >= thr);
    wire        accept = fetch_req && !fetching && look == 2'd0;
    wire        first  = accept && fetch_first;
    wire        d_cur  = rt_now || !latest_v;                 // show the buffer being written
    wire [1:0]  s_dec  = d_cur ? cur_buf : latest;
    wire [1:0]  p_dec  = rt_now ? latest : older;
    wire        pok_dec = rt_now ? latest_v : (latest_v && older_v);
    wire [1:0]  s_n    = first ? s_dec : show_buf;
    wire [1:0]  p_n    = first ? p_dec : prev_buf;
    wire [1:0]  nxt    = pick_free(cur_buf, s_n, p_n);

    wire [7:0]  mark_bits = ((mk_have && mk_grp == grp_line[9:3]) ? mk_bits : 8'd0) | (8'd1 << grp_line[2:0]);

    integer i;
    always @(posedge clk) begin
        in_pop    <= 1'b0;
        pub_valid <= 1'b0;
        lb_we     <= 1'b0;
        ok_we     <= 1'b0;
        if (!resetn) begin
            cur_buf <= 0; have_field <= 0; joined <= 0; grp_mask <= 0; grp_ready <= 0; writing <= 0;
            last_line <= 0; max_line <= 0; fetching <= 0; rd_inflight <= 0; req_valid <= 0;
            done_any <= 0; max_done <= 0; sweeping <= 0; mk_have <= 0; whole_v <= 0;
            latest <= 0; older <= 0; latest_v <= 0; older_v <= 0; low_of <= 0; n1_v <= 0; pub_lines <= 0;
            show_buf <= 0; prev_buf <= 0; prev_ok <= 0; rt_prev <= 0; frame_low <= 0;
            look <= 0; rep_v <= 0; miss <= 0; f_blank <= 0;
        end else begin
            // ---- writer: take words from the FIFO ----
            if (sweeping) begin
                ok_we <= 1'b1; ok_wa <= {cur_buf, sweep_i}; ok_wd <= 8'd0;
                sweep_i <= sweep_i + 7'd1;
                if (&sweep_i) sweeping <= 1'b0;
            end else if (look_in) begin
                if (first_word) begin
                    have_field <= 1'b1; cur_field <= e_field; joined <= 1'b1;
                    sweeping <= 1'b1; sweep_i <= 0; whole_v <= 1'b0;
                end else if (new_field || breaks_grp) begin
                    if (grp_mask != 0) grp_ready <= 1'b1;          // flush the open group first
                    else if (joined) begin                         // the joined field: drop it, move on
                        joined <= 1'b0; cur_field <= e_field; cur_buf <= nxt;
                        last_line <= 0; max_line <= 0; done_any <= 1'b0; max_done <= 0;
                        sweeping <= 1'b1; sweep_i <= 0; mk_have <= 1'b0; whole_v <= 1'b0;
                    end else begin                                 // publish, move on
                        pub_valid <= 1'b1;
                        if (!n1_v) pub_lines <= n_now;
                        else if (n_gap <= 10'd2) pub_lines <= (n_now < n1) ? n_now : n1;
                        n1 <= n_now; n1_v <= 1'b1;
                        older <= latest; older_v <= latest_v && (nxt != latest);
                        latest <= cur_buf; latest_v <= 1'b1;
                        low_of[cur_buf] <= ph_low;
                        cur_buf   <= nxt;
                        cur_field <= e_field;
                        last_line <= 0; max_line <= 0; done_any <= 1'b0; max_done <= 0;
                        sweeping <= 1'b1; sweep_i <= 0; mk_have <= 1'b0; whole_v <= 1'b0;
                    end
                end else begin
                    in_pop <= 1'b1;
                    grp[e_idx[2:0]]      <= e_data;
                    grp_mask[e_idx[2:0]] <= 1'b1;
                    grp_line  <= e_line;
                    grp_base  <= e_idx[8:3];
                    last_line <= e_line;
                    if (e_idx == 9'd0) begin whole_v <= 1'b1; whole_line <= e_line; end
                    if (e_line > max_line) max_line <= e_line;
                    if (e_idx[2:0] == 3'd7) grp_ready <= 1'b1;
                end
            end
            // pad holes of a closed group with black. They only occur when the writer starts in the
            // middle of a line (after reset or LOW), in the field it joined, which is not published.
            // (grp[0] was used until 2026-10-07: never written after reset in LOW, it sent X to the SDRAM.)
            if (grp_ready && !writing && grp_mask != 8'hFF)
                for (i = 0; i < 8; i = i + 1)
                    if (!grp_mask[i]) begin grp[i] <= BLACK; grp_mask[i] <= 1'b1; end

            // ---- fetcher: frame decision, where to read the line from, store read data ----
            if (accept) begin
                look <= 2'd1; f_line <= fetch_line; f_slot <= fetch_slot;
                ok_ra <= {s_n, fetch_line[9:3]};
                if (first) begin
                    show_buf <= s_dec; prev_buf <= p_dec; prev_ok <= pok_dec; rt_prev <= rt_now;
                    frame_low <= d_cur ? ph_low : low_of[latest];
                    rep_v <= 1'b0; miss <= 2'd0;
                end
            end
            if (look == 2'd1) begin look <= 2'd2; ok_ra <= {prev_buf, f_line[9:3]}; end
            if (look == 2'd2) begin look <= 2'd3; ok_s <= ok_rd[f_line[2:0]]; end
            if (look == 2'd3) begin
                look <= 2'd0; fetching <= 1'b1; f_burst <= 0; f_idx <= 0; rep_v <= 1'b1; f_blank <= 1'b0;
                if (ok_s) begin
                    f_buf <= show_buf; f_src <= f_line; rep_buf <= show_buf; rep_line <= f_line; miss <= 2'd0;
                end else begin
                    if (miss != 2'd3) miss <= miss + 2'd1;
                    if (rep_v && miss < 2'd2) begin f_buf <= rep_buf; f_src <= rep_line; end      // the line above
                    else if (prev_ok && ok_rd[f_line[2:0]]) begin
                        f_buf <= prev_buf; f_src <= f_line; rep_buf <= prev_buf; rep_line <= f_line;
                    end else if (rep_v) begin f_buf <= rep_buf; f_src <= rep_line; end
                    else begin f_src <= f_line; f_blank <= 1'b1; rep_v <= 1'b0; end         // nothing to fall back on
                end
            end
            if (fetching && f_blank) begin                    // write the black line, one word per clock
                lb_we   <= 1'b1;
                lb_addr <= {f_slot, f_idx};
                lb_data <= BLACK;
                f_idx   <= f_idx + 9'd1;
                if (f_idx == 9'd359) fetching <= 1'b0;
            end
            if (rdata_valid && rd_inflight) begin
                lb_we   <= 1'b1;
                lb_addr <= {f_slot, f_idx};
                lb_data <= rdata;
                f_idx   <= f_idx + 9'd1;
                if (f_idx[2:0] == 3'd7) rd_inflight <= 1'b0;
                if (f_idx == 9'd359) fetching <= 1'b0;
            end

            // ---- arbiter: one SDRAM request at a time, fetch first ----
            if (req_valid && req_ready) req_valid <= 1'b0;
            if (writing && wdata_take) begin
                wr_k <= wr_k + 3'd1;
                if (wr_k == 3'd7) begin
                    writing <= 1'b0; grp_ready <= 1'b0; grp_mask <= 0;
                    if (stored) begin
                        ok_we <= 1'b1; ok_wa <= {cur_buf, grp_line[9:3]}; ok_wd <= mark_bits;
                        mk_have <= 1'b1; mk_grp <= grp_line[9:3]; mk_bits <= mark_bits;
                        done_any <= 1'b1; max_done <= grp_line;
                    end
                end
            end
            if (!req_valid && !writing && !rd_inflight) begin
                if (fetching && !f_blank && f_burst < 6'd45) begin
                    req_valid <= 1'b1; req_write <= 1'b0;
                    req_addr  <= word_addr(f_buf, f_src, f_burst);
                    f_burst   <= f_burst + 6'd1;
                    rd_inflight <= 1'b1;
                end else if (grp_ready && grp_mask == 8'hFF) begin
                    req_valid <= 1'b1; req_write <= 1'b1;
                    req_addr  <= word_addr(cur_buf, grp_line, grp_base);
                    writing   <= 1'b1; wr_k <= 3'd0;
                end
            end
        end
    end
endmodule
`default_nettype wire
