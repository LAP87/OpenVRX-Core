// tvp_ctrl + i2c_master against two behavioural I2C slaves.
// Prints the slaves' registers and the controller's outputs for sim/test_tvp_ctrl.py;
// decoder 0's slave also logs every register write and read ("I2C W rr dd").
//   PRESENT1 = 0   decoder 1 is not on the bus at start
//   SPLIT = 1      both slaves at 5Ch on separate SDA lines
//   SCENARIO 0     nothing happens after start-up
//            1     decoder 1 is reset twice after start-up (registers back to their defaults)
//            2     decoder 1 acknowledges writes but ignores them: 03h never reads back 0Dh
//            3     decoder 1 joins the bus after start-up (use with PRESENT1 = 0) and leaves it again
//            4     decoder 1's SDA line is shorted to ground (use with SPLIT = 1)
//            5/6/7 decoder 1 refuses register 88h / 89h / 03h until one poll round has failed
//                  (MID is printed right after that round), then answers again
`timescale 1ns/1ps
`default_nettype none
module tb_tvp_ctrl;
    parameter PRESENT1 = 1;
    parameter SPLIT = 0;
    parameter SCENARIO = 0;
    reg clk = 0, rst = 1;
    always #500 clk = ~clk;                       // 1 MHz: 1 ms = 1000 cycles

    reg  present1 = (PRESENT1 != 0);
    wire scl_low, s0_low, s1_low_raw, active;
    wire [1:0] m_sda_low;
    wire s1_low = present1 ? s1_low_raw : 1'b0;
    wire scl = scl_low ? 1'b0 : 1'b1;
    wire sda0 = SPLIT ? !(m_sda_low[0] | s0_low) : !(m_sda_low[0] | s0_low | s1_low);
    wire sda1 = (SCENARIO == 4) ? 1'b0 : SPLIT ? !(m_sda_low[1] | s1_low) : sda0;
    wire resetb, init_done;
    wire [1:0] dev_err, status_valid;
    wire [15:0] status0, status1;
    wire [7:0] reinit0, reinit1;
    tvp_ctrl #(.CLK_HZ(1_000_000), .I2C_DIV(3), .POWER_MS(1), .RESET_MS(1), .BOOT_MS(1), .POLL_MS(2),
               .SPLIT_SDA(SPLIT), .DEV1(SPLIT ? 7'h5C : 7'h5D)) dut (
        .clk(clk), .rst(rst), .tvp_resetb(resetb), .scl_low(scl_low), .sda_low(m_sda_low),
        .scl_in(scl), .sda_in({sda1, sda0}), .init_done(init_done), .dev_err(dev_err),
        .status0(status0), .status1(status1), .status_valid(status_valid),
        .reinit0(reinit0), .reinit1(reinit1), .hold(1'b0), .active(active));
    i2c_slave_model #(.ADDR(7'h5C), .LOG(1)) s0 (.scl(scl), .sda(sda0), .sda_low(s0_low));
    // an absent decoder sees an idle bus
    i2c_slave_model #(.ADDR(SPLIT ? 7'h5C : 7'h5D)) s1 (.scl(present1 ? scl : 1'b1), .sda(present1 ? sda1 : 1'b1),
                                                       .sda_low(s1_low_raw));
    initial begin
        // decoder 0 keeps the model's default, healthy NTSC (000E); decoder 1 reads as healthy PAL
        // in an odd field with the PAL switch set (306E)
        #1 s1.regs[8'h88] = 8'h6E; s1.regs[8'h89] = 8'h30;
        if (SCENARIO == 2) s1.wr_protect = 1;
    end

    reg saw_reset_low = 0;
    integer reset_falls = 0;
    always @(posedge clk) if (!resetb) saw_reset_low <= 1;
    always @(negedge resetb) reset_falls = reset_falls + 1;

    task set_present(input v);                    // between two transactions
        begin
            wait (!active);
            @(negedge clk) present1 = v;
        end
    endtask
    task show(input at_end);
        begin
            if (at_end) $write("RESULT"); else $write("MID");
            $display(" reset_low=%0d reset_falls=%0d err=%0d s0_03=%02x s0_04=%02x s0_0d=%02x s0_00=%02x s0_02=%02x s0_28=%02x s0_writes=%0d s1_03=%02x s1_04=%02x s1_0d=%02x s1_02=%02x s1_28=%02x s1_writes=%0d st0=%04x st1=%04x valid=%0d reinit0=%0d reinit1=%0d",
                     saw_reset_low, reset_falls, dev_err, s0.regs[8'h03], s0.regs[8'h04], s0.regs[8'h0D],
                     s0.regs[8'h00], s0.regs[8'h02], s0.regs[8'h28], s0.writes,
                     s1.regs[8'h03], s1.regs[8'h04], s1.regs[8'h0D], s1.regs[8'h02], s1.regs[8'h28], s1.writes,
                     status0, status1, status_valid, reinit0, reinit1);
        end
    endtask

    initial begin
        #3000 rst = 0;
        wait (init_done);
        wait (status_valid[0]);
        // a decoder whose outputs never come on (2, 4) never has valid status
        if (PRESENT1 && SCENARIO != 2 && SCENARIO != 4) wait (status_valid[1]);
        #20_000_000;
        case (SCENARIO)
            5, 6, 7: begin
                s1.nack_reg = (SCENARIO == 5) ? 8'h88 : (SCENARIO == 6) ? 8'h89 : 8'h03;
                wait (dev_err[1]);
                @(posedge clk); show(0);
                s1.nack_reg = -1;
                #30_000_000;
            end
            1: begin
                s1.tvp_reset; #30_000_000;
                show(0);
                s1.tvp_reset; #30_000_000;
            end
            2, 4: #2_000_000_000;                 // more than 255 poll rounds
            3: begin
                set_present(1); #30_000_000;
                show(0);
                set_present(0); #20_000_000;
            end
            default: ;
        endcase
        show(1);
        $finish;
    end
    initial begin #4_000_000_000 $display("RESULT timeout"); $finish; end
endmodule
`default_nettype wire
