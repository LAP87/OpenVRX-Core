// The decoder status path of M4/M6 (tvp_ctrl -> dec_bad -> mixer2 ext_bad) with two I2C register
// models as the decoders and two BT.656 streams in step on one clock: A a real picture
// (+vec_a), B a flat one (+vec_b, a free-running decoder's output). Both decoders report lock;
// at T_LOSS_NS decoder B reports none (88h = 00h) and refuses 88h in its next poll round, so one
// round is void before a whole round reads the loss. Printed for sim/test_dec_lock.py:
//   ROUND <ns> <decoder>   a whole poll round (tvp_ctrl round_ok)
//   LOSS <ns>              B lost lock and refuses 88h; NACKED <ns> its void round has ended
//   D <ns> <use>           a mixer decision (dec_use: 01 A, 10 B, 11 blend, 00 left out)
`timescale 1ns/1ps
`default_nettype none
module tb_dec_lock;
    parameter T_LOSS_NS = 30_000_000;
    parameter T_END_NS = 45_000_000;
    parameter POLL_MS = 2;                        // as M4 and M6 (TVP_POLL_MS)

    reg clk = 0, tclk = 0, sclk = 0, rst = 1;
    always #18.519 clk = ~clk;                    // 27 MHz board clock
    always #18.519 tclk = ~tclk;                  // both decoders' SCLK: the streams stay in step
    always #7.716 sclk = ~sclk;                   // 64.8 MHz mixer clock

    reg [7:0] mem_a [0:1048575];
    reg [7:0] mem_b [0:1048575];
    integer n_bytes, i = 0;
    string vec_a, vec_b;
    reg [7:0] da = 8'h80, db = 8'h80;
    initial begin
        if (!$value$plusargs("vec_a=%s", vec_a) || !$value$plusargs("vec_b=%s", vec_b)) $fatal(1, "missing +vec_a/+vec_b");
        $readmemh(vec_a, mem_a);
        $readmemh(vec_b, mem_b);
        n_bytes = 0;
        while (mem_a[n_bytes] !== 8'bx && n_bytes < 1048575) n_bytes = n_bytes + 1;
        if (mem_b[n_bytes - 1] === 8'bx || mem_b[n_bytes] !== 8'bx) $fatal(1, "vectors of different length");
    end
    always @(posedge tclk) begin da <= mem_a[i]; db <= mem_b[i]; i <= (i + 1 == n_bytes) ? 0 : i + 1; end

    // ---- the decoders' I2C, one SDA each, shared SCL (as in M4/M6)
    wire scl_low, s_a, s_b;
    wire [1:0] sda_low, dev_err, st_valid, round_ok;
    wire scl = scl_low ? 1'b0 : 1'b1;
    wire sda_a = !(sda_low[0] | s_a), sda_b = !(sda_low[1] | s_b);
    wire [15:0] st0, st1;
    wire init_done;
    tvp_ctrl #(.CLK_HZ(27_000_000), .SPLIT_SDA(1), .DEV0(7'h5C), .DEV1(7'h5C), .POWER_MS(1), .RESET_MS(1),
               .BOOT_MS(1), .POLL_MS(POLL_MS)) ctrl (
        .clk(clk), .rst(rst), .tvp_resetb(), .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl),
        .sda_in({sda_b, sda_a}), .init_done(init_done), .dev_err(dev_err), .status0(st0), .status1(st1),
        .status_valid(st_valid), .round_ok(round_ok), .lost_lock(), .reinit0(), .reinit1(), .addr_alt(),
        .addr_found(), .hold(1'b0), .op_mode_req(1'b0), .op_mode_vcr(1'b0), .active());
    i2c_slave_model #(.ADDR(7'h5C)) tvp_a (.scl(scl), .sda(sda_a), .sda_low(s_a));
    i2c_slave_model #(.ADDR(7'h5C)) tvp_b (.scl(scl), .sda(sda_b), .sda_low(s_b));

    // ---- the rule of M4/M6 and the mixer
    wire nolock_a, nolock_b;
    dec_bad lockrule (.status_valid(st_valid), .status0(st0), .status1(st1), .bad({nolock_b, nolock_a}));
    wire m_empty, dec_valid;
    wire [1:0] dec_use;
    mixer2 mix (.a_clk(tclk), .a_d(da), .b_clk(tclk), .b_d(db), .sys_clk(sclk), .rst_async(rst),
                .ext_bad_a(nolock_a), .ext_bad_b(nolock_b), .ext_weak_a(1'b0), .ext_weak_b(1'b0),
                .out_empty(m_empty), .out_data(), .out_pop(!m_empty),
                .a_lines(), .b_lines(), .alive_a(), .alive_b(), .cur(), .overflow(), .dec_valid(dec_valid),
                .dec_use(dec_use), .dec_pop(), .dec_field(), .dec_line());

    always @(posedge sclk) if (dec_valid) $display("D %0d %b", $time, dec_use);
    always @(posedge clk) begin
        if (round_ok[0]) $display("ROUND %0d 0", $time);
        if (round_ok[1]) $display("ROUND %0d 1", $time);
    end
    initial begin
        #1000 rst = 0;
        #(T_LOSS_NS - 1000);
        tvp_b.regs[8'h88] = 8'h00;                // B has lost lock ...
        tvp_b.nack_reg = 8'h88;                   // ... and its next poll round is void
        $display("LOSS %0d", $time);
        wait (dev_err[1]);
        tvp_b.nack_reg = -1;
        $display("NACKED %0d", $time);
        #(T_END_NS - $time);
        $display("RESULT done");
        $finish;
    end
endmodule
`default_nettype wire
