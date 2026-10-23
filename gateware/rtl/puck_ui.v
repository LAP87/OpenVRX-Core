// Puck prototype UI: two buttons, a 128 x 32 OLED (4 x 21 characters; the top two rows are drawn as
// one double-size row of 10 characters on the flight view and in the menu, ssd1306_text.v text_big),
// RX5808 tuning.
//
// Pages: the flight view (start), two information pages and the menu. The two buttons have no
// names: the screen shows them as arrows (font5x7.py "v" and "^"): v = S1 on the Tang Nano 20K,
// ^ = S2 (owner, 2026-10-20).
//   flight view   ^ -> menu, v -> meter page
//   meter page    ^ -> menu, v -> RSSI page
//   RSSI page     ^ -> calibration on / off, v -> flight view (leaving the page ends a calibration)
//   menu          v -> next item (after the last one: flight view), ^ -> change the item; MENU_MS
//                 after the last button it returns to the flight view by itself (not during a scan)
// Items, one per screen: BAND, CH, MODE (MIX / A / B), LAT (BUF / LOW), FILT (TV / VCR), HDMI (FULL /
// LTD; "N/A" in the DVI build, HDMI_BUILD = 0, where ^ leaves it), SCAN (^ starts, any button
// aborts and leaves the SCAN screen as it was; a scan that found a channel ends on the flight view,
// one that found none says NONE until the next button), HOLD (ON: BAND, CH and SCAN do not react and the flight view shows a padlock;
// not saved, OFF after reset).
//
// Flight view (row 0 double size: 10 characters; rows 2 and 3: 21 characters):
//   F4 5800  @              band + channel, MHz, "!" outside 5725-5875 MHz, padlock while HOLD is on
//   A:LOCK  75 B:NOSIG --   per receiver: decoder LOCK / NOSIG / ---- (absent) and the calibrated
//                           RSSI (" --" uncalibrated, "  ?" no reading)
//   MIX BUF TV      SAVED   mode, latency, filter, and the saved settings (flash_store.v): SAVED (the
//                           flash holds these settings), UNSAVED (changed; written SAVE_MS after the last
//                           change), SAVE ERR (a write did not read back), DEFAULTS (no record in the
//                           flash and nothing changed yet), blank until the start scan is over
// Menu (row 0 double size: item and value; row 2: what the value means; row 3: what the buttons do):
//   CH F4                   F4 5800 MHZ  SE OK        ^ CHANGE  v NEXT ITEM
// The OSD shows the same characters in one size (osd_overlay.v).
//
// Band/channel changes reprogram both RX5808 modules at once with the synth
// register from vtx_channels.vh. The first write comes 0.5 s after reset, and
// the channel is written again every 2 s for as long as no decoder is locked
// (rx5808_tune.v).
// Mode MIX lets the line mixer choose; A or B forces one receiver by marking
// the other one "bad" (same input the decoder lock status uses).
// Latency BUF shows the video through the SDRAM field buffer; LOW bypasses it
// and locks the HDMI output to the input fields (fb_backend.v low-latency mode).
// SCAN (chan_scan.v) steps through all 48 channels and keeps the one where a decoder locks with
// the lowest noise; any button aborts it on the channel it started from.
// Saved settings (flash_store.v): `set_load` at start puts the saved band, channel, mode, latency,
// filter and HDMI range in place (the filter as a request to the decoders, like ^ on the filter).
//
// Meter page ("snow meter", self-interference / signal check):
//    METER   F4  5800
//   A  12345 #######          mean line HF energy (snow) of receiver A over 1024 lines,
//   B   2345 ####             bar = log2 (one block per doubling); "  ----" = no lines
//    USE A 40 B 35 M 25       % of the last 1024 mixer decisions: A, B, blend
//
// RSSI page (rssi_adc.v; values of the last round, "-----" without a reading):
//    RSSI    F4  5800
//   A 12345  45               raw code, calibrated % ("---" uncalibrated), LOW (below the
//   B  4567   3  LOW WEAK     threshold N rounds in a row) and WEAK (the mixer avoids it);
//                             the font has no % sign
//   ^ CAL OFF   A OK B --     calibration: ^ turns it on, move the transmitter far and near
//                             (or tune away and back), ^ again; OK = range accepted.
//                             Leaving the page ends a calibration.
//
// Development commands (DEVCMD = 1, build option DEVCMD=1; off in the product build until the owner decides,
// hub docs/NATTPASS_2026-10-23.md B4): single bytes on uart_rxd at BAUD 8N1, from the PC through the BL616.
// Each sets a value (repeating it changes nothing), and each accepted byte shows in the next log line.
//   B / L    latency BUF / LOW            T / V    filter TV / VCR (a request to both decoders, like the menu)
//   m / a / b  mode MIX / force A / force B
//   H / h    HOLD on / off                + / -    channel up / down through all 48 (band by band, wrapping);
//                                                  ignored while HOLD is on or a scan runs, like the menu
//   O / o / *  OSD always on / always off / as the buttons decide (after reset)
//   ?        one status line ("Q ...", below) after the current log line
//   D / F    field dump from decoder A / from the field store (dump_req, field_dump.v)
// Other bytes are ignored and not counted. A setting changed this way is saved to the flash like a menu change.
// The log line then carries 12 more bytes before CR LF (101 bytes): latency, HOLD (H / -), OSD (A buttons,
// O on, - off), the last accepted byte and the count of accepted bytes (two hex digits each, wrapping):
//   "S ... -W 2 LOW HA 4C07\r\n"
// The status line (52 bytes):
//   "Q A 5D 100E 0D 00 B -- ---- -- 00 T 2 D 5C 0115200\r\n"
// per decoder: the address it answers at (5C / 5D, NA no answer, -- start-up not finished), 89h 88h of the last
// whole poll round (---- not valid), 03h as last read (-- not read yet), times found reset (hex); then the SDRAM
// self-test as in the log line, the build: H HDMI / D DVI, the address tried first (TVP_ADDR), the UART rate.
`default_nettype none
module puck_ui #(
    parameter CLK_HZ = 27_000_000,
    parameter DEBOUNCE_MS = 20,
    parameter [2:0] DEF_BAND = 3'd3,      // F
    parameter [2:0] DEF_CH = 3'd3,        // 4th channel -> F4 5800 MHz (legal in Sweden)
    parameter DEF_LOW_LAT = 0,            // start in the low-latency mode
    parameter OSD_MS = 5000,              // OSD visible this long after a button press
    parameter MENU_MS = 15000,            // the menu returns to the flight view after this without a button
    parameter HDMI_BUILD = 1,             // 0: the HDMI item says N/A (the DVI build ignores the range)
    parameter BAUD = 115200,
    parameter RX_FIRST_MS = 500,          // RX5808 channel write after reset, and its repeat while
    parameter RX_REPEAT_MS = 2000,        // no decoder is locked (rx5808_tune.v)
    parameter HEARTBEAT_MS = 1000,        // a log line also when no mixer window came for this long (0: off)
    parameter DEVCMD = 0,                 // 1: development commands on uart_rxd (see above)
    parameter [6:0] TVP_FIRST = 7'h5C     // the decoders' address tried first (status line; tvp_ctrl DEV0/DEV1)
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        btn_down,          // S1, "v": next item / next page (active high, raw)
    input  wire        btn_up,            // S2, "^": change the value / open the menu / calibration
    // status for the screen (any clock domain; synchronised here)
    input  wire        view_b,            // mixer currently prefers B
    input  wire [1:0]  dec_present,       // decoder answered on I2C
    input  wire [1:0]  dec_locked,        // H + V lock
    // decoder poll rounds (tvp_ctrl.v round_ok, this clock domain): a pulse per whole round that
    // found the decoder up, and that round's 88h bit 4 ("lost lock since 88h was last read")
    input  wire [1:0]  dec_round,
    input  wire [1:0]  dec_lost,
    // snow meter from the mixer (snow_stats.v, other clock domain: values stable around each toggle)
    input  wire [19:0] snow_a, snow_b,
    input  wire [10:0] use_a, use_b, use_mix,
    input  wire        snow_toggle_a, snow_toggle_b, use_toggle,
    // noise meter (noise_stats.v, same domain and handshake): luma samples outside 16..235 per 1024 lines
    input  wire [19:0] noise_a, noise_b,
    input  wire        noise_toggle_a, noise_toggle_b,
    // RSSI (rssi_adc.v, this clock domain, stable between its `done` pulses)
    input  wire [15:0] rssi_a, rssi_b,
    input  wire [1:0]  rssi_valid, rssi_cal_ok, rssi_low, rssi_warn,
    input  wire [6:0]  rssi_pct_a, rssi_pct_b,
    output reg         rssi_cal,          // calibration mode (level), ^ on the RSSI page
    // saved settings (flash_store.v): one clock at start, and the state of the record for the screen
    input  wire        set_load,
    input  wire [2:0]  set_band, set_ch,
    input  wire [1:0]  set_mode,
    input  wire        set_low_lat, set_filter, set_hdmi,
    input  wire        set_ready,         // the start scan is over (levels, this clock domain)
    input  wire        set_dirty,         // the settings differ from the newest record
    input  wire        set_stored,        // the flash holds a record
    input  wire        set_err,           // a write did not read back
    output wire        scan_busy,
    output reg         ch_hold,           // HOLD: band, channel and SCAN do not react (not saved)
    // mixer control
    output wire [1:0]  force_bad,         // [0] mark A bad, [1] mark B bad
    // RX5808
    output wire        rx_spi_clk, rx_spi_data,
    output wire [1:0]  rx_spi_sel_n,
    // OLED text port (ssd1306_text.v)
    input  wire [1:0]  text_row,
    input  wire [4:0]  text_col,
    output reg  [6:0]  text_char,
    output wire [1:0]  text_big,          // row pair 0-1 double size (flight view, menu)
    // second text port for the video OSD (same text), and when to show it
    input  wire [1:0]  osd_row,
    input  wire [4:0]  osd_col,
    output reg  [6:0]  osd_char,
    output wire        osd_show,
    // measurement log over the board's USB-UART (one line per meter window, see below)
    input  wire        mix_overflow,      // any domain, level: the mixer has dropped a line since reset
    input  wire [3:0]  sdram_test,        // {done, ok[2:0]}: the SDRAM self-test (sdram_selftest.v), ok steady once done
    output wire        uart_txd,
    // state (tests, LEDs)
    output reg  [2:0]  band,
    output reg  [2:0]  ch,
    output reg  [1:0]  mode,              // 0 MIX, 1 A, 2 B
    output reg  [2:0]  field,             // menu item: 0 BAND, 1 CH, 2 MODE, 3 LAT, 4 FILT, 5 HDMI, 6 SCAN, 7 HOLD
    output reg  [1:0]  page,              // 0 flight view, 1 meter, 2 RSSI, 3 menu
    output reg         low_lat,           // 1 = low-latency video (no field buffer)
    output reg         filter_vcr,        // 0 TV (default), 1 VCR; persistent controller request value
    output reg         filter_changed,    // one-clock pulse for ^ on the filter item and for set_load
    output reg         hdmi_ltd,          // 0 FULL (default), 1 LTD: HDMI limited range (tmds_link.v)
    // development commands (DEVCMD = 1; unused and unconnected otherwise)
    input  wire        uart_rxd,          // BAUD 8N1 from the board's USB-UART
    input  wire        dec_init_done,     // tvp_ctrl, this clock domain: for the status line
    input  wire [1:0]  dec_err, dec_valid, dec_alt, dec_misc_ok,
    input  wire [15:0] dec_st0, dec_st1,  // {89h, 88h}
    input  wire [7:0]  dec_misc0, dec_misc1, dec_ri0, dec_ri1,
    output reg  [1:0]  dump_req           // one-clock pulse: [0] dump a field from decoder A, [1] from the field store
);
    `include "vtx_channels.vh"
    localparam MS = CLK_HZ / 1000;
    localparam [1:0] P_FLY = 2'd0, P_MET = 2'd1, P_RSSI = 2'd2, P_MENU = 2'd3;
    localparam [2:0] F_BAND = 3'd0, F_CH = 3'd1, F_MODE = 3'd2, F_LAT = 3'd3, F_FILT = 3'd4, F_HDMI = 3'd5,
                     F_SCAN = 3'd6, F_HOLD = 3'd7;

    // ---- buttons: sample every ms, accept a level after DEBOUNCE_MS equal samples
    reg [$clog2(MS+1)-1:0] tick_cnt;
    wire tick = (tick_cnt == MS - 1);
    always @(posedge clk) tick_cnt <= (rst || tick) ? 0 : tick_cnt + 1'b1;

    reg [1:0] s_down, s_up;
    always @(posedge clk) begin s_down <= {s_down[0], btn_down}; s_up <= {s_up[0], btn_up}; end
    reg [7:0] c_down, c_up;
    reg       d_down, d_up, ev_down, ev_up;
    always @(posedge clk) begin
        ev_down <= 1'b0; ev_up <= 1'b0;
        if (tick) begin
            if (s_down[1] == d_down) c_down <= 0;
            else if (c_down == DEBOUNCE_MS - 1) begin d_down <= s_down[1]; c_down <= 0; ev_down <= s_down[1]; end
            else c_down <= c_down + 1'b1;
            if (s_up[1] == d_up) c_up <= 0;
            else if (c_up == DEBOUNCE_MS - 1) begin d_up <= s_up[1]; c_up <= 0; ev_up <= s_up[1]; end
            else c_up <= c_up + 1'b1;
        end
        if (rst) begin c_down <= 0; c_up <= 0; d_down <= 0; d_up <= 0; end
    end

    // ---- state
    // The channel table lookup is registered (chan), together with the decimal digits of its
    // frequency (freq_bcd: the divisions act on constants, one per table entry, and fold away in
    // synthesis). No combinational path runs from the menu state through the table into the RX5808
    // shift register or the text. The SPI write starts one clock after chan has the new channel
    // (chan_step_d below).
    function [15:0] freq_bcd(input [5:0] i);
        integer k;
        reg [41:0] c;
        reg [12:0] f, d3, d2, d1, d0;
        begin
            freq_bcd = 16'd0;
            for (k = 0; k < 64; k = k + 1)
                if (i == k) begin
                    c = vtx_channel(k);
                    f = c[32:20];
                    d3 = f / 1000; d2 = (f / 100) % 10; d1 = (f / 10) % 10; d0 = f % 10;
                    freq_bcd = {d3[3:0], d2[3:0], d1[3:0], d0[3:0]};
                end
        end
    endfunction
    wire [5:0]  idx  = {band, ch};                         // band * 8 + ch
    reg  [41:0] chan;
    reg  [15:0] fbcd;
    always @(posedge clk) begin chan <= vtx_channel(idx); fbcd <= freq_bcd(idx); end
    wire        legal = chan[41];
    wire [7:0]  band_letter = chan[40:33];
    wire [19:0] synth = chan[19:0];

    // ---- channel scan (SCAN in the menu); any button during a scan aborts it
    wire       scan_tune, scan_done, scan_found;
    wire [5:0] scan_idx;
    reg        scan_none;                                  // the last scan found nothing (until a button)
    reg        scan_abort_d;                               // an abort was issued the clock before (its done)
    reg        new_na, new_nb;                             // a new noise value is in na / nb
    wire       ui_down = ev_down && !scan_busy, ui_up = ev_up && !scan_busy;
    wire       item_blocked = ch_hold && (field == F_BAND || field == F_CH || field == F_SCAN);
    chan_scan #(.CLK_HZ(CLK_HZ)) scan (
        .clk(clk), .rst(rst), .start(ui_up && page == P_MENU && field == F_SCAN && !ch_hold),
        .abort(scan_busy && (ev_down || ev_up)), .cur_idx({band, ch}),
        .locked({sp1[1] && sl1[1], sp0[1] && sl0[1]}), .new_a(new_na), .new_b(new_nb), .noise_a(na), .noise_b(nb),
        .busy(scan_busy), .idx(scan_idx), .tune(scan_tune), .done(scan_done), .found(scan_found));
    always @(posedge clk) begin
        scan_abort_d <= scan_busy && (ev_down || ev_up);
        if (scan_done && !scan_found && !scan_abort_d) scan_none <= 1'b1;
        else if (ev_down || ev_up) scan_none <= 1'b0;
        if (rst) begin scan_none <= 1'b0; scan_abort_d <= 1'b0; end
    end

    // the menu returns to the flight view MENU_MS after the last button (a scan holds it)
    reg [$clog2(MENU_MS+1)-1:0] menu_ms;
    always @(posedge clk) begin
        if (page != P_MENU || scan_busy || ev_down || ev_up) menu_ms <= MENU_MS;
        else if (tick && menu_ms != 0) menu_ms <= menu_ms - 1'b1;
        if (rst) menu_ms <= MENU_MS;
    end
    wire menu_timeout = (page == P_MENU) && (menu_ms == 0) && !scan_busy;

    // ---- development commands (DEVCMD = 1): one byte from uart_rx, decoded here; cmd_ok marks the bytes that
    //      are commands (the others are dropped without a trace)
    wire       rx_valid;
    wire [7:0] rx_byte;
    generate if (DEVCMD != 0) begin : g_cmd_rx
        uart_rx #(.DIV(CLK_HZ / BAUD)) urx (.clk(clk), .rst(rst), .rxd(uart_rxd), .valid(rx_valid), .data(rx_byte));
    end else begin : g_no_cmd_rx
        assign rx_valid = 1'b0;
        assign rx_byte = 8'd0;
    end endgenerate
    reg cmd_ok;
    always @* case (rx_byte)
        "B", "L", "T", "V", "m", "a", "b", "H", "h", "+", "-", "O", "o", "*", "?", "D", "F": cmd_ok = 1'b1;
        default: cmd_ok = 1'b0;
    endcase
    wire       cmd = (DEVCMD != 0) && rx_valid && cmd_ok;
    wire       cmd_step = cmd && (rx_byte == "+" || rx_byte == "-") && !ch_hold && !scan_busy;
    wire [5:0] idx_up = (ch != 3'd7) ? {band, ch + 3'd1} : {(band == 3'd5) ? 3'd0 : band + 3'd1, 3'd0};
    wire [5:0] idx_dn = (ch != 3'd0) ? {band, ch - 3'd1} : {(band == 3'd0) ? 3'd5 : band - 3'd1, 3'd7};
    reg  [1:0] osd_force;                                  // 0 the buttons decide, 1 always on, 2 always off
    reg  [7:0] cmd_last, cmd_count;
    reg        q_req;                                      // a status line is due
    wire       q_take;                                     // ... and is copied for sending this clock
    always @(posedge clk) begin
        dump_req <= 2'b00;
        if (q_take) q_req <= 1'b0;
        if (cmd) begin
            cmd_last <= rx_byte;
            cmd_count <= cmd_count + 1'b1;
            case (rx_byte)
                "O": osd_force <= 2'd1;
                "o": osd_force <= 2'd2;
                "*": osd_force <= 2'd0;
                "?": q_req <= 1'b1;
                "D": dump_req[0] <= 1'b1;
                "F": dump_req[1] <= 1'b1;
                default: ;
            endcase
        end
        if (rst) begin osd_force <= 2'd0; cmd_last <= 8'h00; cmd_count <= 8'h00; q_req <= 1'b0; dump_req <= 2'b00; end
    end

    always @(posedge clk) begin
        filter_changed <= 1'b0;
        if (menu_timeout) page <= P_FLY;
        if (ui_down) case (page)                       // v: next page, next item
            P_FLY:  page <= P_MET;
            P_MET:  page <= P_RSSI;
            P_RSSI: page <= P_FLY;
            default: if (field == F_HOLD) page <= P_FLY; else field <= field + 1'b1;
        endcase
        if (ui_up) case (page)                         // ^: the menu, the calibration, the value
            P_FLY, P_MET: begin page <= P_MENU; field <= F_BAND; end
            P_RSSI:       rssi_cal <= ~rssi_cal;
            default: if (!item_blocked) case (field)
                F_BAND: band <= (band == 3'd5) ? 3'd0 : band + 1'b1;
                F_CH:   ch <= ch + 1'b1;                                        // 3 bits wrap 8 -> 1
                F_MODE: mode <= (mode == 2'd2) ? 2'd0 : mode + 1'b1;
                F_LAT:  low_lat <= ~low_lat;
                F_FILT: begin filter_vcr <= ~filter_vcr; filter_changed <= 1'b1; end
                F_HDMI: if (HDMI_BUILD != 0) hdmi_ltd <= ~hdmi_ltd;
                F_HOLD: ch_hold <= ~ch_hold;
                default: ;                                                      // SCAN: chan_scan above
            endcase
        endcase
        if (cmd) case (rx_byte)                        // development commands (above); each one line
            "B": low_lat <= 1'b0;
            "L": low_lat <= 1'b1;
            "T": begin filter_vcr <= 1'b0; filter_changed <= 1'b1; end
            "V": begin filter_vcr <= 1'b1; filter_changed <= 1'b1; end
            "m": mode <= 2'd0;
            "a": mode <= 2'd1;
            "b": mode <= 2'd2;
            "H": ch_hold <= 1'b1;
            "h": ch_hold <= 1'b0;
            "+": if (cmd_step) {band, ch} <= idx_up;
            "-": if (cmd_step) {band, ch} <= idx_dn;
            default: ;
        endcase
        if (scan_tune) {band, ch} <= scan_idx;
        if (scan_done && scan_found) page <= P_FLY;        // the picture on the channel it found
        if (page != P_RSSI) rssi_cal <= 1'b0;              // leaving the RSSI page ends a calibration
        if (set_load) begin
            band <= set_band; ch <= set_ch; mode <= (set_mode == 2'd3) ? 2'd0 : set_mode;
            low_lat <= set_low_lat; filter_vcr <= set_filter; filter_changed <= 1'b1; hdmi_ltd <= set_hdmi;
        end
        if (rst) begin
            band <= DEF_BAND; ch <= DEF_CH; mode <= 2'd0; field <= F_BAND; page <= P_FLY; rssi_cal <= 1'b0;
            low_lat <= DEF_LOW_LAT[0]; ch_hold <= 1'b0;
            filter_vcr <= 1'b0; filter_changed <= 1'b0; hdmi_ltd <= 1'b0;
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
    //      (band/ch change on the clock after ev_up, chan one clock later: write_now is delayed one
    //      clock so that rx5808_tune sees the new synth word one clock after write_now, as before)
    wire chan_step  = (ui_up && page == P_MENU && !item_blocked && (field == F_BAND || field == F_CH)) || scan_tune
                      || cmd_step;
    reg  chan_step_d;
    always @(posedge clk) chan_step_d <= chan_step && !rst;
    wire any_locked = (sp0[1] && sl0[1]) || (sp1[1] && sl1[1]);
    rx5808_tune #(.CLK_HZ(CLK_HZ), .FIRST_MS(RX_FIRST_MS), .REPEAT_MS(RX_REPEAT_MS)) rx (
        .clk(clk), .rst(rst), .synth(synth), .write_now(chan_step_d), .any_locked(any_locked),
        .spi_clk(rx_spi_clk), .spi_data(rx_spi_data), .spi_sel_n(rx_spi_sel_n));

    // ---- snow meter: copy values a few clocks after each toggle, flag stale channels,
    //      convert to decimal one value at a time
    localparam STALE = CLK_HZ / 4;                         // 250 ms without a new window = no lines
    reg [2:0] tga, tgb, tgu, tna, tnb;
    reg [19:0] va, vb, na, nb;
    reg [10:0] ua, ub, um;
    reg [$clog2(STALE+1)-1:0] age_a, age_b;
    always @(posedge clk) begin
        tga <= {tga[1:0], snow_toggle_a}; tgb <= {tgb[1:0], snow_toggle_b}; tgu <= {tgu[1:0], use_toggle};
        tna <= {tna[1:0], noise_toggle_a}; tnb <= {tnb[1:0], noise_toggle_b};
        if (tga[2] != tga[1]) begin va <= snow_a; age_a <= 0; end else if (age_a != STALE) age_a <= age_a + 1'b1;
        if (tgb[2] != tgb[1]) begin vb <= snow_b; age_b <= 0; end else if (age_b != STALE) age_b <= age_b + 1'b1;
        if (tgu[2] != tgu[1]) begin ua <= use_a; ub <= use_b; um <= use_mix; end
        if (tna[2] != tna[1]) na <= noise_a;
        if (tnb[2] != tnb[1]) nb <= noise_b;
        new_na <= (tna[2] != tna[1]); new_nb <= (tnb[2] != tnb[1]);
        if (rst) begin age_a <= STALE; age_b <= STALE; va <= 0; vb <= 0; ua <= 0; ub <= 0; um <= 0; na <= 0; nb <= 0; end
    end
    wire stale_a = (age_a == STALE), stale_b = (age_b == STALE);
    function [6:0] pct(input [10:0] c);                    // c / 1024 * 100, 0..100
        reg [17:0] t;
        begin t = {7'd0, c} * 18'd100; pct = t[16:10]; end
    endfunction

    reg  [3:0]  conv_i;
    reg         conv_start;
    wire        conv_busy, conv_done;
    wire [23:0] conv_bcd;
    reg  [23:0] bcd_a, bcd_b, bcd_na, bcd_nb;
    reg  [11:0] bcd_ua, bcd_ub, bcd_um, bcd_pa, bcd_pb;
    reg  [23:0] bcd_ra, bcd_rb;
    reg  [19:0] conv_in;
    always @* case (conv_i)
        4'd0: conv_in = va; 4'd1: conv_in = vb; 4'd2: conv_in = pct(ua); 4'd3: conv_in = pct(ub);
        4'd4: conv_in = pct(um); 4'd5: conv_in = na; 4'd6: conv_in = nb;
        4'd7: conv_in = {4'd0, rssi_a}; 4'd8: conv_in = {4'd0, rssi_b};
        4'd9: conv_in = {13'd0, rssi_pct_a}; default: conv_in = {13'd0, rssi_pct_b};
    endcase
    bin2bcd #(.W(20), .D(6)) conv (.clk(clk), .start(conv_start), .bin(conv_in), .busy(conv_busy),
                                   .done(conv_done), .bcd(conv_bcd));
    always @(posedge clk) begin
        conv_start <= 1'b0;
        if (!conv_busy && !conv_start && !conv_done) conv_start <= 1'b1;
        if (conv_done) begin
            case (conv_i)
                4'd0: bcd_a <= conv_bcd; 4'd1: bcd_b <= conv_bcd; 4'd2: bcd_ua <= conv_bcd[11:0];
                4'd3: bcd_ub <= conv_bcd[11:0]; 4'd4: bcd_um <= conv_bcd[11:0];
                4'd5: bcd_na <= conv_bcd; 4'd6: bcd_nb <= conv_bcd;
                4'd7: bcd_ra <= conv_bcd; 4'd8: bcd_rb <= conv_bcd;
                4'd9: bcd_pa <= conv_bcd[11:0]; default: bcd_pb <= conv_bcd[11:0];
            endcase
            conv_i <= (conv_i == 4'd10) ? 4'd0 : conv_i + 1'b1;
        end
        if (rst) begin
            conv_i <= 0; bcd_a <= 0; bcd_b <= 0; bcd_ua <= 0; bcd_ub <= 0; bcd_um <= 0; bcd_na <= 0; bcd_nb <= 0;
            bcd_ra <= 0; bcd_rb <= 0; bcd_pa <= 0; bcd_pb <= 0;
        end
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

    // 5 digits with leading blanks; "-----" without a reading
    function [39:0] num5(input [23:0] b, input none);
        integer i;
        reg lead;
        begin
            lead = 1'b1;
            for (i = 4; i >= 0; i = i - 1) begin
                if (b[4*i +: 4] != 0 || i == 0) lead = 1'b0;
                num5[i * 8 +: 8] = lead ? " " : 8'h30 + b[4*i +: 4];
            end
            if (none) num5 = "-----";
        end
    endfunction

    // ---- text: 21 characters per row, leftmost character in the top byte; a double-size row has 10
    //      and the row under it is not drawn (the OSD shows its blank row)
    function [7:0] dig(input [3:0] d); dig = 8'h30 + d; endfunction
    wire [3:0]  f_th = fbcd[15:12], f_h = fbcd[11:8], f_t = fbcd[7:4], f_u = fbcd[3:0];   // see "state"
    wire [31:0] mhz = {dig(f_th), dig(f_h), dig(f_t), dig(f_u)};
    wire [7:0]  ch_dig = dig({1'b0, ch} + 4'd1);
    wire [23:0] mode_s = (mode == 2'd0) ? "MIX" : (mode == 2'd1) ? "A  " : "B  ";
    function [39:0] dec_s(input present, input locked);
        dec_s = !present ? "---- " : locked ? "LOCK " : "NOSIG";
    endfunction
    function [23:0] pct3(input valid, input cal_ok, input [11:0] b);   // calibrated RSSI, 3 characters
        pct3 = !valid ? "  ?" : !cal_ok ? " --" : num3(b);
    endfunction
    // the saved settings (flash_store.v), 9 characters, right-aligned
    wire [71:0] save_s = !set_ready ? "         " : set_err ? " SAVE ERR" : set_dirty ? "  UNSAVED"
                       : set_stored ? "    SAVED" : " DEFAULTS";
    // flight view
    wire [167:0] frow0 = {band_letter, ch_dig, " ", mhz, " ", legal ? " " : "!", ch_hold ? "@" : " ", {11{8'h20}}};
    wire [167:0] blank = {21{8'h20}};
    wire [167:0] frow2 = {"A:", dec_s(sp0[1], sl0[1]), pct3(rssi_valid[0], rssi_cal_ok[0], bcd_pa), " ",
                          "B:", dec_s(sp1[1], sl1[1]), pct3(rssi_valid[1], rssi_cal_ok[1], bcd_pb)};
    wire [167:0] frow3 = {mode_s, " ", low_lat ? "LOW" : "BUF", " ", filter_vcr ? "VCR" : "TV ", " ", save_s};
    // menu: one item per screen
    wire [167:0] chan_s = {band_letter, ch_dig, " ", mhz, " MHZ  ", legal ? "SE OK" : "!SE  ", "   "};
    reg  [79:0]  mbig;
    reg  [167:0] mrow2, mrow3;
    always @* begin
        mrow3 = (field == F_HOLD) ? "^ CHANGE  v EXIT     " : "^ CHANGE  v NEXT ITEM";
        case (field)
            F_BAND: begin mbig = {"BAND ", band_letter, "    "}; mrow2 = chan_s; end
            F_CH:   begin mbig = {"CH ", band_letter, ch_dig, "     "}; mrow2 = chan_s; end
            F_MODE: begin
                mbig = {"MODE ", mode_s, "  "};
                mrow2 = (mode == 2'd0) ? "MIX: BOTH RECEIVERS  " : (mode == 2'd1) ? "A: RECEIVER A ONLY   "
                      : "B: RECEIVER B ONLY   ";
            end
            F_LAT:  begin
                mbig = {"LAT ", low_lat ? "LOW" : "BUF", "   "};
                mrow2 = low_lat ? "LOW: FOLLOWS INPUT   " : "BUF: STEADY TIMING   ";
            end
            F_FILT: begin mbig = {"FILT ", filter_vcr ? "VCR" : "TV ", "  "}; mrow2 = "DECODER MODE REQUEST "; end
            F_HDMI: begin
                mbig = {"HDMI ", (HDMI_BUILD == 0) ? "N/A  " : hdmi_ltd ? "LTD  " : "FULL "};
                mrow2 = (HDMI_BUILD == 0) ? "DVI BUILD: NO EFFECT " : hdmi_ltd ? "RGB 16-235 LIMITED   "
                      : "RGB 0-255 FULL       ";
                if (HDMI_BUILD == 0) mrow3 = "^ N/A     v NEXT ITEM";
            end
            F_SCAN: begin
                mbig = scan_busy ? "SCANNING  " : scan_none ? "SCAN NONE " : "SCAN      ";
                mrow2 = scan_busy ? {"TRYING ", band_letter, ch_dig, " ", mhz, " MHZ   "}
                      : scan_none ? "NO LOCKED CHANNEL    " : "SEARCH 48 CHANNELS   ";
                mrow3 = scan_busy ? "ANY BUTTON ABORTS    " : "^ START   v NEXT ITEM";
            end
            default: begin mbig = {"HOLD ", ch_hold ? "ON " : "OFF", "  "}; mrow2 = "ON: LOCKS CH AND SCAN"; end
        endcase
        if (item_blocked && !scan_busy) mrow3 = "HOLD ON   v NEXT ITEM";
    end
    wire [167:0] mrow0 = {mbig, {11{8'h20}}};
    // meter page
    wire [167:0] trow0 = {" METER   ", band_letter, ch_dig, "  ", mhz, "    "};
    wire [167:0] trow1 = {"A ", num6(bcd_a, stale_a), " ", bar(stale_a ? 4'd0 : bar_len(va))};
    wire [167:0] trow2 = {"B ", num6(bcd_b, stale_b), " ", bar(stale_b ? 4'd0 : bar_len(vb))};
    wire [167:0] trow3 = {" USE A", num3(bcd_ua), " B", num3(bcd_ub), " M", num3(bcd_um), "  "};
    // RSSI page
    wire [167:0] rrow0 = {" RSSI    ", band_letter, ch_dig, "  ", mhz, "    "};
    wire [167:0] rrow1 = {"A ", num5(bcd_ra, !rssi_valid[0]), " ", rssi_cal_ok[0] ? num3(bcd_pa) : "---", "  ",
                          rssi_low[0] ? "LOW " : "    ", rssi_warn[0] ? "WEAK" : "    "};
    wire [167:0] rrow2 = {"B ", num5(bcd_rb, !rssi_valid[1]), " ", rssi_cal_ok[1] ? num3(bcd_pb) : "---", "  ",
                          rssi_low[1] ? "LOW " : "    ", rssi_warn[1] ? "WEAK" : "    "};
    wire [167:0] rrow3 = {"^ CAL ", rssi_cal ? "ON " : "OFF", "   A ", rssi_cal_ok[0] ? "OK" : "--",
                          " B ", rssi_cal_ok[1] ? "OK" : "--"};
    // (two always blocks, not a function: a function reading the row wires would only be re-evaluated
    // in simulation when its arguments change, and the OSD port's row changes rarely)
    reg [167:0] row_sel, osd_sel;
    always @* case ({page, text_row})
        4'd0: row_sel = frow0; 4'd1: row_sel = blank; 4'd2: row_sel = frow2; 4'd3: row_sel = frow3;
        4'd4: row_sel = trow0; 4'd5: row_sel = trow1; 4'd6: row_sel = trow2; 4'd7: row_sel = trow3;
        4'd8: row_sel = rrow0; 4'd9: row_sel = rrow1; 4'd10: row_sel = rrow2; 4'd11: row_sel = rrow3;
        4'd12: row_sel = mrow0; 4'd13: row_sel = blank; 4'd14: row_sel = mrow2; default: row_sel = mrow3;
    endcase
    always @* case ({page, osd_row})
        4'd0: osd_sel = frow0; 4'd1: osd_sel = blank; 4'd2: osd_sel = frow2; 4'd3: osd_sel = frow3;
        4'd4: osd_sel = trow0; 4'd5: osd_sel = trow1; 4'd6: osd_sel = trow2; 4'd7: osd_sel = trow3;
        4'd8: osd_sel = rrow0; 4'd9: osd_sel = rrow1; 4'd10: osd_sel = rrow2; 4'd11: osd_sel = rrow3;
        4'd12: osd_sel = mrow0; 4'd13: osd_sel = blank; 4'd14: osd_sel = mrow2; default: osd_sel = mrow3;
    endcase
    always @(posedge clk) begin
        text_char <= (text_col < 5'd21) ? row_sel[(20 - text_col) * 8 +: 7] : 7'h20;
        osd_char <= (osd_col < 5'd21) ? osd_sel[(20 - osd_col) * 8 +: 7] : 7'h20;
    end
    assign text_big = {1'b0, (page == P_FLY) || (page == P_MENU)};

    // ---- OSD visibility: OSD_MS after any button event, always on the information pages and in the menu
    reg [$clog2(OSD_MS+1)-1:0] osd_ms;
    always @(posedge clk) begin
        if (ev_down || ev_up) osd_ms <= OSD_MS;
        else if (tick && osd_ms != 0) osd_ms <= osd_ms - 1'b1;
        if (rst) osd_ms <= OSD_MS;                         // show briefly after power-up
    end
    assign osd_show = (osd_force == 2'd1) || (osd_force != 2'd2 && ((osd_ms != 0) || (page != P_FLY)));

    // ---- measurement log: after each mixer-usage window (~65 ms) send one fixed-width line, and
    //   HEARTBEAT_MS after the last line when no window has come (no lines from any decoder: the
    //   snow and noise values then read "------", the usage values are the last window's; hub
    //   LOGIKGRANSKNING F10, 2026-10-21)
    //   "S aaaaaa bbbbbb nnnnnn mmmmmm ua_ ub_ um_ Bc ffff MOD T/V F/L o ll rrrrr sssss pa_ pb_ ww t\r\n"
    //   (89 bytes incl. CRLF; 87 before the SDRAM self-test of 2026-10-21, 85 before the HDMI range of
    //   2026-10-18, 62 before the RSSI fields of 2026-10-13)
    //   snow A, snow B, noise A, noise B (luma samples outside 16..235 in the last 1024 lines),
    //   % from A, % from B, % blended, band+channel, MHz, mode (MIX/A/B), filter (T/V),
    //   HDMI range (F full, L limited: the menu's choice, also in the DVI build, which ignores it),
    //   o = "!" once the mixer has dropped a line because its line slots were full, else "-",
    //   ll = decoder A, decoder B since the previous line: "L" a whole poll round read 88h bit 4
    //   (lost lock), "-" whole rounds without it, "?" no whole round (decoder absent or reset),
    //   RSSI A, RSSI B (raw ADC codes of the last round, "-----" without a reading), calibrated % A,
    //   B ("---" uncalibrated), and per receiver "W" weak (the mixer avoids it), "L" low but not
    //   weak (the other one is low too, or not calibrated), "-" neither, "?" no reading;
    //   t = the SDRAM self-test: "-" not run yet, else a digit 0-7 whose bits 0/1/2 say that sample
    //   point 4/5/6 read the test bursts right ("2": only the default point 5, as it should be)
    reg [1:0] ll_round, ll_lost;                           // since the previous log line
    wire      log_take;                                    // the line is copied this clock
    function [7:0] ll_char(input round, input lost);
        ll_char = lost ? "L" : round ? "-" : "?";
    endfunction
    always @(posedge clk) begin
        if (log_take) begin ll_round <= dec_round; ll_lost <= dec_round & dec_lost; end
        else begin ll_round <= ll_round | dec_round; ll_lost <= ll_lost | (dec_round & dec_lost); end
        if (rst) begin ll_round <= 2'b00; ll_lost <= 2'b00; end
    end
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
    function [39:0] z5(input [23:0] b, input none);
        integer i;
        begin
            for (i = 0; i < 5; i = i + 1) z5[i * 8 +: 8] = 8'h30 + b[4*i +: 4];
            if (none) z5 = "-----";
        end
    endfunction
    function [7:0] rs_char(input valid, input low, input warn);
        rs_char = !valid ? "?" : warn ? "W" : low ? "L" : "-";
    endfunction
    reg  [1:0] ovf_s;
    always @(posedge clk) ovf_s <= {ovf_s[0], mix_overflow};
    // the 87 bytes before CR LF that every build sends; DEVCMD = 1 adds 12 (see the top of the file)
    localparam BASE_LEN = 87, CMD_LEN = 12, Q_LEN = 52;
    localparam LOG_LEN = BASE_LEN + ((DEVCMD != 0) ? CMD_LEN : 0) + 2;
    wire [BASE_LEN*8-1:0] log_base = {"S ", z6(bcd_a, stale_a), " ", z6(bcd_b, stale_b), " ",
                             z6(bcd_na, stale_a), " ", z6(bcd_nb, stale_b), " ", z3(bcd_ua), " ", z3(bcd_ub), " ",
                             z3(bcd_um), " ", band_letter, ch_dig, " ", mhz, " ", mode_s, " ",
                             filter_vcr ? "V" : "T", " ", hdmi_ltd ? "L" : "F", " ", ovf_s[1] ? "!" : "-", " ",
                             ll_char(ll_round[0], ll_lost[0]), ll_char(ll_round[1], ll_lost[1]), " ",
                             z5(bcd_ra, !rssi_valid[0]), " ", z5(bcd_rb, !rssi_valid[1]), " ",
                             rssi_cal_ok[0] ? z3(bcd_pa) : "---", " ", rssi_cal_ok[1] ? z3(bcd_pb) : "---", " ",
                             rs_char(rssi_valid[0], rssi_low[0], rssi_warn[0]),
                             rs_char(rssi_valid[1], rssi_low[1], rssi_warn[1]), " ",
                             sdram_test[3] ? 8'h30 + {5'd0, sdram_test[2:0]} : "-"};
    function [7:0] hexd(input [3:0] v); hexd = (v < 4'd10) ? 8'h30 + v : 8'h37 + v; endfunction
    function [15:0] hex2(input [7:0] v); hex2 = {hexd(v[7:4]), hexd(v[3:0])}; endfunction
    wire [CMD_LEN*8-1:0] cmd_s = {" ", low_lat ? "LOW" : "BUF", " ", ch_hold ? "H" : "-",
                                  (osd_force == 2'd1) ? "O" : (osd_force == 2'd2) ? "-" : "A", " ",
                                  hex2(cmd_last), hex2(cmd_count)};
    // status line: per decoder address, {89h, 88h}, 03h, times found reset
    // (dec_init_done is an argument: a function reading a module signal is not re-evaluated in simulation when
    //  only that signal changes)
    function [103:0] dec_q(input init, input err, input alt, input valid, input [15:0] st, input mok, input [7:0] m,
                           input [7:0] ri);
        dec_q = {!init ? "--" : err ? "NA" : (alt ^ TVP_FIRST[0]) ? "5D" : "5C", " ",
                 valid ? {hex2(st[15:8]), hex2(st[7:0])} : "----", " ", mok ? hex2(m) : "--", " ", hex2(ri)};
    endfunction
    localparam [7:0] BD6 = 8'h30 + (BAUD / 1000000) % 10, BD5 = 8'h30 + (BAUD / 100000) % 10,
                     BD4 = 8'h30 + (BAUD / 10000) % 10, BD3 = 8'h30 + (BAUD / 1000) % 10,
                     BD2 = 8'h30 + (BAUD / 100) % 10, BD1 = 8'h30 + (BAUD / 10) % 10, BD0 = 8'h30 + BAUD % 10;
    wire [Q_LEN*8-1:0] q_line = {"Q A ", dec_q(dec_init_done, dec_err[0], dec_alt[0], dec_valid[0], dec_st0,
                                               dec_misc_ok[0], dec_misc0, dec_ri0),
                                 " B ", dec_q(dec_init_done, dec_err[1], dec_alt[1], dec_valid[1], dec_st1,
                                              dec_misc_ok[1], dec_misc1, dec_ri1),
                                 " T ", sdram_test[3] ? 8'h30 + {5'd0, sdram_test[2:0]} : "-",
                                 (HDMI_BUILD != 0) ? " H " : " D ", TVP_FIRST[0] ? "5D" : "5C", " ",
                                 BD6, BD5, BD4, BD3, BD2, BD1, BD0, 16'h0D0A};
    wire [LOG_LEN*8-1:0] log_line;
    generate if (DEVCMD != 0) begin : g_cmd_line
        assign log_line = {log_base, cmd_s, 16'h0D0A};
    end else begin : g_line
        assign log_line = {log_base, 16'h0D0A};
    end endgenerate
    reg  [8:0] log_wait;
    reg  [6:0] log_i, log_n;                                         // byte being sent, bytes in the buffer
    reg        log_active, u_send;
    reg  [LOG_LEN*8-1:0] log_buf;                                    // the line left-aligned (the status line is shorter)
    wire       u_busy;
    assign log_take = (log_wait == 9'd400);
    assign q_take = (DEVCMD != 0) && q_req && !log_active && log_wait == 0;
    uart_tx #(.DIV(CLK_HZ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(log_buf[(LOG_LEN - 1 - log_i) * 8 +: 8]),
                                         .busy(u_busy), .txd(uart_txd));
    reg [$clog2(HEARTBEAT_MS + 2)-1:0] hb_ms;                        // ms since the last line was taken
    always @(posedge clk) begin
        u_send <= 1'b0;
        if (log_take) hb_ms <= 0;
        else if (tick && hb_ms != HEARTBEAT_MS) hb_ms <= hb_ms + 1'b1;
        if (q_take) begin                                            // a status line, between log lines
            log_buf <= {q_line, {(LOG_LEN - Q_LEN) * 8{1'b0}}}; log_n <= Q_LEN; log_i <= 0; log_active <= 1'b1;
        end else if (tgu[2] != tgu[1] && !log_active) log_wait <= 9'd1; // new window: wait for the decimal values
        else if (HEARTBEAT_MS != 0 && hb_ms == HEARTBEAT_MS && log_wait == 0 && !log_active)
            log_wait <= 9'd1;                                            // no window for HEARTBEAT_MS: a line anyway
        else if (log_wait != 0) begin
            log_wait <= log_wait + 1'b1;
            if (log_wait == 9'd400) begin
                log_wait <= 0; log_buf <= log_line; log_n <= LOG_LEN; log_i <= 0; log_active <= 1'b1;
            end
        end
        if (log_active && !u_busy && !u_send) begin
            u_send <= 1'b1;
        end
        if (u_send) begin
            if (log_i == log_n - 1) log_active <= 1'b0; else log_i <= log_i + 1'b1;
        end
        if (rst) begin log_wait <= 0; log_active <= 1'b0; log_i <= 0; log_n <= LOG_LEN; hb_ms <= 0; end
    end
endmodule
`default_nettype wire
