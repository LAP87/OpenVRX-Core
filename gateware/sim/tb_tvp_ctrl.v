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
//            8     decoder 0 sets 88h bit 4 (lost lock) once; reading 88h clears it
//            9     request VCR while decoder 0 reads 88h; 10 toggles back during its mode write
//            11    NACK the first decoder-0 mode register phase, then allow a later retry
//            12    select VCR before startup init; 13 also reset decoder 1 twice
//            14    run 20 ms after init without waiting for a valid status (no decoder may answer)
//   S0_ADDR, S1_ADDR   the slaves' I2C addresses (defaults 5Ch, and 5Ch with SPLIT or 5Dh without);
//                      any other value than 5Ch/5Dh is a decoder that never answers
//   DEV0, SEARCH       tvp_ctrl's first address for decoder 0 and its address search
//   PIN_TRACE=1   print resolved BUS pin changes and request timestamps for the independent oracle
`timescale 1ns/1ps
`default_nettype none
module tb_tvp_ctrl;
parameter PRESENT1 = 1;
parameter SPLIT = 0;
parameter SCENARIO = 0;
parameter PIN_TRACE = 0;
parameter [6:0] S0_ADDR = 7'h5C;
parameter [6:0] S1_ADDR = SPLIT ? 7'h5C : 7'h5D;
parameter [6:0] DEV0 = 7'h5C;
parameter SEARCH = 1;
    reg clk = 0, rst = 1;
    always #500 clk = ~clk;                       // 1 MHz: 1 ms = 1000 cycles

    reg  present1 = (PRESENT1 != 0);
    wire scl_low, s0_low, s1_low_raw, active;
    wire [1:0] m_sda_low;
    wire s1_low = present1 ? s1_low_raw : 1'b0;
    wire scl = scl_low ? 1'b0 : 1'b1;
    wire sda0 = SPLIT ? !(m_sda_low[0] | s0_low) : !(m_sda_low[0] | s0_low | s1_low);
    wire sda1 = (SCENARIO == 4) ? 1'b0 : SPLIT ? !(m_sda_low[1] | s1_low) : sda0;
    reg trace_enable = 0;
    always @(scl or sda0 or sda1 or trace_enable)
        if (PIN_TRACE && trace_enable) $strobe("BUS %0t %b %b %b", $time, scl, sda0, sda1);
    wire resetb, init_done;
    wire [1:0] dev_err, status_valid;
    wire [15:0] status0, status1;
    wire [7:0] reinit0, reinit1;
    wire [1:0] round_ok, lost_lock, addr_alt, addr_found;
    reg mode_req = 0, mode_vcr = 0;
    reg req_pending = 0, req_pending_vcr = 0;
    reg midpoll_req_sent = 0, latest_req_sent = 0, mode_nack_cleared = 0;
    reg request_stimulus_enable = 0;
    reg mon_active = 0, mon_lane = 0;
    integer mon_88_count = 0;
    reg [3:0] mon_bits = 0;
    reg [1:0] mon_phase = 0;
    reg [7:0] mon_byte = 0, mon_addr = 0, mon_reg = 0;
    wire mon_sda = mon_lane ? sda1 : sda0;

    task queue_mode_request(input vcr);
        begin req_pending_vcr = vcr; req_pending = 1; end
    endtask
    always @(negedge clk) begin
        if (req_pending) begin
            mode_vcr = req_pending_vcr;
            mode_req = 1;
            req_pending = 0;
            $display("REQ %0t %s", $time, req_pending_vcr ? "V" : "T");
        end else mode_req = 0;
    end
    // Passive request stimulus recognizes physical address/register bytes on the resolved bus.
    // The request is deliberately injected during decoder 0's second 88h register read, before
    // its repeated START, without reading controller state or transaction wires. Waiting until
    // after the first paired sweep also keeps the preemption mutant bounded in the bench.
    always @(negedge sda0 or negedge sda1) if (scl === 1'b1) begin
        mon_lane = (SPLIT && sda0 === 1'b1 && sda1 === 1'b0);
        mon_active = 1; mon_bits = 0; mon_phase = 0; mon_byte = 0; mon_addr = 0; mon_reg = 0;
    end
    always @(posedge scl) if (mon_active) begin
        if (mon_bits < 8) begin
            mon_byte = {mon_byte[6:0], mon_sda};
            mon_bits = mon_bits + 1'b1;
            if (SCENARIO == 10 && !latest_req_sent && mon_phase == 2 &&
                (!SPLIT || mon_lane == 0) && mon_addr == 8'hB8 && mon_reg == 8'h02 &&
                mon_bits == 8 && mon_byte == 8'h20) begin
                latest_req_sent = 1;
                queue_mode_request(1'b0);                 // latest choice changes while VCR data is clocking
            end
        end else begin
            if (mon_phase == 0) begin
                mon_addr = mon_byte;
                mon_phase = 1;
            end else if (mon_phase == 1) begin
                mon_reg = mon_byte;
                if ((!SPLIT || mon_lane == 0) && mon_addr == 8'hB8 && mon_reg == 8'h88) begin
                    mon_88_count = mon_88_count + 1;
                    if (request_stimulus_enable &&
                        (SCENARIO == 9 || SCENARIO == 10 || SCENARIO == 11) &&
                        !midpoll_req_sent && mon_88_count >= 2) begin
                        midpoll_req_sent = 1;
                        queue_mode_request(1'b1);
                        if (SCENARIO == 11) s0.nack_reg = 8'h02;
                    end
                end
                // This edge is the register byte's physical ACK/NACK clock. The
                // slave has already sampled the register and driven its response.
                if (SCENARIO == 11 && midpoll_req_sent && !mode_nack_cleared &&
                    (!SPLIT || mon_lane == 0) && mon_addr == 8'hB8 && mon_reg == 8'h02 &&
                    mon_sda === 1'b1) begin
                    mode_nack_cleared = 1;
                    s0.nack_reg = -1;
                end
                mon_phase = 2;
            end else mon_phase = mon_phase + 1'b1;
            mon_bits = 0; mon_byte = 0;
        end
    end
    integer rounds0 = 0, rounds1 = 0, lost0 = 0, lost1 = 0;     // whole rounds, and those with 88h bit 4
    always @(posedge clk) begin
        if (round_ok[0]) begin rounds0 = rounds0 + 1; if (lost_lock[0]) lost0 = lost0 + 1; end
        if (round_ok[1]) begin rounds1 = rounds1 + 1; if (lost_lock[1]) lost1 = lost1 + 1; end
    end
    tvp_ctrl #(.CLK_HZ(1_000_000), .I2C_DIV(3), .POWER_MS(1), .RESET_MS(1), .BOOT_MS(1), .POLL_MS(2),
               .SPLIT_SDA(SPLIT), .DEV0(DEV0), .DEV1(SPLIT ? 7'h5C : 7'h5D), .SEARCH(SEARCH)) dut (
        .clk(clk), .rst(rst), .tvp_resetb(resetb), .scl_low(scl_low), .sda_low(m_sda_low),
        .scl_in(scl), .sda_in({sda1, sda0}), .init_done(init_done), .dev_err(dev_err),
        .status0(status0), .status1(status1), .status_valid(status_valid),
        .reinit0(reinit0), .reinit1(reinit1), .round_ok(round_ok), .lost_lock(lost_lock),
        .addr_alt(addr_alt), .addr_found(addr_found),
        .hold(1'b0), .op_mode_req(mode_req), .op_mode_vcr(mode_vcr), .active(active));
    i2c_slave_model #(.ADDR(S0_ADDR), .LOG(1)) s0 (.scl(scl), .sda(sda0), .sda_low(s0_low));
    // an absent decoder sees an idle bus
    i2c_slave_model #(.ADDR(S1_ADDR)) s1 (.scl(present1 ? scl : 1'b1), .sda(present1 ? sda1 : 1'b1),
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
            $display(" reset_low=%0d reset_falls=%0d err=%0d s0_03=%02x s0_04=%02x s0_0d=%02x s0_00=%02x s0_02=%02x s0_28=%02x s0_writes=%0d s1_03=%02x s1_04=%02x s1_0d=%02x s1_02=%02x s1_28=%02x s1_writes=%0d st0=%04x st1=%04x valid=%0d reinit0=%0d reinit1=%0d rounds0=%0d rounds1=%0d lost0=%0d lost1=%0d alt=%0d found=%0d",
                     saw_reset_low, reset_falls, dev_err, s0.regs[8'h03], s0.regs[8'h04], s0.regs[8'h0D],
                     s0.regs[8'h00], s0.regs[8'h02], s0.regs[8'h28], s0.writes,
                     s1.regs[8'h03], s1.regs[8'h04], s1.regs[8'h0D], s1.regs[8'h02], s1.regs[8'h28], s1.writes,
                     status0, status1, status_valid, reinit0, reinit1, rounds0, rounds1, lost0, lost1,
                     addr_alt, addr_found);
        end
    endtask

    initial begin
        #3000 rst = 0;
        trace_enable = PIN_TRACE;
        if (SCENARIO == 12 || SCENARIO == 13) queue_mode_request(1'b1);
        wait (init_done);
        if (SCENARIO != 14) wait (status_valid[0]);
        // a decoder whose outputs never come on (2, 4) never has valid status
        if (PRESENT1 && SCENARIO != 2 && SCENARIO != 4 && SCENARIO != 14) wait (status_valid[1]);
        #20_000_000;
        request_stimulus_enable = 1;
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
            8: begin
                s0.regs[8'h88] = s0.regs[8'h88] | 8'h10;
                #20_000_000;
            end
            9, 10, 11, 14: #20_000_000;
            12: #20_000_000;
            13: begin
                s1.tvp_reset; #30_000_000;
                show(0);
                s1.tvp_reset; #30_000_000;
            end
            3: begin
                set_present(1); #30_000_000;
                show(0);
                set_present(0); #20_000_000;
            end
            default: ;
        endcase
        wait (!active);
        #1 trace_enable = 0;
        show(1);
        $finish;
    end
    initial begin #4_000_000_000 $display("RESULT timeout"); $finish; end
endmodule
`default_nettype wire
