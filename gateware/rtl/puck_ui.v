// Puck prototype UI: two buttons, 4 x 21 character OLED text, RX5808 tuning.
//
//   OK   (short press) -> select the next field: band, channel, mode, latency, page
//   NEXT (short press) -> step the selected field (page: main <-> meter)
//
// Band/channel changes reprogram both RX5808 modules at once with the synth
// register from vtx_channels.vh. The first write comes 0.5 s after reset, and
// the channel is written again every 2 s for as long as no decoder is locked
// (rx5808_tune.v).
// Mode MIX lets the line mixer choose; A or B forces one receiver by marking
// the other one "bad" (same input the decoder lock status uses).
// Latency BUF shows the video through the SDRAM field buffer; LOW bypasses it
// and locks the HDMI output to the input fields (fb_backend.v low-latency mode).
//
// Screen (rows 0-3):
//   >BAND F   CH 4  5800        (exactly 21 characters per row)
//    MODE MIX VIEW A  BUF     (BUF / LOW: latency mode)
//    A LOCK    B NOSIG
//    SE BAND OK            or   !OUTSIDE SE BAND
// '>' marks the selected field (in front of BAND, CH, MODE, BUF/LOW, or row 3 for the page).
//
// Meter page ("snow meter", self-interference / signal check):
//   >METER   F4  5800
//   A  12345 #######          mean line HF energy (snow) of receiver A over 1024 lines,
//   B   2345 ####             bar = log2 (one block per doubling); "  ----" = no lines
//    USE A 40 B 35 M 25       % of the last 1024 mixer decisions: A, B, blend
`default_nettype none
module puck_ui #(
    parameter CLK_HZ = 27_000_000,
    parameter DEBOUNCE_MS = 20,
    parameter [2:0] DEF_BAND = 3'd3,      // F
    parameter [2:0] DEF_CH = 3'd3,        // 4th channel -> F4 5800 MHz (legal in Sweden)
    parameter DEF_LOW_LAT = 0,            // start in the low-latency mode
    parameter OSD_MS = 5000,              // OSD visible this long after a button press
    parameter BAUD = 115200,
    parameter RX_FIRST_MS = 500,          // RX5808 channel write after reset, and its repeat while
    parameter RX_REPEAT_MS = 2000         // no decoder is locked (rx5808_tune.v)
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        btn_ok,            // active high, raw
    input  wire        btn_next,
    // status for the screen (any clock domain; synchronised here)
    input  wire        view_b,            // mixer currently prefers B
    input  wire [1:0]  dec_present,       // decoder answered on I2C
    input  wire [1:0]  dec_locked,        // H + V lock
    // snow meter from the mixer (snow_stats.v, other clock domain: values stable around each toggle)
    input  wire [19:0] snow_a, snow_b,
    input  wire [10:0] use_a, use_b, use_mix,
    input  wire        snow_toggle_a, snow_toggle_b, use_toggle,
    // mixer control
    output wire [1:0]  force_bad,         // [0] mark A bad, [1] mark B bad
    // RX5808
    output wire        rx_spi_clk, rx_spi_data,
    output wire [1:0]  rx_spi_sel_n,
    // OLED text port
    input  wire [1:0]  text_row,
    input  wire [4:0]  text_col,
    output reg  [6:0]  text_char,
    // second text port for the video OSD (same text), and when to show it
    input  wire [1:0]  osd_row,
    input  wire [4:0]  osd_col,
    output reg  [6:0]  osd_char,
    output wire        osd_show,
    // measurement log over the board's USB-UART (one line per meter window, see below)
    input  wire        mix_overflow,      // any domain, level: the mixer has dropped a line since reset
    output wire        uart_txd,
    // state (tests, LEDs)
    output reg  [2:0]  band,
    output reg  [2:0]  ch,
    output reg  [1:0]  mode,              // 0 MIX, 1 A, 2 B
    output reg  [2:0]  field,             // 0 band, 1 channel, 2 mode, 3 latency, 4 page
    output reg         page,              // 0 main, 1 meter
    output reg         low_lat            // 1 = low-latency video (no field buffer)
);
    `include "vtx_channels.vh"
    localparam MS = CLK_HZ / 1000;

    // ---- buttons: sample every ms, accept a level after DEBOUNCE_MS equal samples
    reg [$clog2(MS+1)-1:0] tick_cnt;
    wire tick = (tick_cnt == MS - 1);
    always @(posedge clk) tick_cnt <= (rst || tick) ? 0 : tick_cnt + 1'b1;

    reg [1:0] s_ok, s_next;
    always @(posedge clk) begin s_ok <= {s_ok[0], btn_ok}; s_next <= {s_next[0], btn_next}; end
    reg [7:0] c_ok, c_next;
    reg       d_ok, d_next, ev_ok, ev_next;
    always @(posedge clk) begin
        ev_ok <= 1'b0; ev_next <= 1'b0;
        if (tick) begin
            if (s_ok[1] == d_ok) c_ok <= 0;
            else if (c_ok == DEBOUNCE_MS - 1) begin d_ok <= s_ok[1]; c_ok <= 0; ev_ok <= s_ok[1]; end
            else c_ok <= c_ok + 1'b1;
            if (s_next[1] == d_next) c_next <= 0;
            else if (c_next == DEBOUNCE_MS - 1) begin d_next <= s_next[1]; c_next <= 0; ev_next <= s_next[1]; end
            else c_next <= c_next + 1'b1;
        end
        if (rst) begin c_ok <= 0; c_next <= 0; d_ok <= 0; d_next <= 0; end
    end

    // ---- state
    wire [5:0]  idx  = {3'd0, band} * 6'd8 + {3'd0, ch};
    wire [41:0] chan = vtx_channel(idx);
    wire        legal = chan[41];
    wire [7:0]  band_letter = chan[40:33];
    wire [12:0] freq = chan[32:20];
    wire [19:0] synth = chan[19:0];

    always @(posedge clk) begin
        if (ev_ok) field <= (field == 3'd4) ? 3'd0 : field + 1'b1;
        if (ev_next) case (field)
            3'd0: band <= (band == 3'd5) ? 3'd0 : band + 1'b1;
            3'd1: ch <= ch + 1'b1;                                              // 3 bits wrap 8 -> 1
            3'd2: mode <= (mode == 2'd2) ? 2'd0 : mode + 1'b1;
            3'd3: low_lat <= ~low_lat;
            default: page <= ~page;
        endcase
        if (rst) begin
            band <= DEF_BAND; ch <= DEF_CH; mode <= 2'd0; field <= 3'd0; page <= 1'b0;
            low_lat <= DEF_LOW_LAT[0];
        end
    end
    assign force_bad = {mode == 2'd1, mode == 2'd2};

    // ---- status synchronisers
    reg [1:0] sv, sp0, sp1, sl0, sl1;
    always @(posedge clk) begin
        sv <= {sv[0], view_b};
        sp0 <= {sp0[0], dec_present[0]}; sp1 <= {sp1[0], dec_present[1]};
        sl0 <= {sl0[0], dec_locked[0]};  sl1 <= {sl1[0], dec_locked[1]};
    end

    // ---- RX5808: both modules get the channel RX_FIRST_MS after reset, at once when the band or
    //      channel is stepped, and again every RX_REPEAT_MS while no decoder is locked
    wire chan_step  = ev_next && (field == 3'd0 || field == 3'd1);
    wire any_locked = (sp0[1] && sl0[1]) || (sp1[1] && sl1[1]);
    rx5808_tune #(.CLK_HZ(CLK_HZ), .FIRST_MS(RX_FIRST_MS), .REPEAT_MS(RX_REPEAT_MS)) rx (
        .clk(clk), .rst(rst), .synth(synth), .write_now(chan_step), .any_locked(any_locked),
        .spi_clk(rx_spi_clk), .spi_data(rx_spi_data), .spi_sel_n(rx_spi_sel_n));

    // ---- snow meter: copy values a few clocks after each toggle, flag stale channels,
    //      convert to decimal one value at a time
    localparam STALE = CLK_HZ / 4;                         // 250 ms without a new window = no lines
    reg [2:0] tga, tgb, tgu;
    reg [19:0] va, vb;
    reg [10:0] ua, ub, um;
    reg [$clog2(STALE+1)-1:0] age_a, age_b;
    always @(posedge clk) begin
        tga <= {tga[1:0], snow_toggle_a}; tgb <= {tgb[1:0], snow_toggle_b}; tgu <= {tgu[1:0], use_toggle};
        if (tga[2] != tga[1]) begin va <= snow_a; age_a <= 0; end else if (age_a != STALE) age_a <= age_a + 1'b1;
        if (tgb[2] != tgb[1]) begin vb <= snow_b; age_b <= 0; end else if (age_b != STALE) age_b <= age_b + 1'b1;
        if (tgu[2] != tgu[1]) begin ua <= use_a; ub <= use_b; um <= use_mix; end
        if (rst) begin age_a <= STALE; age_b <= STALE; va <= 0; vb <= 0; ua <= 0; ub <= 0; um <= 0; end
    end
    wire stale_a = (age_a == STALE), stale_b = (age_b == STALE);
    function [6:0] pct(input [10:0] c);                    // c / 1024 * 100, 0..100
        reg [17:0] t;
        begin t = {7'd0, c} * 18'd100; pct = t[16:10]; end
    endfunction

    reg  [2:0]  conv_i;
    reg         conv_start;
    wire        conv_busy, conv_done;
    wire [23:0] conv_bcd;
    reg  [23:0] bcd_a, bcd_b;
    reg  [11:0] bcd_ua, bcd_ub, bcd_um;
    reg  [19:0] conv_in;
    always @* case (conv_i)
        3'd0: conv_in = va; 3'd1: conv_in = vb; 3'd2: conv_in = pct(ua); 3'd3: conv_in = pct(ub);
        default: conv_in = pct(um);
    endcase
    bin2bcd #(.W(20), .D(6)) conv (.clk(clk), .start(conv_start), .bin(conv_in), .busy(conv_busy),
                                   .done(conv_done), .bcd(conv_bcd));
    always @(posedge clk) begin
        conv_start <= 1'b0;
        if (!conv_busy && !conv_start && !conv_done) conv_start <= 1'b1;
        if (conv_done) begin
            case (conv_i)
                3'd0: bcd_a <= conv_bcd; 3'd1: bcd_b <= conv_bcd; 3'd2: bcd_ua <= conv_bcd[11:0];
                3'd3: bcd_ub <= conv_bcd[11:0]; default: bcd_um <= conv_bcd[11:0];
            endcase
            conv_i <= (conv_i == 3'd4) ? 3'd0 : conv_i + 1'b1;
        end
        if (rst) begin conv_i <= 0; bcd_a <= 0; bcd_b <= 0; bcd_ua <= 0; bcd_ub <= 0; bcd_um <= 0; end
    end
    // log2 bar: one block per doubling above 32 (msb index - 5), at most 12 blocks
    function [3:0] bar_len(input [19:0] v);
        integer i;
        reg [4:0] msb;
        begin
            msb = 0;
            for (i = 0; i < 20; i = i + 1) if (v[i]) msb = i;
            bar_len = (v == 0 || msb <= 5) ? 4'd0 : (msb - 5 > 12) ? 4'd12 : msb - 5;
        end
    endfunction
    function [95:0] bar(input [3:0] n);                     // 12 characters
        integer i;
        begin for (i = 0; i < 12; i = i + 1) bar[(11 - i) * 8 +: 8] = (i < n) ? "#" : " "; end
    endfunction
    // 6 digits with leading blanks; "  ----" when stale
    function [47:0] num6(input [23:0] b, input stale);
        integer i;
        reg lead;
        begin
            lead = 1'b1;
            for (i = 5; i >= 0; i = i - 1) begin
                if (b[4*i +: 4] != 0 || i == 0) lead = 1'b0;
                num6[i * 8 +: 8] = lead ? " " : 8'h30 + b[4*i +: 4];
            end
            if (stale) num6 = "  ----";
        end
    endfunction
    function [23:0] num3(input [11:0] b);                   // 0..100, leading blanks
        begin
            num3[23:16] = (b[11:8] != 0) ? 8'h30 + b[11:8] : " ";
            num3[15:8]  = (b[11:8] != 0 || b[7:4] != 0) ? 8'h30 + b[7:4] : " ";
            num3[7:0]   = 8'h30 + b[3:0];
        end
    endfunction

    // ---- text
    function [7:0] dig(input [3:0] d); dig = 8'h30 + d; endfunction
    wire [3:0] f_th = freq / 1000, f_h = (freq / 100) % 10, f_t = (freq / 10) % 10, f_u = freq % 10;
    wire [7:0] m_sel = (field == 3'd0) ? ">" : " ";
    wire [7:0] m_ch  = (field == 3'd1) ? ">" : " ";
    wire [7:0] m_mod = (field == 3'd2) ? ">" : " ";
    wire [7:0] m_lat = (field == 3'd3) ? ">" : " ";
    wire [23:0] mode_s = (mode == 2'd0) ? "MIX" : (mode == 2'd1) ? "A  " : "B  ";
    function [39:0] dec_s(input present, input locked);
        dec_s = !present ? "---- " : locked ? "LOCK " : "NOSIG";
    endfunction
    // 21 characters per row, leftmost character in the top byte
    wire [167:0] row0 = {m_sel, "BAND ", band_letter, "  ", m_ch, "CH ", dig({1'b0, ch} + 4'd1), "  ",
                         dig(f_th), dig(f_h), dig(f_t), dig(f_u), " "};
    wire [167:0] row1 = {m_mod, "MODE ", mode_s, " VIEW ", sv[1] ? "B" : "A", " ", m_lat, low_lat ? "LOW" : "BUF"};
    wire [167:0] row2 = {" A ", dec_s(sp0[1], sl0[1]), "   B ", dec_s(sp1[1], sl1[1]), "   "};
    wire [7:0] m_pg  = (field == 3'd4) ? ">" : " ";
    wire [167:0] row3 = legal ? {m_pg, "SE BAND OK", 80'h20202020202020202020}
                              : {m_pg, "!OUTSIDE SE BAND", 32'h20202020};
    // meter page
    wire [167:0] mrow0 = {m_pg, "METER   ", band_letter, dig({1'b0, ch} + 4'd1), "  ",
                          dig(f_th), dig(f_h), dig(f_t), dig(f_u), "    "};
    wire [167:0] mrow1 = {"A ", num6(bcd_a, stale_a), " ", bar(stale_a ? 4'd0 : bar_len(va))};
    wire [167:0] mrow2 = {"B ", num6(bcd_b, stale_b), " ", bar(stale_b ? 4'd0 : bar_len(vb))};
    wire [167:0] mrow3 = {" USE A", num3(bcd_ua), " B", num3(bcd_ub), " M", num3(bcd_um), "  "};
    reg [167:0] row_sel;
    always @* case ({page, text_row})
        3'd0: row_sel = row0; 3'd1: row_sel = row1; 3'd2: row_sel = row2; 3'd3: row_sel = row3;
        3'd4: row_sel = mrow0; 3'd5: row_sel = mrow1; 3'd6: row_sel = mrow2; default: row_sel = mrow3;
    endcase
    always @(posedge clk)
        text_char <= (text_col < 5'd21) ? row_sel[(20 - text_col) * 8 +: 7] : 7'h20;
    reg [167:0] osd_sel;
    always @* case ({page, osd_row})
        3'd0: osd_sel = row0; 3'd1: osd_sel = row1; 3'd2: osd_sel = row2; 3'd3: osd_sel = row3;
        3'd4: osd_sel = mrow0; 3'd5: osd_sel = mrow1; 3'd6: osd_sel = mrow2; default: osd_sel = mrow3;
    endcase
    always @(posedge clk)
        osd_char <= (osd_col < 5'd21) ? osd_sel[(20 - osd_col) * 8 +: 7] : 7'h20;

    // ---- OSD visibility: OSD_MS after any button event, always on the meter page
    reg [$clog2(OSD_MS+1)-1:0] osd_ms;
    always @(posedge clk) begin
        if (ev_ok || ev_next) osd_ms <= OSD_MS;
        else if (tick && osd_ms != 0) osd_ms <= osd_ms - 1'b1;
        if (rst) osd_ms <= OSD_MS;                         // show briefly after power-up
    end
    assign osd_show = (osd_ms != 0) || page;

    // ---- measurement log: after each mixer-usage window (~65 ms) send one fixed-width line
    //   "S aaaaaa bbbbbb ua_ ub_ um_ Bc ffff MOD o\r\n"  (43 bytes, zero-padded, ------ = no lines)
    //   snow A, snow B, % from A, % from B, % blended, band+channel, MHz, mode (MIX/A/B),
    //   o = "!" once the mixer has dropped a line because its line slots were full, else "-"
    function [47:0] z6(input [23:0] b, input stale);
        integer i;
        begin
            for (i = 0; i < 6; i = i + 1) z6[i * 8 +: 8] = 8'h30 + b[4*i +: 4];
            if (stale) z6 = "------";
        end
    endfunction
    function [23:0] z3(input [11:0] b);
        z3 = {8'h30 + b[11:8], 8'h30 + b[7:4], 8'h30 + b[3:0]};
    endfunction
    reg  [1:0] ovf_s;
    always @(posedge clk) ovf_s <= {ovf_s[0], mix_overflow};
    wire [343:0] log_line = {"S ", z6(bcd_a, stale_a), " ", z6(bcd_b, stale_b), " ", z3(bcd_ua), " ", z3(bcd_ub), " ",
                             z3(bcd_um), " ", band_letter, dig({1'b0, ch} + 4'd1), " ",
                             dig(f_th), dig(f_h), dig(f_t), dig(f_u), " ", mode_s, " ", ovf_s[1] ? "!" : "-", 16'h0D0A};
    localparam LOG_LEN = 43;
    reg  [8:0] log_wait;
    reg  [5:0] log_i;
    reg        log_active, u_send;
    reg  [343:0] log_buf;
    wire       u_busy;
    uart_tx #(.DIV(CLK_HZ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(log_buf[(LOG_LEN - 1 - log_i) * 8 +: 8]),
                                         .busy(u_busy), .txd(uart_txd));
    always @(posedge clk) begin
        u_send <= 1'b0;
        if (tgu[2] != tgu[1] && !log_active) log_wait <= 9'd1;          // new window: wait for the decimal values
        else if (log_wait != 0) begin
            log_wait <= log_wait + 1'b1;
            if (log_wait == 9'd400) begin log_wait <= 0; log_buf <= log_line; log_i <= 0; log_active <= 1'b1; end
        end
        if (log_active && !u_busy && !u_send) begin
            u_send <= 1'b1;
        end
        if (u_send) begin
            if (log_i == LOG_LEN - 1) log_active <= 1'b0; else log_i <= log_i + 1'b1;
        end
        if (rst) begin log_wait <= 0; log_active <= 1'b0; log_i <= 0; end
    end
endmodule
`default_nettype wire
