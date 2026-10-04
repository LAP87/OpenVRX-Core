// Field frame buffer in SDRAM (SDRAM clock domain).
//
// Writer: pops tagged words {field, line, idx, data} from the input FIFO,
// groups them into aligned 8-word bursts and writes them to the current field
// buffer. When a new field starts (field bit flips or the line number goes
// backwards) the finished buffer is published with its line count, and the
// next buffer is chosen so it is neither the one just published nor the one
// the display is showing (triple buffering).
//
// Fetcher: on a request {buf, line, slot} it reads one 360-word line in 45
// bursts into the dual-clock line buffer at {slot, idx}. Fetches have priority
// over writes (the display has a deadline; the input FIFO absorbs the stall).
//
// Word address map (21 bits): buf * 2^19 + line * 512 + idx (idx < 360), so
// 8-word groups never cross an SDRAM row and three buffers fit in 2^21 words.
`default_nettype none
module fb_sdram (
    input  wire        clk,
    input  wire        resetn,

    input  wire        in_empty,
    input  wire [51:0] in_data,          // {field, line[9:0], idx[8:0], data[31:0]}
    output reg         in_pop,

    input  wire        fetch_req,        // pulse (synchronised into this domain)
    input  wire [1:0]  fetch_buf,
    input  wire [9:0]  fetch_line,
    input  wire [1:0]  fetch_slot,
    output reg         lb_we,
    output reg  [10:0] lb_addr,          // {slot, idx}
    output reg  [31:0] lb_data,

    input  wire [1:0]  display_buf,
    output reg         pub_valid,
    output reg  [1:0]  pub_buf,
    output reg  [9:0]  pub_lines,

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

    function [1:0] pick_next(input [1:0] latest, input [1:0] shown);
        begin
            if (2'd0 != latest && 2'd0 != shown) pick_next = 2'd0;
            else if (2'd1 != latest && 2'd1 != shown) pick_next = 2'd1;
            else pick_next = 2'd2;
        end
    endfunction

    function [20:0] word_addr(input [1:0] b, input [9:0] line, input [5:0] grp);
        word_addr = {b, 19'd0} + {2'b00, line, 9'd0} + {12'd0, grp, 3'd0};
    endfunction

    // writer state
    reg [1:0]  cur_buf;
    reg        cur_field, have_field;
    reg [9:0]  last_line, max_line;
    reg [31:0] grp [0:7];
    reg [7:0]  grp_mask;
    reg [9:0]  grp_line;
    reg [5:0]  grp_base;
    reg        grp_ready, writing;
    reg [2:0]  wr_k;
    assign wdata = grp[wr_k];

    // fetcher state
    reg        fetching, rd_inflight;
    reg [1:0]  f_buf, f_slot;
    reg [9:0]  f_line;
    reg [5:0]  f_burst;
    reg [8:0]  f_idx;

    wire new_field  = have_field && (e_field != cur_field || e_line < last_line);
    wire breaks_grp = (grp_mask != 0) && (e_line != grp_line || e_idx[8:3] != grp_base);

    integer i;
    always @(posedge clk) begin
        in_pop    <= 1'b0;
        pub_valid <= 1'b0;
        lb_we     <= 1'b0;
        if (!resetn) begin
            cur_buf <= 0; have_field <= 0; grp_mask <= 0; grp_ready <= 0; writing <= 0;
            last_line <= 0; max_line <= 0; fetching <= 0; rd_inflight <= 0; req_valid <= 0;
        end else begin
            // ---- writer: take words from the FIFO ----
            if (!grp_ready && !in_empty && !in_pop) begin
                if (new_field || breaks_grp) begin
                    if (grp_mask != 0) grp_ready <= 1'b1;          // flush the open group first
                    else if (new_field) begin
                        pub_valid <= 1'b1;
                        pub_buf   <= cur_buf;
                        pub_lines <= max_line + 10'd1;
                        cur_buf   <= pick_next(cur_buf, display_buf);
                        cur_field <= e_field;
                        last_line <= 0;
                        max_line  <= 0;
                    end
                end else begin
                    if (!have_field) begin have_field <= 1'b1; cur_field <= e_field; end
                    in_pop <= 1'b1;
                    grp[e_idx[2:0]]      <= e_data;
                    grp_mask[e_idx[2:0]] <= 1'b1;
                    grp_line  <= e_line;
                    grp_base  <= e_idx[8:3];
                    last_line <= e_line;
                    if (e_line > max_line) max_line <= e_line;
                    if (e_idx[2:0] == 3'd7) grp_ready <= 1'b1;
                end
            end
            // pad holes of a closed group (only happens for broken lines)
            if (grp_ready && !writing && grp_mask != 8'hFF)
                for (i = 0; i < 8; i = i + 1)
                    if (!grp_mask[i]) begin grp[i] <= grp[0]; grp_mask[i] <= 1'b1; end

            // ---- fetcher: accept a request, store read data ----
            if (fetch_req && !fetching) begin
                fetching <= 1'b1; f_buf <= fetch_buf; f_line <= fetch_line; f_slot <= fetch_slot;
                f_burst <= 0; f_idx <= 0;
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
                if (wr_k == 3'd7) begin writing <= 1'b0; grp_ready <= 1'b0; grp_mask <= 0; end
            end
            if (!req_valid && !writing && !rd_inflight) begin
                if (fetching && f_burst < 6'd45 && !(fetch_req && !fetching)) begin
                    req_valid <= 1'b1; req_write <= 1'b0;
                    req_addr  <= word_addr(f_buf, f_line, f_burst);
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
