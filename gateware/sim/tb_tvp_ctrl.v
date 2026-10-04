// tvp_ctrl + i2c_master against two behavioural I2C slaves (or one, PRESENT1 = 0).
// Prints the slaves' registers and the controller's status for sim/test_tvp_ctrl.py.
`timescale 1ns/1ps
`default_nettype none
module tb_tvp_ctrl;
    parameter PRESENT1 = 1;
    parameter SPLIT = 0;                          // 1: both slaves at 5Ch on separate SDA lines
    reg clk = 0, rst = 1;
    always #500 clk = ~clk;                       // 1 MHz: 1 ms = 1000 cycles

    wire scl_low, s0_low, s1_low_raw;
    wire [1:0] m_sda_low;
    wire s1_low = PRESENT1 ? s1_low_raw : 1'b0;
    wire scl = scl_low ? 1'b0 : 1'b1;
    wire sda0 = SPLIT ? !(m_sda_low[0] | s0_low) : !(m_sda_low[0] | s0_low | s1_low);
    wire sda1 = SPLIT ? !(m_sda_low[1] | s1_low) : sda0;
    wire resetb, init_done;
    wire [1:0] dev_err, status_valid;
    wire [15:0] status0, status1;
    tvp_ctrl #(.CLK_HZ(1_000_000), .I2C_DIV(3), .POWER_MS(1), .RESET_MS(1), .BOOT_MS(1), .POLL_MS(2),
               .SPLIT_SDA(SPLIT), .DEV1(SPLIT ? 7'h5C : 7'h5D)) dut (
        .clk(clk), .rst(rst), .tvp_resetb(resetb), .scl_low(scl_low), .sda_low(m_sda_low),
        .scl_in(scl), .sda_in({sda1, sda0}), .init_done(init_done), .dev_err(dev_err),
        .status0(status0), .status1(status1), .status_valid(status_valid), .hold(1'b0), .active());
    i2c_slave_model #(.ADDR(7'h5C)) s0 (.scl(scl), .sda(sda0), .sda_low(s0_low));
    i2c_slave_model #(.ADDR(SPLIT ? 7'h5C : 7'h5D)) s1 (.scl(scl), .sda(sda1), .sda_low(s1_low_raw));
    initial begin
        s1.regs[8'h88] = 8'h06; s1.regs[8'h89] = 8'h00;   // decoder 1: H+V lock, 50 Hz
    end

    reg saw_reset_low = 0;
    always @(posedge clk) if (!resetb) saw_reset_low <= 1;

    initial begin
        #3000 rst = 0;
        wait (init_done);
        wait (status_valid[0]);
        if (PRESENT1) wait (status_valid[1]);
        #20000;
        $display("RESULT reset_low=%0d err=%0d s0_03=%02x s0_0d=%02x s0_00=%02x s0_writes=%0d s1_03=%02x s1_0d=%02x s1_writes=%0d st0=%04x st1=%04x valid=%0d",
                 saw_reset_low, dev_err, s0.regs[8'h03], s0.regs[8'h0D], s0.regs[8'h00], s0.writes,
                 s1.regs[8'h03], s1.regs[8'h0D], s1.writes, status0, status1, status_valid);
        $finish;
    end
    initial begin #200_000_000 $display("RESULT timeout"); $finish; end
endmodule
`default_nettype wire
