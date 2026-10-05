// SDRAM memory test for bring-up (top/m2a_memtest.v): finds out on the board which read sample point
// works, instead of guessing from a shifted picture. Everything except the PLL and the pins, so the
// same module runs on hardware and in simulation (sim/test_memtest.py).
//
// Endless loop over the three sample points T_RCD+CAS, +1, +2 (sdram_burst.v, rd_sample). For each:
//   write 2^AW words in 8-word bursts with pseudo-random data, read them back and compare;
//   the same with the address in the data: word = {~address[10:0], address[20:0]};
//   print one line on the UART (8N1, BAUD), then clear the counters.
// A pass is three lines. The pseudo-random data change with every pass.
//
//   M rs=5 pass=0012 err=00000000 bits=00000000000000000000000000000000 pos=00000000
//
//   rs    sample point of this line: the cycle after ACTIVATE at whose end word 0 is sampled
//   pass  pass number, hex, wraps at FFFF
//   err   words read back wrong, hex, both patterns together (stops at FFFFFFFF)
//   bits  one digit per data line, DQ31 first, DQ0 last: how often that bit was wrong
//   pos   one digit per word of the burst, word 0 first: how often that word was wrong
// A digit is the size of a count: 0 none, 1 one, 2 two or three, 3 four to seven ... n means 2^(n-1)
// to 2^n - 1, F 16384 or more (the counters stop at 32767).
//
// inject = 1: bit 0 of word 5 of the first burst is written wrong in the pseudo-random pattern. A line
// from a working sample point must then show err=00000001, the last digit of bits 1 and the sixth digit
// of pos 1: proof that the test can see an error.
`default_nettype none
module memtest_core #(
    parameter         FREQ  = 64_800_000,     // clk in Hz: SDRAM power-up wait and UART bit time
    parameter         BAUD  = 115_200,
    parameter         AW    = 21,             // 2^AW words are tested (21: the whole SDRAM); at least 4
    parameter [3:0]   CAS   = 4'd2,           // as sdram_burst's
    parameter [3:0]   T_RCD = 4'd2
) (
    input  wire        clk,
    input  wire        clk_sdram,             // clk shifted for the SDRAM (clocks_sdram.v)
    input  wire        rst,                   // synchronous, active high
    input  wire        inject,                // synchronous

    inout  wire [31:0] SDRAM_DQ,
    output wire [10:0] SDRAM_A,
    output wire [1:0]  SDRAM_BA,
    output wire        SDRAM_nCS, SDRAM_nWE, SDRAM_nRAS, SDRAM_nCAS, SDRAM_CLK, SDRAM_CKE,
    output wire [3:0]  SDRAM_DQM,

    output wire        uart_txd,
    output wire        init_done,             // SDRAM initialised
    output reg         line_toggle,           // flips with every line
    output reg         fail_default           // the last line of the default sample point (T_RCD+CAS+1) had errors
);
    localparam BW = AW - 3;                   // bits of the burst number

    // ---- SDRAM ----
    reg  [BW-1:0] burst;
    reg  [2:0]    k;                          // word in the burst
    reg  [1:0]    step;                       // sample point: T_RCD + CAS + step
    reg           pat;                        // 0 pseudo-random, 1 address
    reg  [15:0]   pass;
    reg  [31:0]   gen;                        // pseudo-random word (xorshift32)
    wire [20:0]   word_addr = {burst, k};
    wire [31:0]   word      = pat ? {~word_addr[10:0], word_addr} : gen;
    wire          hit       = inject && !pat && burst == 0 && k == 3'd5;
    wire [4:0]    rd_sample = T_RCD + CAS + step;
    wire [20:0]   req_addr  = {burst, 3'b000};
    wire          req_valid, req_write, req_ready, wdata_take, rdata_valid;
    wire [31:0]   rdata;
    sdram_burst #(.FREQ(FREQ), .CAS(CAS), .T_RCD(T_RCD)) sdram (
        .SDRAM_DQ(SDRAM_DQ), .SDRAM_A(SDRAM_A), .SDRAM_BA(SDRAM_BA), .SDRAM_nCS(SDRAM_nCS), .SDRAM_nWE(SDRAM_nWE),
        .SDRAM_nRAS(SDRAM_nRAS), .SDRAM_nCAS(SDRAM_nCAS), .SDRAM_CLK(SDRAM_CLK), .SDRAM_CKE(SDRAM_CKE), .SDRAM_DQM(SDRAM_DQM),
        .clk(clk), .clk_sdram(clk_sdram), .resetn(~rst), .rd_sample(rd_sample),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_ready(req_ready),
        .wdata(word ^ {31'd0, hit}), .wdata_take(wdata_take), .rdata(rdata), .rdata_valid(rdata_valid),
        .init_done(init_done));

    function [31:0] xorshift(input [31:0] x);
        reg [31:0] a, b;
        begin
            a = x ^ (x << 13);
            b = a ^ (a >> 17);
            xorshift = b ^ (b << 5);
        end
    endfunction
    wire [31:0] seed = {~pass, pass};         // never 0

    // ---- sequencer ----
    localparam S_START = 3'd0, S_WREQ = 3'd1, S_WDATA = 3'd2, S_RREQ = 3'd3, S_RDATA = 3'd4, S_FLUSH = 3'd5,
               S_PRINT = 3'd6;
    reg [2:0] st;
    reg [1:0] flush;
    assign req_valid = (st == S_WREQ) || (st == S_RREQ);
    assign req_write = (st == S_WREQ);
    wire last_burst = (burst == {BW{1'b1}});
    reg  line_done;

    // ---- compare, one clock behind the read data ----
    reg  [31:0] diff;
    reg         diff_valid;
    reg  [2:0]  diff_k;
    always @(posedge clk) begin
        diff       <= rdata ^ word;
        diff_valid <= (st == S_RDATA) && rdata_valid;
        diff_k     <= k;
    end

    reg [31:0]     err;
    reg [32*15-1:0] bit_n;                    // DQ i: bit_n[15*i +: 15]
    reg [8*15-1:0]  pos_n;                    // word i of the burst: pos_n[15*i +: 15]
    integer i;
    always @(posedge clk) begin
        if (rst || line_done) begin
            err <= 0; bit_n <= 0; pos_n <= 0;
        end else if (diff_valid && diff != 0) begin
            if (err != 32'hFFFFFFFF) err <= err + 1'b1;
            for (i = 0; i < 32; i = i + 1)
                if (diff[i] && bit_n[15*i +: 15] != 15'h7FFF) bit_n[15*i +: 15] <= bit_n[15*i +: 15] + 1'b1;
            for (i = 0; i < 8; i = i + 1)
                if (diff_k == i && pos_n[15*i +: 15] != 15'h7FFF) pos_n[15*i +: 15] <= pos_n[15*i +: 15] + 1'b1;
        end
    end

    // ---- report line ----
    localparam LEN = 82;
    localparam [LEN*8-1:0] TEXT = {"M rs=0 pass=0000 err=00000000 bits=", {32{"0"}}, " pos=", {8{"0"}}, 16'h0D0A};
    function [7:0] hexc(input [3:0] v); hexc = (v < 10) ? 8'h30 + v : 8'h37 + v; endfunction
    function [3:0] size_of(input [14:0] n);   // 0 for 0, else the position of the highest 1, counted from 1
        integer j;
        begin
            size_of = 4'd0;
            for (j = 0; j < 15; j = j + 1) if (n[j]) size_of = j + 1;
        end
    endfunction
    reg  [6:0]  idx;
    wire [6:0]  dq_i  = 7'd66 - idx;          // characters 35..66 are DQ31..DQ0
    wire [6:0]  pos_i = idx - 7'd72;          // characters 72..79 are words 0..7
    wire [15:0] pass_sh = pass >> {7'd15 - idx, 2'b00};       // characters 12..15
    wire [31:0] err_sh  = err  >> {7'd28 - idx, 2'b00};       // characters 21..28
    reg  [7:0]  ch_next;
    always @* begin
        ch_next = TEXT[(LEN - 1 - idx) * 8 +: 8];
        if (idx == 7'd5)                   ch_next = hexc(rd_sample[3:0]);
        if (idx >= 7'd12 && idx <= 7'd15)  ch_next = hexc(pass_sh[3:0]);
        if (idx >= 7'd21 && idx <= 7'd28)  ch_next = hexc(err_sh[3:0]);
        if (idx >= 7'd35 && idx <= 7'd66)  ch_next = hexc(size_of(bit_n[15*dq_i[4:0] +: 15]));
        if (idx >= 7'd72 && idx <= 7'd79)  ch_next = hexc(size_of(pos_n[15*pos_i[2:0] +: 15]));
    end
    reg  [7:0] ch;
    reg  [1:0] pst;
    reg        u_send;
    wire       u_busy;
    uart_tx #(.DIV(FREQ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(ch), .busy(u_busy), .txd(uart_txd));

    always @(posedge clk) begin
        u_send    <= 1'b0;
        line_done <= 1'b0;
        case (st)
        S_START: if (init_done) begin
            burst <= 0; k <= 0; gen <= seed; st <= S_WREQ;
        end
        // write: the controller takes one word at the end of every cycle with wdata_take
        S_WREQ: if (req_ready) st <= S_WDATA;
        S_WDATA: if (wdata_take) begin
            gen <= xorshift(gen);
            k   <= k + 1'b1;
            if (k == 3'd7) begin
                burst <= burst + 1'b1;
                st    <= S_WREQ;
                if (last_burst) begin gen <= seed; st <= S_RREQ; end
            end
        end
        // read back with the sample point of this line
        S_RREQ: if (req_ready) st <= S_RDATA;
        S_RDATA: if (rdata_valid) begin
            gen <= xorshift(gen);
            k   <= k + 1'b1;
            if (k == 3'd7) begin
                burst <= burst + 1'b1;
                st    <= S_RREQ;
                if (last_burst) begin
                    pat <= ~pat; gen <= seed;
                    if (pat) begin st <= S_FLUSH; flush <= 0; end
                    else st <= S_WREQ;
                end
            end
        end
        // let the last comparison reach the counters
        S_FLUSH: begin
            flush <= flush + 1'b1;
            if (flush == 2'd3) begin st <= S_PRINT; idx <= 0; pst <= 0; end
        end
        // one character at a time: compute it, wait for the UART, send it
        S_PRINT: case (pst)
            2'd0: begin ch <= ch_next; pst <= 2'd1; end
            2'd1: if (!u_busy) begin u_send <= 1'b1; pst <= 2'd2; end
            default: begin
                pst <= 2'd0;
                idx <= idx + 1'b1;
                if (idx == LEN - 1) begin
                    line_done   <= 1'b1;
                    line_toggle <= ~line_toggle;
                    if (step == 2'd1) fail_default <= (err != 0);
                    step <= (step == 2'd2) ? 2'd0 : step + 1'b1;
                    if (step == 2'd2) pass <= pass + 1'b1;
                    st <= S_START;
                end
            end
        endcase
        default: st <= S_START;
        endcase
        if (rst) begin
            st <= S_START; step <= 0; pat <= 1'b0; pass <= 0; line_toggle <= 1'b0; fail_default <= 1'b0;
        end
    end
endmodule
`default_nettype wire
