// M3: bring-up probe for the two-decoder wiring of M4/M6 (same pins).
// No video out. Once a second it prints one line per decoder over the
// onboard USB-UART (PIN69, 115200 8N1):
//
//   A sclk 27000064 tog FF hi FF len 1716-1716 ln 14565 fld 060 xe 0000 i2c OK st 402E
//
//   sclk  SCLK frequency in Hz (resolution 256 Hz); "no SCLK" ends the line when the decoder clock is absent
//   tog   data bits YOUT7..0 that toggled (FF = all wired); hi = bits ever 1 (stuck-low bit: tog 0, hi 0)
//   len   shortest-longest line in bytes, active lines only (NTSC 1716, PAL 1728; ---- = no line)
//   ln    active lines this second (NTSC about 14 500, PAL about 14 400)
//   fld   field changes this second (60 or 50)
//   xe    timing codes with uncorrectable bit errors
//   i2c   OK / NA (no acknowledge) / -- (start-up not finished); st = status registers 89h,88h (---- = none yet)
//
// Both RX5808 are tuned to F4 5800 MHz at start (same SPI pins as M6), so
// receiver video reaches the decoders without the menu.
// LEDs (active low): 0 heartbeat, 1 SCLK A, 2 SCLK B, 3 both decoders answer on I2C; led[4]/led[5] carry the
// RX5808 SPI DATA/SEL (pins 19/20 = J6-17/J6-16; pins 52/53 are configuration and HDMI DDC pins).
// Pull test (find open joints without a meter): PULL=UP or PULL=DOWN gateware/build.sh m3_probe
// adds weak pulls on the data pins; a bit that follows the pull is not driven by the decoder.
`default_nettype none
module m3_probe #(
    parameter CLK_HZ = 27_000_000,
    parameter WINDOW = 27_000_000,        // board clocks per report
    parameter BAUD = 115_200,
    parameter POWER_MS = 20
) (
    input  wire        clk,
    input  wire        tvpa_sclk,
    input  wire [7:0]  tvpa_d,
    input  wire        tvpb_sclk,
    input  wire [7:0]  tvpb_d,
    inout  wire        i2c_scl,
    inout  wire        i2c_sda_a,
    inout  wire        i2c_sda_b,
    output wire        tvp_resetb,
    output wire        rx_spi_clk,        // RX5808 DATA and SEL leave on led[4] (J6-17), led[5] (J6-16), as in M6
    output wire [5:0]  led,
    output wire        uart_txd
);
    `include "vtx_channels.vh"

    // ---- resets
    reg [3:0] por = 4'hF;
    always @(posedge clk) por <= {por[2:0], 1'b0};
    wire rst = por[3];
    reg [2:0] rst_a, rst_b;
    always @(posedge tvpa_sclk or posedge rst) if (rst) rst_a <= 3'b111; else rst_a <= {rst_a[1:0], 1'b0};
    always @(posedge tvpb_sclk or posedge rst) if (rst) rst_b <= 3'b111; else rst_b <= {rst_b[1:0], 1'b0};

    // ---- decoders: I2C bring-up and status (as in M4)
    wire scl_low, init_done;
    wire [1:0] sda_low, dev_err, st_valid;
    wire [15:0] st0, st1;
    tvp_ctrl #(.CLK_HZ(CLK_HZ), .SPLIT_SDA(1), .DEV0(7'h5C), .DEV1(7'h5C), .POWER_MS(POWER_MS)) ctrl (
        .clk(clk), .rst(rst), .tvp_resetb(tvp_resetb),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(i2c_scl), .sda_in({i2c_sda_b, i2c_sda_a}),
        .init_done(init_done), .dev_err(dev_err), .status0(st0), .status1(st1), .status_valid(st_valid),
        .hold(1'b0), .active());
    assign i2c_scl   = scl_low    ? 1'b0 : 1'bz;
    assign i2c_sda_a = sda_low[0] ? 1'b0 : 1'bz;
    assign i2c_sda_b = sda_low[1] ? 1'b0 : 1'bz;

    // ---- RX5808: F4 5800 MHz once after reset
    wire [41:0] f4 = vtx_channel(6'd27);
    reg  spi_go, spi_done;
    wire spi_busy;
    wire [1:0] sel_n;
    wire       spi_data;
    rx5808_spi #(.HALF(CLK_HZ / 1_000_000 > 0 ? CLK_HZ / 1_000_000 : 1)) spi (
        .clk(clk), .rst(rst), .start(spi_go), .sel_mask(2'b11), .addr(4'h1), .data(f4[19:0]),
        .busy(spi_busy), .spi_clk(rx_spi_clk), .spi_data(spi_data), .spi_sel_n(sel_n));
    always @(posedge clk) begin
        spi_go <= 1'b0;
        if (!rst && !spi_done && !spi_busy && !spi_go) begin spi_go <= 1'b1; spi_done <= 1'b1; end
        if (rst) spi_done <= 1'b0;
    end

    // ---- probes
    reg  snap_t;
    wire ack_a, ack_b, div_a, div_b;
    wire [7:0]  tog_a, hi_a, tog_b, hi_b;
    wire [15:0] lmin_a, lmax_a, lmin_b, lmax_b, bad_a, bad_b;
    wire [19:0] lines_a, lines_b;
    wire [9:0]  fld_a, fld_b;
    bt656_probe pa (.clk(tvpa_sclk), .rst(rst_a[2]), .d(tvpa_d), .snap_toggle(snap_t), .ack_toggle(ack_a),
                    .tog(tog_a), .hi(hi_a), .len_min(lmin_a), .len_max(lmax_a), .lines(lines_a), .fields(fld_a),
                    .xy_bad(bad_a), .div_out(div_a));
    bt656_probe pb (.clk(tvpb_sclk), .rst(rst_b[2]), .d(tvpb_d), .snap_toggle(snap_t), .ack_toggle(ack_b),
                    .tog(tog_b), .hi(hi_b), .len_min(lmin_b), .len_max(lmax_b), .lines(lines_b), .fields(fld_b),
                    .xy_bad(bad_b), .div_out(div_b));

    // ---- SCLK frequency: count SCLK/256 edges per window
    reg [2:0]  da, db, aa, ab;
    reg [16:0] fa, fb, fa_win, fb_win;
    reg [$clog2(WINDOW+1)-1:0] wcnt;
    wire       win_end = (wcnt == WINDOW - 1);
    always @(posedge clk) begin
        da <= {da[1:0], div_a};  db <= {db[1:0], div_b};
        aa <= {aa[1:0], ack_a};  ab <= {ab[1:0], ack_b};
        wcnt <= win_end ? 0 : wcnt + 1'b1;
        if (win_end) begin
            fa_win <= fa; fb_win <= fb; fa <= 0; fb <= 0; snap_t <= ~snap_t;
        end else begin
            if (da[2:1] == 2'b01 && fa != 17'h1FFFF) fa <= fa + 1'b1;
            if (db[2:1] == 2'b01 && fb != 17'h1FFFF) fb <= fb + 1'b1;
        end
        if (rst) begin wcnt <= 0; fa <= 0; fb <= 0; fa_win <= 0; fb_win <= 0; snap_t <= 1'b0; end
    end

    // ---- report: after each window, wait for the acks, convert six numbers per channel, print two lines
    localparam LEN = 84;
    function [7:0] hexc(input [3:0] v); hexc = (v < 10) ? 8'h30 + v : 8'h37 + v; endfunction
    function [15:0] hex2(input [7:0] v); hex2 = {hexc(v[7:4]), hexc(v[3:0])}; endfunction
    function [31:0] hex4(input [15:0] v); hex4 = {hex2(v[15:8]), hex2(v[7:0])}; endfunction
    function [7:0] dg(input [3:0] v); dg = 8'h30 + v; endfunction
    function [24:0] clampv(input [24:0] v, input [24:0] mx); clampv = (v > mx) ? mx : v; endfunction

    reg  [3:0]  phase;                    // 0 idle, 1 wait acks, 2 convert, 3 build, 4 send
    reg         ch;                       // 0 = A, 1 = B
    reg  [2:0]  ci;                       // conversion index 0..5
    reg  [9:0]  wait_n;
    reg  [2:0]  ack_last;                 // [0] A, [1] B: last seen ack level
    reg  [1:0]  fresh;
    reg  [24:0] conv_in;
    reg         conv_go;
    wire        conv_busy, conv_done;
    wire [31:0] conv_bcd;
    reg  [31:0] bcd [0:5];                // sclk, len min, len max, lines, fields, xy errors
    bin2bcd #(.W(25), .D(8)) conv (.clk(clk), .start(conv_go), .bin(conv_in), .busy(conv_busy),
                                   .done(conv_done), .bcd(conv_bcd));
    // the selected channel's latched values (stable: the probe changes them only at the next snap)
    wire [16:0] f_sel   = ch ? fb_win : fa_win;
    wire [7:0]  tog_sel = ch ? tog_b : tog_a,   hi_sel = ch ? hi_b : hi_a;
    wire [15:0] lmin    = ch ? lmin_b : lmin_a, lmax = ch ? lmax_b : lmax_a, bad = ch ? bad_b : bad_a;
    wire [19:0] lns     = ch ? lines_b : lines_a;
    wire [9:0]  fld     = ch ? fld_b : fld_a;
    wire [15:0] stv     = ch ? st1 : st0;
    wire        stok    = ch ? st_valid[1] : st_valid[0];
    wire        err     = ch ? dev_err[1] : dev_err[0];
    wire        fr      = ch ? fresh[1] : fresh[0];
    always @* case (ci)
        3'd0: conv_in = {f_sel, 8'd0};
        3'd1: conv_in = clampv({9'd0, lmin}, 25'd9999);
        3'd2: conv_in = clampv({9'd0, lmax}, 25'd9999);
        3'd3: conv_in = clampv({5'd0, lns}, 25'd99999);
        3'd4: conv_in = clampv({15'd0, fld}, 25'd999);
        default: conv_in = clampv({9'd0, bad}, 25'd9999);
    endcase

    function [31:0] d4(input [31:0] b); d4 = {dg(b[15:12]), dg(b[11:8]), dg(b[7:4]), dg(b[3:0])}; endfunction
    wire [31:0] b0 = bcd[0], b1 = bcd[1], b2 = bcd[2], b3 = bcd[3], b4 = bcd[4], b5 = bcd[5];
    wire [63:0] sclk_s = {dg(b0[31:28]), dg(b0[27:24]), dg(b0[23:20]), dg(b0[19:16]), d4(b0)};
    wire [71:0] len_s  = (lns == 0) ? "---------" : {d4(b1), "-", d4(b2)};
    wire [15:0] i2c_s  = !init_done ? "--" : err ? "NA" : "OK";
    wire [31:0] st_s   = stok ? hex4(stv) : "----";
    wire [LEN*8-1:0] line_ok = {ch ? "B" : "A", " sclk ", sclk_s, " tog ", hex2(tog_sel), " hi ", hex2(hi_sel),
                                " len ", len_s, " ln ", dg(b3[19:16]), d4(b3), " fld ", dg(b4[11:8]), dg(b4[7:4]),
                                dg(b4[3:0]), " xe ", d4(b5), " i2c ", i2c_s, " st ", st_s, 16'h0D0A};
    // no SCLK: the probe values are stale, print only the frequency and I2C
    wire [LEN*8-1:0] line_dead = {ch ? "B" : "A", " sclk ", sclk_s, " no SCLK", {44{" "}}, " i2c ", i2c_s,
                                  " st ", st_s, 16'h0D0A};

    reg  [LEN*8-1:0] out;
    reg  [6:0]  oi;
    reg         u_send;
    wire        u_busy;
    uart_tx #(.DIV(CLK_HZ / BAUD)) uart (.clk(clk), .rst(rst), .send(u_send), .data(out[(LEN - 1 - oi) * 8 +: 8]),
                                         .busy(u_busy), .txd(uart_txd));
    always @(posedge clk) begin
        conv_go <= 1'b0;
        u_send  <= 1'b0;
        case (phase)
            4'd0: if (win_end) begin phase <= 4'd1; wait_n <= 0; end
            4'd1: begin                                      // acks come within a few dozen clocks
                wait_n <= wait_n + 1'b1;
                if (wait_n == 10'd1000) begin
                    fresh <= {ab[2] != ack_last[1], aa[2] != ack_last[0]};
                    ack_last[1:0] <= {ab[2], aa[2]};
                    ch <= 1'b0; ci <= 0; phase <= 4'd2;
                end
            end
            4'd2: if (!conv_busy && !conv_go && !conv_done) conv_go <= 1'b1;
                  else if (conv_done) begin
                      bcd[ci] <= conv_bcd;
                      if (ci == 3'd5) phase <= 4'd3; else ci <= ci + 1'b1;
                  end
            4'd3: begin out <= fr ? line_ok : line_dead; oi <= 0; phase <= 4'd4; end
            4'd4: begin
                if (!u_busy && !u_send) u_send <= 1'b1;
                if (u_send) begin
                    if (oi == LEN - 1) begin
                        if (ch) phase <= 4'd0; else begin ch <= 1'b1; ci <= 0; phase <= 4'd2; end
                    end else oi <= oi + 1'b1;
                end
            end
            default: phase <= 4'd0;
        endcase
        if (rst) begin phase <= 0; ack_last <= 0; fresh <= 0; oi <= 0; end
    end

    // ---- LEDs
    reg [24:0] beat;
    always @(posedge clk) beat <= beat + 1'b1;
    assign led = {sel_n[0], spi_data, ~{init_done && dev_err == 2'b00, fresh[1], fresh[0], beat[24]}};
endmodule
`default_nettype wire
