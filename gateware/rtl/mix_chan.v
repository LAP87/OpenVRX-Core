// Mixer input stage for one channel (SDRAM/system clock domain): drains the
// channel's FIFO, writes line words into a 4-slot ring (4 x 512 x 32 bits,
// BSRAM) and keeps the metrics of each completed line. The mixer reads the
// oldest completed line (head) and releases it with pop_line.
//
// A line counts as bad when a timing code could not be decoded or its length
// (EAV to EAV) is not NTSC or PAL within LEN_TOL bytes, or while ext_bad is
// set (e.g. the decoder reports no horizontal/vertical lock).
`default_nettype none
module mix_chan #(
    parameter LEN_NTSC = 1716,
    parameter LEN_PAL  = 1728,
    parameter LEN_TOL  = 2,
    parameter TIMEOUT  = 65536            // cycles without a line before the channel counts as dead
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        ext_bad,           // async, slow (decoder status)
    input  wire        in_empty,
    input  wire [52:0] in_data,
    output wire        in_pop,

    input  wire        pop_line,
    input  wire [8:0]  rd_idx,
    output wire [31:0] rd_data,          // word rd_idx of the head line, 1 cycle after rd_idx

    output reg  [2:0]  count,            // completed lines waiting (0..4)
    output wire        head_field,
    output wire [9:0]  head_line,
    output wire [19:0] head_hf,
    output wire        head_bad,
    output reg         alive,
    output reg         overflow          // sticky: a line was dropped because all slots were full
);
    assign in_pop = !in_empty;
    wire is_marker = in_data[52];
    wire full = (count == 3'd4);

    reg [1:0] wslot, rslot;
    dual_clock_ram #(.DEPTH(2048), .AW(11), .W(32)) ring (
        .wclk(clk), .we(in_pop && !is_marker && !full), .waddr({wslot, in_data[40:32]}), .wdata(in_data[31:0]),
        .rclk(clk), .raddr({rslot, rd_idx}), .rdata(rd_data));

    wire [11:0] len = in_data[12:1];
    function in_tol(input [11:0] v, input [11:0] nominal);
        in_tol = (v + LEN_TOL >= nominal) && (v <= nominal + LEN_TOL);
    endfunction
    reg [1:0] ext_s;
    always @(posedge clk) ext_s <= {ext_s[0], ext_bad};
    wire bad_in = ext_s[1] || (in_data[20:17] != 4'd0) || !(in_tol(len, LEN_NTSC) || in_tol(len, LEN_PAL));

    reg        m_field [0:3];
    reg [9:0]  m_line  [0:3];
    reg [19:0] m_hf    [0:3];
    reg        m_bad   [0:3];
    assign head_field = m_field[rslot];
    assign head_line  = m_line[rslot];
    assign head_hf    = m_hf[rslot];
    assign head_bad   = m_bad[rslot];

    wire mark = in_pop && is_marker && !full;
    wire rel  = pop_line && count != 3'd0;
    reg [$clog2(TIMEOUT+1)-1:0] idle;
    always @(posedge clk) begin
        if (mark) begin
            m_field[wslot] <= in_data[51];
            m_line[wslot]  <= in_data[50:41];
            m_hf[wslot]    <= in_data[40:21];
            m_bad[wslot]   <= bad_in;
            wslot <= wslot + 1'b1;
        end
        if (rel) rslot <= rslot + 1'b1;
        count <= count + {2'b00, mark} - {2'b00, rel};
        if (in_pop && is_marker && full) overflow <= 1'b1;

        if (in_pop && is_marker) begin idle <= 0; alive <= 1'b1; end
        else if (idle != TIMEOUT) idle <= idle + 1'b1;
        else alive <= 1'b0;

        if (rst) begin
            wslot <= 0; rslot <= 0; count <= 0; overflow <= 1'b0; idle <= 0; alive <= 1'b0;
        end
    end
endmodule
`default_nettype wire
