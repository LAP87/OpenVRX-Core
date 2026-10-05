// One mixer channel: complete lines in a four-slot ring, with quality and
// arrival metadata. A full ring or a missing word discards the WHOLE line;
// releasing a slot halfway through it must never publish stale RAM contents.
// Epochs increment on field changes or line-number restarts (constant-F video).
`default_nettype none
module mix_chan #(
    parameter LEN_NTSC = 1716, LEN_PAL = 1728, LEN_TOL = 2,
    parameter N_WORDS = 360,
    parameter TIMEOUT = 262144           // 4.05 ms at 64.8 MHz: includes PAL/NTSC VBI
) (
    input wire clk, rst,
    input wire ext_bad,
    input wire in_empty,
    input wire [52:0] in_data,
    output wire in_pop,
    input wire pop_line,
    input wire [8:0] rd_idx,
    output wire [31:0] rd_data,
    output reg [2:0] count,
    output wire head_field,
    output wire [9:0] head_line,
    output wire [19:0] head_hf,
    output wire head_bad,
    output wire [7:0] head_epoch,
    output wire [31:0] head_age,
    output reg alive,
    output reg overflow
);
    assign in_pop = !in_empty;
    wire is_marker = in_data[52];
    wire full = count == 3'd4;
    reg [1:0] wslot, rslot;
    reg assembling, discard;
    reg word_field;
    reg [9:0] word_line, next_word;
    wire first_word = in_data[40:32] == 9'd0;
    wire word_matches = assembling && !discard &&
                        in_data[51:41] == {word_field, word_line} &&
                        {1'b0, in_data[40:32]} == next_word;
    wire write_word = in_pop && !is_marker && !full && (first_word || word_matches);
    dual_clock_ram #(.DEPTH(2048), .AW(11), .W(32)) ring (
        .wclk(clk), .we(write_word), .waddr({wslot, in_data[40:32]}), .wdata(in_data[31:0]),
        .rclk(clk), .raddr({rslot, rd_idx}), .rdata(rd_data));

    wire [11:0] len = in_data[12:1];
    function in_tol(input [11:0] v, input [11:0] nominal);
        in_tol = (v + LEN_TOL >= nominal) && (v <= nominal + LEN_TOL);
    endfunction
    reg [1:0] ext_s;
    always @(posedge clk) if (rst) ext_s <= 0; else ext_s <= {ext_s[0], ext_bad};
    // Preserve the decoder/forced fault at capture; a later recovery must not
    // make queued data from the faulty interval usable. Current faults also
    // apply immediately to an otherwise good waiting head below.
    wire bad_in = ext_s[1] || (in_data[20:17] != 4'd0) ||
                  !(in_tol(len, LEN_NTSC) || in_tol(len, LEN_PAL));

    reg m_field [0:3], m_bad [0:3];
    reg [9:0] m_line [0:3];
    reg [19:0] m_hf [0:3];
    reg [7:0] m_epoch [0:3];
    reg [31:0] m_tick [0:3];
    reg [31:0] tick;
    assign head_field = m_field[rslot];
    assign head_line = m_line[rslot];
    assign head_hf = m_hf[rslot];
    // Forced-channel mode applies to waiting lines too, not just future markers.
    assign head_bad = m_bad[rslot] || ext_s[1];
    assign head_epoch = m_epoch[rslot];
    assign head_age = tick - m_tick[rslot];

    reg seen_marker, last_field;
    reg [9:0] last_line;
    reg [7:0] epoch;
    wire [7:0] incoming_epoch = epoch +
        (seen_marker && (in_data[51] != last_field || in_data[50:41] < last_line));
    wire mark = in_pop && is_marker && !full && assembling && !discard &&
                next_word == N_WORDS && in_data[51:41] == {word_field, word_line};
    wire rel = pop_line && count != 0;
    reg [$clog2(TIMEOUT+1)-1:0] idle;
    always @(posedge clk) begin
        tick <= tick + 1'b1;
        if (in_pop && !is_marker) begin
            if (first_word) begin
                assembling <= 1'b1;
                discard <= full;
                word_field <= in_data[51]; word_line <= in_data[50:41];
                next_word <= 1;
            end else if (word_matches && !full) next_word <= next_word + 1'b1;
            else discard <= 1'b1;
            if (full) overflow <= 1'b1;
        end
        if (in_pop && is_marker) begin
            assembling <= 1'b0; discard <= 1'b0;
            epoch <= incoming_epoch; seen_marker <= 1'b1;
            last_field <= in_data[51]; last_line <= in_data[50:41];
            idle <= 0; alive <= 1'b1;
            if (full) overflow <= 1'b1;
        end else if (idle != TIMEOUT) idle <= idle + 1'b1;
        else alive <= 1'b0;
        if (mark) begin
            m_field[wslot] <= in_data[51]; m_line[wslot] <= in_data[50:41];
            m_hf[wslot] <= in_data[40:21]; m_bad[wslot] <= bad_in;
            m_epoch[wslot] <= incoming_epoch; m_tick[wslot] <= tick;
            wslot <= wslot + 1'b1;
        end
        if (rel) rslot <= rslot + 1'b1;
        count <= count + {2'b00, mark} - {2'b00, rel};
        if (rst) begin
            wslot <= 0; rslot <= 0; count <= 0; overflow <= 0;
            assembling <= 0; discard <= 0; next_word <= 0;
            idle <= 0; alive <= 0; tick <= 0;
            seen_marker <= 0; last_field <= 0; last_line <= 0; epoch <= 0;
        end
    end
endmodule
`default_nettype wire
