// Field dump over the UART (M6 with DEVCMD = 1, task 59): one field, line by line, from one of two word streams,
// sent as checked frames so that the PC can rebuild the picture without a grabber (gateware/tools/fielddump.py).
//
// The two taps carry the 52-bit word format of the mixer and the field store, {field, line[9:0], idx[8:0],
// data[31:0]}, data = {Y1, Cr, Y0, Cb} (word_packer.v), 360 words per line:
//   tap 0  decoder A before the mixer (chan_capture.v's words, its own clock: what the decoder delivers)
//   tap 1  the mixer's output as the field store takes it (sd_clk: what is written into the field store; not read
//          back from the SDRAM)
// A request (req[0] or req[1], one clock) dumps lines 0 .. N_LINES - 1 of that tap. For each line the controller
// arms the tap's line_grab with the line number; the grabber writes the next occurrence of that line, all 360 words
// in order from index 0, into a block RAM, and then the controller sends it. After the first line that arrives,
// only lines of the same field bit are taken, so an interlaced source gives one field. A line that does not arrive
// within TIMEOUT_MS is sent as a frame without data, marked missing. The picture is therefore taken over many
// fields (about one line per field period): exact per line, a snapshot only of a still source.
// While a dump runs, `busy` holds the log line sender off (puck_ui tx_pause) and, once it is idle (`tx_idle`),
// the UART pin is this module's (`owns_tx`).
//
// Frame, all values big-endian:
//   A5 5A  type ('D' tap 0, 'F' tap 1)  line (2)  flags (1)  length (2)  data (length bytes)  CRC (2)
//   flags: bit 0 the line's field bit, bit 1 missing (no data), bit 2 end of the dump (after the last line, no
//   data), bit 3 field matching was on. data: the 360 words as the decoder sent the bytes, Cb Y0 Cr Y1 ...
//   (1440 bytes). CRC-16/CCITT-FALSE (polynomial 1021h, start FFFFh) over type .. the last data byte.
`default_nettype none
module field_dump #(
    parameter CLK_HZ = 27_000_000,
    parameter BAUD = 115200,
    parameter N_LINES = 320,              // more than a PAL field has; lines that never come are sent as missing
    parameter TIMEOUT_MS = 45             // two field periods at 50 Hz, plus margin
) (
    input  wire        clk,               // board clock
    input  wire        rst,
    input  wire [1:0]  req,
    output reg         busy,
    input  wire        tx_idle,
    output reg         owns_tx,
    output wire        txd,
    input  wire        t0_clk, t0_rst, t0_valid,
    input  wire [51:0] t0_word,
    input  wire        t1_clk, t1_rst, t1_valid,
    input  wire [51:0] t1_word
);
    localparam LEN = 1440;
    localparam TMO = TIMEOUT_MS * (CLK_HZ / 1000);
    reg        sel;                       // the tap being dumped
    reg  [9:0] line;
    reg        match, want_field;
    reg  [1:0] arm;
    wire [1:0] done_tgl, got_field;
    wire [31:0] rd0, rd1;
    reg  [8:0] raddr;
    line_grab g0 (.tclk(t0_clk), .trst(t0_rst), .w_valid(t0_valid), .w_word(t0_word),
                  .arm_tgl(arm[0]), .target(line), .match(match), .want_field(want_field),
                  .done_tgl(done_tgl[0]), .got_field(got_field[0]), .rclk(clk), .raddr(raddr), .rdata(rd0));
    line_grab g1 (.tclk(t1_clk), .trst(t1_rst), .w_valid(t1_valid), .w_word(t1_word),
                  .arm_tgl(arm[1]), .target(line), .match(match), .want_field(want_field),
                  .done_tgl(done_tgl[1]), .got_field(got_field[1]), .rclk(clk), .raddr(raddr), .rdata(rd1));
    // done toggles into this clock domain (got_field is steady from the flip on)
    reg [2:0] d0, d1;
    always @(posedge clk) begin d0 <= {d0[1:0], done_tgl[0]}; d1 <= {d1[1:0], done_tgl[1]}; end
    wire done = sel ? (d1[2] != d1[1]) : (d0[2] != d0[1]);
    wire [31:0] rdata = sel ? rd1 : rd0;

    function [15:0] crc_byte(input [15:0] c, input [7:0] b);
        integer k;
        reg [15:0] x;
        begin
            x = c ^ {b, 8'h00};
            for (k = 0; k < 8; k = k + 1) x = x[15] ? {x[14:0], 1'b0} ^ 16'h1021 : {x[14:0], 1'b0};
            crc_byte = x;
        end
    endfunction

    localparam S_IDLE = 3'd0, S_QUIET = 3'd1, S_ARM = 3'd2, S_WAIT = 3'd3, S_SEND = 3'd4, S_DRAIN = 3'd5;
    reg [2:0]  st;
    reg [1:0]  quiet;
    reg [$clog2(TMO + 1)-1:0] t;
    reg [7:0]  flags;
    reg [10:0] n;                         // bytes of data in this frame (0 or LEN)
    reg [11:0] i;                         // byte of the frame being sent
    reg [15:0] crc;
    reg        u_send;
    wire       u_busy;
    wire [11:0] di = i - 12'd8;           // data byte index
    reg  [7:0] byte_i;
    always @* begin
        if (i == 0) byte_i = 8'hA5;
        else if (i == 1) byte_i = 8'h5A;
        else if (i == 2) byte_i = sel ? "F" : "D";
        else if (i == 3) byte_i = {6'd0, line[9:8]};
        else if (i == 4) byte_i = line[7:0];
        else if (i == 5) byte_i = flags;
        else if (i == 6) byte_i = {5'd0, n[10:8]};
        else if (i == 7) byte_i = n[7:0];
        else if (di < {1'b0, n}) case (di[1:0])
            2'd0: byte_i = rdata[7:0];
            2'd1: byte_i = rdata[15:8];
            2'd2: byte_i = rdata[23:16];
            default: byte_i = rdata[31:24];
        endcase
        else if (di == {1'b0, n}) byte_i = crc[15:8];
        else byte_i = crc[7:0];
    end
    always @* raddr = di[10:2];
    uart_tx #(.DIV(CLK_HZ / BAUD)) utx (.clk(clk), .rst(rst), .send(u_send), .data(byte_i), .busy(u_busy), .txd(txd));

    always @(posedge clk) begin
        u_send <= 1'b0;
        case (st)
            S_IDLE: if (req != 2'b00) begin
                sel <= req[1] & ~req[0];  // both at once: decoder A
                busy <= 1'b1; line <= 10'd0; match <= 1'b0; quiet <= 2'd0; st <= S_QUIET;
            end
            S_QUIET: begin                // the log sender has seen busy (two clocks) and finished its line
                if (quiet != 2'd3) quiet <= quiet + 1'b1;
                else if (tx_idle) begin owns_tx <= 1'b1; st <= S_ARM; end
            end
            S_ARM: begin
                if (sel) arm[1] <= ~arm[1]; else arm[0] <= ~arm[0];
                t <= 0; st <= S_WAIT;
            end
            S_WAIT: begin
                if (done) begin
                    flags <= {4'd0, match, 2'b00, sel ? got_field[1] : got_field[0]};
                    if (!match) begin match <= 1'b1; want_field <= sel ? got_field[1] : got_field[0]; end
                    n <= LEN; i <= 0; crc <= 16'hFFFF; st <= S_SEND;
                end else if (t == TMO) begin
                    flags <= {4'd0, match, 3'b010}; n <= 0; i <= 0; crc <= 16'hFFFF; st <= S_SEND;
                end else t <= t + 1'b1;
            end
            S_SEND: begin
                if (!u_busy && !u_send) u_send <= 1'b1;
                if (u_send) begin
                    if (i >= 12'd2 && i < 12'd8 + {1'b0, n}) crc <= crc_byte(crc, byte_i);
                    if (i == 12'd9 + {1'b0, n}) begin               // CRC low byte sent: frame done
                        if (flags[2]) st <= S_DRAIN;               // end frame: let its last byte out
                        else if (line == N_LINES - 1) begin       // the end frame
                            line <= N_LINES[9:0]; flags <= {4'd0, match, 3'b100}; n <= 0; i <= 0;
                            crc <= 16'hFFFF;
                        end else begin line <= line + 1'b1; st <= S_ARM; end
                    end else i <= i + 1'b1;
                end
            end
            S_DRAIN: if (!u_busy && !u_send) begin busy <= 1'b0; owns_tx <= 1'b0; st <= S_IDLE; end
            default: st <= S_IDLE;
        endcase
        if (rst) begin
            st <= S_IDLE; busy <= 1'b0; owns_tx <= 1'b0; arm <= 2'b00; u_send <= 1'b0; sel <= 1'b0; match <= 1'b0;
            want_field <= 1'b0; line <= 10'd0; i <= 0; n <= 0; flags <= 8'd0; crc <= 16'hFFFF; t <= 0;
        end
    end
endmodule

// One line of a tap's word stream into a block RAM. arm_tgl (another clock) flips once per request; target, match
// and want_field are steady from that flip until done_tgl flips back. The grabber then takes the next line with
// that number (and, with match, that field bit) whose words come in order 0..359; a line that breaks off is dropped
// and the next occurrence waited for. got_field is steady from done_tgl's flip until the next arm.
module line_grab (
    input  wire        tclk,
    input  wire        trst,
    input  wire        w_valid,
    input  wire [51:0] w_word,
    input  wire        arm_tgl,
    input  wire [9:0]  target,
    input  wire        match,
    input  wire        want_field,
    output reg         done_tgl,
    output reg         got_field,
    input  wire        rclk,
    input  wire [8:0]  raddr,
    output wire [31:0] rdata
);
    reg [2:0] a;
    always @(posedge tclk) a <= {a[1:0], arm_tgl};
    wire       w_field = w_word[51];
    wire [9:0] w_line = w_word[50:41];
    wire [8:0] w_idx = w_word[40:32];
    reg        armed, run;
    reg [8:0]  next;
    wire       first = w_valid && w_idx == 9'd0 && w_line == target && (!match || w_field == want_field);
    wire       more = w_valid && run && w_line == target && w_idx == next;
    wire       we = armed && (first || more);
    dual_clock_ram #(.DEPTH(360), .AW(9), .W(32)) ram (.wclk(tclk), .we(we), .waddr(w_idx), .wdata(w_word[31:0]),
                                                       .rclk(rclk), .raddr(raddr), .rdata(rdata));
    always @(posedge tclk) begin
        if (a[2] != a[1]) begin armed <= 1'b1; run <= 1'b0; end
        else if (armed) begin
            if (first) begin run <= 1'b1; next <= 9'd1; got_field <= w_field; end
            else if (more) begin
                if (next == 9'd359) begin armed <= 1'b0; run <= 1'b0; done_tgl <= ~done_tgl; end
                else next <= next + 1'b1;
            end else if (w_valid && run) run <= 1'b0;            // broken off: wait for the next occurrence
        end
        if (trst) begin armed <= 1'b0; run <= 1'b0; done_tgl <= 1'b0; got_field <= 1'b0; next <= 9'd0; end
    end
endmodule
`default_nettype wire
