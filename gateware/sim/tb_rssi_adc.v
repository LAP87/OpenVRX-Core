// rssi_adc against sim/ads1115_model.v, on one I2C bus with the two other masters of M6
// (tvp_ctrl, no decoders fitted, and ssd1306_text, no display fitted) wired as in
// top/m6_puck_proto.v. sched.txt has one line per round: uV on AIN0, uV on AIN1, ADC absent,
// cal, load (then four load values). Each line is applied before the round it describes;
// after each round the testbench prints
//   R raw_a raw_b valid_a valid_b min_a max_a min_b max_b cal_ok_a cal_ok_b pct_a pct_b
//     low_a low_b warn_a warn_b
// At the end: COLL <clocks with more than one master active>, then the masters' activity:
// OLED frames, tvp_ctrl init_done, ADC conversions. Driven by sim/test_rssi_adc.py.
`timescale 1ns/1ps
`default_nettype none
module tb_rssi_adc;
    parameter CLK_HZ = 27_000_000;
    parameter PERIOD_US = 8_000;
    parameter CONV_US = 2_600;

    reg clk = 0, rst = 1;
    always #(500.0e3 / (CLK_HZ / 1000)) clk = ~clk;

    // ---- the bus: SCL shared, SDA_A (OLED, decoder A, ADC)
    wire scl_r, sda_r, scl_o, sda_o, scl_t, adc_sda;
    wire [1:0] sda_t;
    wire scl = (scl_r | scl_o | scl_t) ? 1'b0 : 1'b1;
    wire sda = (sda_r | sda_o | sda_t[0] | adc_sda) ? 1'b0 : 1'b1;
    ads1115_model #(.ADDR(7'h48)) adc (.scl(scl), .sda(sda), .sda_low(adc_sda));

    // ---- the three masters, arbitration as in m6_puck_proto.v
    wire oled_hold, rssi_hold, tvp_active, oled_active, rssi_active, init_done;
    reg  cal = 0, load = 0;
    reg  [15:0] lmin_a = 0, lmax_a = 0, lmin_b = 0, lmax_b = 0;
    wire [15:0] raw_a, raw_b, min_a, max_a, min_b, max_b;
    wire [1:0]  valid, cal_ok, low, warn;
    wire [6:0]  pct_a, pct_b;
    wire        done;
    tvp_ctrl #(.CLK_HZ(CLK_HZ), .SPLIT_SDA(1), .DEV0(7'h5C), .DEV1(7'h5C), .POWER_MS(1), .RESET_MS(1),
               .BOOT_MS(1), .POLL_MS(2)) ctrl (
        .clk(clk), .rst(rst), .tvp_resetb(), .scl_low(scl_t), .sda_low(sda_t), .scl_in(scl), .sda_in({1'b1, sda}),
        .init_done(init_done), .dev_err(), .status0(), .status1(), .status_valid(), .reinit0(), .reinit1(),
        .round_ok(), .lost_lock(), .hold(oled_hold | rssi_hold), .op_mode_req(1'b0), .op_mode_vcr(1'b0),
        .active(tvp_active));
    wire [1:0] trow;
    wire [4:0] tcol;
    integer frames = 0;
    wire frame_done;
    always @(posedge clk) if (frame_done) frames = frames + 1;
    ssd1306_text #(.CLK_HZ(CLK_HZ), .POWER_MS(1)) oled (
        .clk(clk), .rst(rst), .scl_low(scl_o), .sda_low(sda_o), .scl_in(scl), .sda_in(sda),
        .hold_other(oled_hold), .other_active(tvp_active | rssi_hold | rssi_active),
        .text_row(trow), .text_col(tcol), .text_big(2'b00), .text_char(7'h41), .frame_done(frame_done), .nack_error(),
        .active(oled_active));
    rssi_adc #(.CLK_HZ(CLK_HZ), .PERIOD_US(PERIOD_US), .CONV_US(CONV_US)) dut (
        .clk(clk), .rst(rst), .scl_low(scl_r), .sda_low(sda_r), .scl_in(scl), .sda_in(sda),
        .hold_other(rssi_hold), .other_hold(oled_hold), .other_active(tvp_active | oled_active),
        .active(rssi_active), .cal(cal), .load(load),
        .load_min_a(lmin_a), .load_max_a(lmax_a), .load_min_b(lmin_b), .load_max_b(lmax_b),
        .raw_a(raw_a), .raw_b(raw_b), .valid(valid), .min_a(min_a), .max_a(max_a), .min_b(min_b), .max_b(max_b),
        .cal_ok(cal_ok), .pct_a(pct_a), .pct_b(pct_b), .low(low), .warn(warn), .done(done));

    // ---- collisions: more than one master starting or running a transaction
    integer coll = 0;
    always @(posedge clk) if (!rst && (tvp_active + oled_active + rssi_active) > 1) coll = coll + 1;

    integer fs, fo, n, uva, uvb, absent, c, ld, a0, a1, b0, b1;
    initial begin
        fs = $fopen("sched.txt", "r");
        fo = $fopen("out.txt", "w");
        repeat (20) @(posedge clk);
        rst = 0;
        while (!$feof(fs)) begin
            n = $fscanf(fs, "%d %d %d %d %d %d %d %d %d\n", uva, uvb, absent, c, ld, a0, a1, b0, b1);
            adc.ain_uv[0] = uva; adc.ain_uv[1] = uvb; adc.absent = absent;
            @(posedge clk);
            cal <= c;
            if (ld) begin
                lmin_a <= a0; lmax_a <= a1; lmin_b <= b0; lmax_b <= b1; load <= 1'b1;
                @(posedge clk); load <= 1'b0;
            end
            @(posedge done);
            @(posedge clk);
            $fwrite(fo, "R %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
                    raw_a, raw_b, valid[0], valid[1], min_a, max_a, min_b, max_b, cal_ok[0], cal_ok[1],
                    pct_a, pct_b, low[0], low[1], warn[0], warn[1]);
        end
        $fwrite(fo, "COLL %0d\n", coll);
        $fwrite(fo, "ACT %0d %0d %0d\n", frames, init_done, adc.conversions);
        $fclose(fo);
        $finish;
    end
endmodule
`default_nettype wire
