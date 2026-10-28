// M7: probe for the C5VRX sample bus on decoder B's pins (J5, DIGIN wiring of M4): captures 2^AW
// consecutive 6-bit samples on the bus clock (PIN80, 40 MHz) and sends them over the onboard USB-UART
// (PIN69, 115200 8N1) as hex, 64 samples per line, between a header line and "END". Then a pause and the
// next capture. 16 384 samples are 410 us, 6.4 NTSC lines: enough to see the sync pulses, their width and
// spacing and the code levels C5VRX really uses, which is what cvbs_capture.v's slicer has to find.
//   DIGIN 10000 CLK 0262            (samples per capture in hex; CLK: toggles of a 2^16 divider of the bus clock
//                                    per second, hex: f = CLK * 65536 Hz)
//   0f0f0f...                       (64 samples, two hex digits each, bit 0 = XIAO D4 ... bit 5 = D9)
//   ...
//   END
// Between dumps one statistics line from a cvbs_capture running on the live bus (the measurement tap of
// task 69): "CAP t=<window in 65536 bus clocks> l=<locked now> c=<lock changes> n=<line markers> b=<bad ones>
// m=<shortest line, ticks> M=<longest> w=<words>", all hex, the window being the time since the previous line.
// LEDs (active low): 0 heartbeat 2 Hz, 1 lit while a capture is sent, 2 lit while the bus clock is seen.
// Bench 2026-10-27: m3_probe showed the clock (> 33.5 MHz, its counter's top) and all six bits toggling, but
// m4_dual_mix_digin produced no lines; this shows what the bits carry.
`default_nettype none
module m7_digin_probe #(
    parameter CLK_HZ = 27_000_000,
    parameter BAUD = 115_200,                 // 921 600 (27e6/29, +1.0 %) stalled the BL616 bridge path on 2026-10-27: 7.7 kB, then silence
    parameter AW = 16,                        // 2^AW samples per capture: 65 536 = 1.6 ms = 26 NTSC lines
    parameter PAUSE_MS = 1000,
    parameter TRIG_LOW_RUN = 400,             // capture starts at a low run this long (a broad pulse: the vertical
                                              // interval and the lines after it land in the dump); 0 = at once
    parameter TRIG_LEVEL = 27                 // "low" for the trigger: below this code (C5VRX: sync 23, blanking 31)
) (
    input  wire       clk,
    input  wire       tvpb_sclk,              // the bus clock, PIN80
    input  wire [5:0] tvpb_d,                 // the bus, D4..D9 = bits 0..5
    output wire [5:0] led,
    output wire       uart_txd
);
    localparam N = 1 << AW;

    // ---- reset and heartbeat (board clock)
    reg [3:0] por = 4'hF;
    always @(posedge clk) por <= {por[2:0], 1'b0};
    wire rst = por[3];
    reg [$clog2(CLK_HZ / 4)-1:0] hb_cnt = 0;
    reg beat = 1'b0;
    always @(posedge clk) begin
        if (hb_cnt == CLK_HZ / 4 - 1) begin hb_cnt <= 0; beat <= ~beat; end
        else hb_cnt <= hb_cnt + 1'b1;
    end

    // ---- capture, bus clock domain: one pass over the RAM per arm toggle
    reg          arm_t = 1'b0;                // board domain, toggles to request a capture
    reg  [2:0]   arm_s = 3'b000;              // synchronised into the bus domain
    reg          cap_run = 1'b0;
    reg  [AW-1:0] waddr = 0;
    reg          done_t = 1'b0;               // toggles when a capture is complete
    reg  [5:0]   d_q = 6'd0;
    reg          alive_t = 1'b0;              // toggles every 2^16 bus clocks: clock presence
    reg  [15:0]  alive_cnt = 16'd0;
    reg          armed = 1'b0;                // waiting for the trigger
    reg  [11:0]  low_cnt = 12'd0;
    reg  [3:0]   high_cnt = 4'd0;             // the low run survives noise spikes: it ends after 8 highs in a row
    wire         trig = (TRIG_LOW_RUN == 0) || (low_cnt >= TRIG_LOW_RUN);
    always @(posedge tvpb_sclk) begin
        d_q   <= tvpb_d;
        arm_s <= {arm_s[1:0], arm_t};
        alive_cnt <= alive_cnt + 1'b1;
        if (&alive_cnt) alive_t <= ~alive_t;
        if (d_q < TRIG_LEVEL) begin
            high_cnt <= 4'd0;
            if (!(&low_cnt)) low_cnt <= low_cnt + 1'b1;
        end else begin
            high_cnt <= (&high_cnt[2:0]) ? high_cnt : high_cnt + 1'b1;
            if (high_cnt >= 4'd7) low_cnt <= 12'd0;
        end
        if (!cap_run) begin
            if (arm_s[2] != arm_s[1]) armed <= 1'b1;
            if (armed && trig) begin cap_run <= 1'b1; armed <= 1'b0; waddr <= 0; end
        end else begin
            waddr <= waddr + 1'b1;
            if (&waddr) begin cap_run <= 1'b0; done_t <= ~done_t; end
        end
    end
    reg  [AW-1:0] raddr = 0;
    wire [5:0]    rdata;
    dual_clock_ram #(.DEPTH(N), .AW(AW), .W(6)) ram (
        .wclk(tvpb_sclk), .we(cap_run), .waddr(waddr), .wdata(d_q),
        .rclk(clk), .raddr(raddr), .rdata(rdata));

    // ---- cvbs_capture on the live bus: lock and line statistics between dumps (a measurement tap, task 69)
    // Counters in the bus domain, latched and cleared on a snapshot toggle from the board domain, acknowledged
    // by a toggle back (as bt656_probe.v); the window is the time since the previous snapshot.
    reg [2:0] rst_b = 3'b111;
    always @(posedge tvpb_sclk or posedge rst) if (rst) rst_b <= 3'b111; else rst_b <= {rst_b[1:0], 1'b0};
    wire        e_valid, line_pulse, lock;
    wire [52:0] e_data;
    // d_q: one input flop before the capture, as mixer2's b_in in M4
    cvbs_capture #(.WHITE_X8(31)) cap (.clk(tvpb_sclk), .rst(rst_b[2]), .d(d_q), .e_valid(e_valid), .e_data(e_data),
                                       .line_pulse(line_pulse), .lock(lock));
    wire        marker = e_valid && e_data[52];
    wire [11:0] mlen   = e_data[12:1];
    wire        mbad   = |e_data[20:17];
    reg         snap_t = 1'b0;                // board domain
    reg  [2:0]  snap_s = 3'b000;              // bus domain
    reg         ack_t = 1'b0;
    reg         lock_q = 1'b0, l_lock = 1'b0;
    reg  [15:0] c_t = 16'd0, l_t = 16'd0;     // alive toggles in the window: window length = l_t * 65536 bus clocks
    reg  [23:0] c_chg = 24'd0, c_lines = 24'd0, c_bad = 24'd0, l_chg = 24'd0, l_lines = 24'd0, l_bad = 24'd0;
    reg  [23:0] c_off = 24'd0, l_off = 24'd0;   // markers whose length is outside the mixer's 1716 +- 2
    wire        moff   = mlen < 12'd1714 || mlen > 12'd1718;
    reg  [11:0] c_min = 12'hFFF, c_max = 12'd0, l_min = 12'hFFF, l_max = 12'd0;
    reg  [27:0] c_words = 28'd0, l_words = 28'd0;
    always @(posedge tvpb_sclk) begin
        snap_s <= {snap_s[1:0], snap_t};
        lock_q <= lock;
        if (snap_s[2] != snap_s[1]) begin
            l_t <= c_t; l_chg <= c_chg; l_lines <= c_lines; l_bad <= c_bad; l_min <= c_min; l_max <= c_max;
            l_words <= c_words; l_lock <= lock; l_off <= c_off;
            c_t <= 16'd0; c_chg <= 24'd0; c_lines <= 24'd0; c_bad <= 24'd0; c_min <= 12'hFFF; c_max <= 12'd0;
            c_words <= 28'd0; c_off <= 24'd0;
            ack_t <= ~ack_t;
        end else begin
            if (&alive_cnt) c_t <= c_t + 1'b1;
            if (lock != lock_q) c_chg <= c_chg + 1'b1;
            if (marker) begin
                c_lines <= c_lines + 1'b1;
                if (mbad) c_bad <= c_bad + 1'b1;
                if (moff) c_off <= c_off + 1'b1;
                if (mlen < c_min) c_min <= mlen;
                if (mlen > c_max) c_max <= mlen;
            end
            if (e_valid && !e_data[52]) c_words <= c_words + 1'b1;
        end
    end
    reg [2:0] ack_s = 3'b000;
    always @(posedge clk) ack_s <= {ack_s[1:0], ack_t};
    wire ack_p = ack_s[2] ^ ack_s[1];
    // "CAP t=tttt l=L c=cccccc n=nnnnnn b=bbbbbb m=mmm M=MMM w=wwwwwww x=xxxxxx\n" (73 bytes, hex): t window in
    // 65 536 bus clocks, l lock now, c lock changes, n line markers, b of them bad, m/M shortest/longest line
    // (ticks), w words, x markers with a length outside 1716 +- 2 (the mixer's tolerance)
    localparam STAT_LEN = 73;
    function [7:0] stat_byte(input [6:0] i, input [15:0] t, input l, input [23:0] c, input [23:0] n,
                             input [23:0] b, input [11:0] mn, input [11:0] mx, input [27:0] w, input [23:0] o);
        case (i)
            6'd0: stat_byte = "C"; 6'd1: stat_byte = "A"; 6'd2: stat_byte = "P"; 6'd3: stat_byte = " ";
            6'd4: stat_byte = "t"; 6'd5: stat_byte = "=";
            6'd6: stat_byte = hex(t[15:12]); 6'd7: stat_byte = hex(t[11:8]); 6'd8: stat_byte = hex(t[7:4]);
            6'd9: stat_byte = hex(t[3:0]); 6'd10: stat_byte = " ";
            6'd11: stat_byte = "l"; 6'd12: stat_byte = "="; 6'd13: stat_byte = l ? "1" : "0"; 6'd14: stat_byte = " ";
            6'd15: stat_byte = "c"; 6'd16: stat_byte = "=";
            6'd17: stat_byte = hex(c[23:20]); 6'd18: stat_byte = hex(c[19:16]); 6'd19: stat_byte = hex(c[15:12]);
            6'd20: stat_byte = hex(c[11:8]); 6'd21: stat_byte = hex(c[7:4]); 6'd22: stat_byte = hex(c[3:0]);
            6'd23: stat_byte = " ";
            6'd24: stat_byte = "n"; 6'd25: stat_byte = "=";
            6'd26: stat_byte = hex(n[23:20]); 6'd27: stat_byte = hex(n[19:16]); 6'd28: stat_byte = hex(n[15:12]);
            6'd29: stat_byte = hex(n[11:8]); 6'd30: stat_byte = hex(n[7:4]); 6'd31: stat_byte = hex(n[3:0]);
            6'd32: stat_byte = " ";
            6'd33: stat_byte = "b"; 6'd34: stat_byte = "=";
            6'd35: stat_byte = hex(b[23:20]); 6'd36: stat_byte = hex(b[19:16]); 6'd37: stat_byte = hex(b[15:12]);
            6'd38: stat_byte = hex(b[11:8]); 6'd39: stat_byte = hex(b[7:4]); 6'd40: stat_byte = hex(b[3:0]);
            6'd41: stat_byte = " ";
            6'd42: stat_byte = "m"; 6'd43: stat_byte = "=";
            6'd44: stat_byte = hex(mn[11:8]); 6'd45: stat_byte = hex(mn[7:4]); 6'd46: stat_byte = hex(mn[3:0]);
            6'd47: stat_byte = " ";
            6'd48: stat_byte = "M"; 6'd49: stat_byte = "=";
            6'd50: stat_byte = hex(mx[11:8]); 6'd51: stat_byte = hex(mx[7:4]); 6'd52: stat_byte = hex(mx[3:0]);
            6'd53: stat_byte = " ";
            6'd54: stat_byte = "w"; 6'd55: stat_byte = "=";
            6'd56: stat_byte = hex(w[27:24]); 6'd57: stat_byte = hex(w[23:20]); 6'd58: stat_byte = hex(w[19:16]);
            6'd59: stat_byte = hex(w[15:12]); 6'd60: stat_byte = hex(w[11:8]); 6'd61: stat_byte = hex(w[7:4]);
            6'd62: stat_byte = hex(w[3:0]); 6'd63: stat_byte = " ";
            7'd64: stat_byte = "x"; 7'd65: stat_byte = "=";
            7'd66: stat_byte = hex(o[23:20]); 7'd67: stat_byte = hex(o[19:16]); 7'd68: stat_byte = hex(o[15:12]);
            7'd69: stat_byte = hex(o[11:8]); 7'd70: stat_byte = hex(o[7:4]); 7'd71: stat_byte = hex(o[3:0]);
            default: stat_byte = 8'h0A;
        endcase
    endfunction

    // ---- board clock domain: arm, wait, send
    reg [2:0] done_s = 3'b000, alive_s = 3'b000;
    always @(posedge clk) begin done_s <= {done_s[1:0], done_t}; alive_s <= {alive_s[1:0], alive_t}; end
    wire done_p = done_s[2] ^ done_s[1];
    reg [$clog2(CLK_HZ / 8)-1:0] alive_age = 0;      // clock seen within the last 1/8 s
    reg clock_seen = 1'b0;
    always @(posedge clk) begin
        if (alive_s[2] ^ alive_s[1]) begin alive_age <= 0; clock_seen <= 1'b1; end
        else if (alive_age == CLK_HZ / 8 - 1) clock_seen <= 1'b0;
        else alive_age <= alive_age + 1'b1;
    end

    function [7:0] hex(input [3:0] v);
        hex = (v < 4'd10) ? (8'h30 + {4'd0, v}) : (8'h57 + {4'd0, v});
    endfunction
    // bus clock frequency: alive_t toggles per second (times 65 536 Hz), latched once a second
    reg [$clog2(CLK_HZ)-1:0] win_cnt = 0;
    reg [15:0] tog_cnt = 16'd0, tog_lat = 16'd0;
    wire alive_p = alive_s[2] ^ alive_s[1];
    always @(posedge clk) begin
        if (win_cnt == CLK_HZ - 1) begin win_cnt <= 0; tog_lat <= tog_cnt + {15'd0, alive_p}; tog_cnt <= 16'd0; end
        else begin win_cnt <= win_cnt + 1'b1; if (alive_p) tog_cnt <= tog_cnt + 1'b1; end
    end
    // header "DIGIN hhhhh CLK hhhh\n": hhhhh = samples per capture in hex, hhhh = divider toggles per second in
    // hex, bus clock = hhhh * 65536 Hz
    localparam HDR_LEN = 21;
    localparam [19:0] N_HEX = N;
    function [7:0] hdr(input [4:0] i, input [15:0] t);
        case (i)
            5'd0: hdr = "D"; 5'd1: hdr = "I"; 5'd2: hdr = "G"; 5'd3: hdr = "I"; 5'd4: hdr = "N"; 5'd5: hdr = " ";
            5'd6: hdr = hex(N_HEX[19:16]); 5'd7: hdr = hex(N_HEX[15:12]); 5'd8: hdr = hex(N_HEX[11:8]);
            5'd9: hdr = hex(N_HEX[7:4]); 5'd10: hdr = hex(N_HEX[3:0]); 5'd11: hdr = " ";
            5'd12: hdr = "C"; 5'd13: hdr = "L"; 5'd14: hdr = "K"; 5'd15: hdr = " ";
            5'd16: hdr = hex(t[15:12]); 5'd17: hdr = hex(t[11:8]); 5'd18: hdr = hex(t[7:4]); 5'd19: hdr = hex(t[3:0]);
            default: hdr = 8'h0A;
        endcase
    endfunction
    function [7:0] tail(input [1:0] i);
        case (i) 2'd0: tail = "E"; 2'd1: tail = "N"; 2'd2: tail = "D"; default: tail = 8'h0A; endcase
    endfunction

    localparam [3:0] S_PAUSE = 4'd0, S_ARM = 4'd1, S_WAIT = 4'd2, S_HDR = 4'd3, S_RD = 4'd4, S_RD2 = 4'd5,
                     S_HI = 4'd6, S_LO = 4'd7, S_NL = 4'd8, S_END = 4'd9, S_SNAP = 4'd10, S_SNAPW = 4'd11,
                     S_STAT = 4'd12;
    reg [3:0]  state = S_PAUSE;
    reg        stat_done = 1'b0;              // the statistics line of this pause has been sent
    reg [$clog2(CLK_HZ / 1000 * PAUSE_MS + 1)-1:0] pause_cnt = 0;
    reg [AW-1:0] i = 0;
    reg [4:0]  ci = 0;
    reg        u_send = 1'b0;
    reg [7:0]  u_data = 8'd0;
    wire       u_busy;
    wire       u_free = !u_busy && !u_send;
    uart_tx #(.DIV(CLK_HZ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(u_data), .busy(u_busy), .txd(uart_txd));

    always @(posedge clk) begin
        u_send <= 1'b0;
        if (rst) begin state <= S_PAUSE; pause_cnt <= 0; end
        else case (state)
            S_PAUSE: if (!stat_done) state <= S_SNAP;
                     else if (pause_cnt == CLK_HZ / 1000 * PAUSE_MS - 1) begin pause_cnt <= 0; state <= S_ARM; end
                     else pause_cnt <= pause_cnt + 1'b1;
            S_SNAP:  begin snap_t <= ~snap_t; state <= S_SNAPW; end
            S_SNAPW: if (ack_p) begin state <= S_STAT; i <= 0; end
            S_STAT:  if (u_free) begin
                         u_send <= 1'b1;
                         u_data <= stat_byte(i[6:0], l_t, l_lock, l_chg, l_lines, l_bad, l_min, l_max, l_words, l_off);
                         i <= i + 1'b1;
                         if (i[6:0] == STAT_LEN - 1) begin stat_done <= 1'b1; state <= S_PAUSE; end
                     end
            S_ARM:   begin arm_t <= ~arm_t; stat_done <= 1'b0; state <= S_WAIT; end
            S_WAIT:  if (done_p) begin state <= S_HDR; ci <= 0; i <= 0; end
            S_HDR:   if (u_free) begin
                         u_send <= 1'b1; u_data <= hdr(ci, tog_lat);
                         if (ci == HDR_LEN - 1) begin ci <= 0; state <= S_RD; end else ci <= ci + 1'b1;
                     end
            S_RD:    begin raddr <= i; state <= S_RD2; end
            S_RD2:   state <= S_HI;                                 // rdata valid from here on
            S_HI:    if (u_free) begin u_send <= 1'b1; u_data <= hex({2'b00, rdata[5:4]}); state <= S_LO; end
            S_LO:    if (u_free) begin
                         u_send <= 1'b1; u_data <= hex(rdata[3:0]);
                         i <= i + 1'b1;
                         state <= (&i[5:0]) ? S_NL : S_RD;           // 64 samples per text line
                     end
            S_NL:    if (u_free) begin
                         u_send <= 1'b1; u_data <= 8'h0A;
                         state <= (i == 0) ? S_END : S_RD;           // i wrapped to 0 after the last sample
                         ci <= 0;
                     end
            S_END:   if (u_free) begin
                         u_send <= 1'b1; u_data <= tail(ci[1:0]);
                         if (ci[1:0] == 2'd3) state <= S_PAUSE; else ci <= ci + 1'b1;
                     end
            default: state <= S_PAUSE;
        endcase
    end

    assign led = ~{3'b000, clock_seen, state != S_PAUSE, beat};
endmodule
`default_nettype wire
