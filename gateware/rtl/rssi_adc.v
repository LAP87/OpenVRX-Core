// RSSI of both receivers from a TI ADS1115 on decoder A's I2C bus (Puck rev A board,
// design/rev_a in OpenVRX-Puck): AIN0 = receiver A, AIN1 = receiver B, address 48h.
// Model: model/rssi_ref.py. Testbench: sim/tb_rssi_adc.v against sim/ads1115_model.v.
//
// Every PERIOD_US (one NTSC field by default) both channels are read once, in single-shot
// mode (TI SBAS444E table 8-3): write the config with OS = 1 and the channel's MUX
// (AINx against GND), wait CONV_US, read the conversion register (two bytes, MSB first).
// Config C3C3h / D3C3h: FSR +-4.096 V (125 uV per code; the inputs run on 3.3 V), single
// shot, 475 SPS (2.1 ms; CONV_US covers +10 % oscillator and the 25 us wake-up), comparator
// off. A negative code (input below ground) counts as 0.
//
// A reading whose write or read is not acknowledged is not valid (no ADC fitted, as on
// boards without the rev A RSSI circuit): it changes nothing but `valid`, and a channel
// without a valid reading never warns.
//
// Calibration (no two RX5808 have the same RSSI range): while `cal` is high every valid
// reading widens that channel's [min, max]; `cal` rising starts both ranges afresh. When
// `cal` falls, a channel counts as calibrated if max - min >= MIN_SPAN. `load` sets the
// ranges directly (saved settings, see the SPI-flash store).
// Calibrated value pct = floor((raw - min) * 100 / (max - min)), 0..100 (0 at or below min,
// 100 at or above max).
//
// Warning (the mixer's health, mixer2 ext_weak): a channel is `low` after N_LOW readings in a
// row with pct < LOW_PCT. It `warn`s only while it is low and the other channel is calibrated,
// has a valid reading, is not low and reads at least MARGIN_PCT points higher: near the floor
// one or two points of noisy RSSI say nothing about which picture is cleaner, and while a
// warning lasts the mixer takes the other receiver in every pair. The warning says "the other
// receiver hears the transmitter clearly better"; two weak receivers do not mark each other.
// Uncalibrated channels are never low.
//
// Shared bus (one master at a time, all on this clock): before each transaction `hold_other`
// rises, but only while the other holding master (`other_hold`, the OLED) does not hold; the
// transaction starts once `other_active` has been low for two clocks. Hold drops after each
// transaction, so the OLED and tvp_ctrl get the bus during the conversion wait.
`default_nettype none
module rssi_adc #(
    parameter CLK_HZ = 27_000_000,
    parameter I2C_DIV = 68,                  // 99 kHz, as tvp_ctrl
    parameter [6:0] DEV = 7'h48,
    parameter PERIOD_US = 16_683,            // one NTSC field
    parameter CONV_US = 2_600,
    parameter LOW_PCT = 20,
    parameter MARGIN_PCT = 5,
    parameter N_LOW = 3,
    parameter MIN_SPAN = 400                 // codes: 50 mV
) (
    input  wire        clk,
    input  wire        rst,
    output wire        scl_low,
    output wire        sda_low,
    input  wire        scl_in,
    input  wire        sda_in,
    output reg         hold_other,
    input  wire        other_hold,
    input  wire        other_active,
    output wire        active,               // a transaction is starting or running
    input  wire        cal,
    input  wire        load,                 // one clock: take the ranges below
    input  wire [15:0] load_min_a, load_max_a, load_min_b, load_max_b,
    output reg  [15:0] raw_a, raw_b,         // last valid readings
    output reg  [1:0]  valid,                // the last reading of the channel was acknowledged
    output reg  [15:0] min_a, max_a, min_b, max_b,
    output reg  [1:0]  cal_ok,
    output reg  [6:0]  pct_a, pct_b,
    output reg  [1:0]  low,
    output reg  [1:0]  warn,
    output reg         done                  // one clock after each pair of readings, outputs updated
);
    localparam US = CLK_HZ / 1_000_000;
    localparam [31:0] T_PERIOD = PERIOD_US * US, T_CONV = CONV_US * US;
    localparam [15:0] CFG_A = 16'hC3C3, CFG_B = 16'hD3C3;

    reg        start, rw;
    reg  [7:0] addr, wdata;
    wire       busy, i_done, nack, wreq;
    wire [15:0] rdata;
    i2c_master #(.DIV(I2C_DIV), .READ_BYTES(2)) i2c (
        .clk(clk), .rst(rst), .start(start), .rw(rw), .dev(DEV), .addr(addr), .wdata(wdata),
        .wextra(8'd1), .wreq(wreq), .busy(busy), .done(i_done), .nack(nack), .stuck(), .rdata(rdata),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl_in), .sda_in(sda_in));
    assign active = start | busy;

    // step 0 write config A, 1 read A, 2 write config B, 3 read B
    localparam S_WAIT = 3'd0, S_REQ = 3'd1, S_GO = 3'd2, S_TX = 3'd3, S_CONV = 3'd4, S_CALC = 3'd5, S_DIV = 3'd6;
    reg [2:0]  st;
    reg [1:0]  step;
    reg [31:0] t, tp;                        // tp: period timer, runs all the time
    reg [1:0]  free_cnt;
    reg [15:0] lsb;                          // second byte of the config write
    reg [15:0] new_a, new_b;
    reg [1:0]  ok;                           // this round's channel readings acknowledged
    reg        cal_d;

    // calibrated value: (raw - min) * 100 / (max - min), one quotient bit per clock (7 bits)
    reg        dch;                          // channel being divided
    reg [22:0] num;
    reg [15:0] den;
    reg [2:0]  dbit;
    reg [6:0]  q;
    reg [6:0]  p_a, p_b;
    reg [2:0]  n_a, n_b;                     // low readings in a row (saturates at N_LOW)
    wire [15:0] r_c   = dch ? raw_b : raw_a;
    wire [15:0] mn_c  = dch ? min_b : min_a;
    wire [15:0] mx_c  = dch ? max_b : max_a;

    function [15:0] clamp(input [15:0] c);   // negative codes count as 0
        clamp = c[15] ? 16'd0 : c;
    endfunction

    always @(posedge clk) begin
        start <= 1'b0;
        done <= 1'b0;
        tp <= (tp == T_PERIOD - 1) ? 0 : tp + 1;
        if (wreq) wdata <= lsb[7:0];
        cal_d <= cal;
        if (cal && !cal_d) begin             // a new calibration: both ranges afresh
            min_a <= 16'hFFFF; max_a <= 16'h0000; min_b <= 16'hFFFF; max_b <= 16'h0000; cal_ok <= 2'b00;
        end
        if (!cal && cal_d) cal_ok <= {max_b >= min_b && max_b - min_b >= MIN_SPAN,
                                      max_a >= min_a && max_a - min_a >= MIN_SPAN};
        if (load) begin
            min_a <= load_min_a; max_a <= load_max_a; min_b <= load_min_b; max_b <= load_max_b;
            cal_ok <= {load_max_b >= load_min_b && load_max_b - load_min_b >= MIN_SPAN,
                       load_max_a >= load_min_a && load_max_a - load_min_a >= MIN_SPAN};
        end
        case (st)
        S_WAIT: if (tp == 0) begin step <= 0; ok <= 2'b00; st <= S_REQ; end
        S_REQ: if (!other_hold) begin hold_other <= 1'b1; free_cnt <= 0; st <= S_GO; end
        S_GO: begin
            if (other_active) free_cnt <= 0;
            else if (free_cnt != 2'd3) free_cnt <= free_cnt + 1'b1;
            if (free_cnt == 2'd2 && !other_active && !busy) begin
                start <= 1'b1;
                rw <= step[0];
                addr <= step[0] ? 8'h00 : 8'h01;
                wdata <= step[1] ? CFG_B[15:8] : CFG_A[15:8];
                lsb <= step[1] ? CFG_B : CFG_A;
                st <= S_TX;
            end
        end
        S_TX: if (i_done) begin
            hold_other <= 1'b0;
            t <= 0;
            if (nack) begin                  // this channel has no reading this round
                if (step[1]) st <= S_CALC; else begin step <= 2'd2; st <= S_REQ; end
            end else if (!step[0]) st <= S_CONV;
            else begin
                if (step[1]) begin new_b <= clamp(rdata); ok[1] <= 1'b1; st <= S_CALC; end
                else begin new_a <= clamp(rdata); ok[0] <= 1'b1; step <= 2'd2; st <= S_REQ; end
            end
        end
        S_CONV: begin
            t <= t + 1;
            if (t == T_CONV) begin step <= step + 1'b1; st <= S_REQ; end
        end
        S_CALC: begin                        // take the round, widen the calibration ranges
            valid <= ok;
            if (ok[0]) raw_a <= new_a;
            if (ok[1]) raw_b <= new_b;
            if (cal && cal_d) begin
                if (ok[0]) begin if (new_a < min_a) min_a <= new_a; if (new_a > max_a) max_a <= new_a; end
                if (ok[1]) begin if (new_b < min_b) min_b <= new_b; if (new_b > max_b) max_b <= new_b; end
            end
            dch <= 1'b0; dbit <= 3'd7; st <= S_DIV;
        end
        S_DIV: begin
            if (dbit == 3'd7) begin          // set up the division for channel dch
                num <= (r_c <= mn_c) ? 23'd0 : ({7'd0, r_c - mn_c} * 23'd100);
                den <= mx_c - mn_c;
                q <= 0;
                dbit <= 3'd6;
            end else begin
                if (num >= ({7'd0, den} << dbit)) begin num <= num - ({7'd0, den} << dbit); q[dbit] <= 1'b1; end
                if (dbit != 3'd0) dbit <= dbit - 1'b1;
                else begin
                    if (dch) p_b <= (r_c >= mx_c) ? 7'd100 : q | {6'd0, num >= {7'd0, den}};
                    else     p_a <= (r_c >= mx_c) ? 7'd100 : q | {6'd0, num >= {7'd0, den}};
                    if (!dch) begin dch <= 1'b1; dbit <= 3'd7; end
                    else st <= 3'd7;
                end
            end
        end
        3'd7: begin                          // publish: calibrated value, low, warn
            pct_a <= cal_ok[0] ? p_a : 7'd0;
            pct_b <= cal_ok[1] ? p_b : 7'd0;
            begin : lowcount
                reg la, lb;
                reg [2:0] na, nb;
                la = cal_ok[0] && valid[0] && p_a < LOW_PCT;
                lb = cal_ok[1] && valid[1] && p_b < LOW_PCT;
                na = !la ? 3'd0 : (n_a == N_LOW) ? n_a : n_a + 1'b1;
                nb = !lb ? 3'd0 : (n_b == N_LOW) ? n_b : n_b + 1'b1;
                n_a <= na; n_b <= nb;
                low <= {nb == N_LOW, na == N_LOW};
                warn <= {nb == N_LOW && na != N_LOW && cal_ok[0] && valid[0] && p_a - p_b >= MARGIN_PCT,
                         na == N_LOW && nb != N_LOW && cal_ok[1] && valid[1] && p_b - p_a >= MARGIN_PCT};
            end
            done <= 1'b1;
            st <= S_WAIT;
        end
        endcase
        if (rst) begin
            st <= S_WAIT; tp <= 1; t <= 0; step <= 0; hold_other <= 1'b0; start <= 1'b0; done <= 1'b0;
            raw_a <= 0; raw_b <= 0; valid <= 2'b00; ok <= 2'b00; cal_d <= 1'b0; cal_ok <= 2'b00;
            min_a <= 16'hFFFF; max_a <= 16'h0000; min_b <= 16'hFFFF; max_b <= 16'h0000;
            pct_a <= 0; pct_b <= 0; p_a <= 0; p_b <= 0; n_a <= 0; n_b <= 0; low <= 2'b00; warn <= 2'b00;
        end
    end
endmodule
`default_nettype wire
