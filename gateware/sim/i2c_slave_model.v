// Behavioural I2C register slave (TVP5150-like: 8-bit register pointer,
// auto-increment). Drives sda_low only while SCL is low.
//
// Register defaults are the TVP5150AM1's (SLES209E table 3-11) where the tests
// look: 03h = 01h (outputs off), 04h = DCh (autoswitch mask), 02h = 00h (TV/VCR
// mode automatic), 28h = 00h (video standard autoswitch). 0Dh starts at 00h
// instead of the real 47h, so that a test can see it being written.
// Status as a healthy NTSC input reads (SLES209E 3.21.49, 3.21.50):
//   88h = 0Eh  H, V and colour lock; bit5 = 0: 60 Hz; bit6 = 0: not line alternating
//   89h = 00h  no weak signal (bit6); bit4 follows the field, so 10h is as healthy
// Healthy PAL reads 88h = 6Eh (50 Hz, line alternating); 89h bit5 is the PAL switch.
// Testbench hooks: tvp_reset (registers back to defaults, as after RESETB or a
// supply dip), wr_protect (writes are acknowledged but ignored), nack_data
// (>= 0: the data byte with that index in a write, counted from 0 after the
// register byte, is not acknowledged and not stored, nor is anything after it
// until the next START), nack_reg (>= 0: a register byte with that value is not
// acknowledged, so a read or write of that register fails).
// AUTO_INC = 0 gives a slave whose register pointer does not advance (negative
// control for multi-byte writes in sim/test_i2c_master.py).
`timescale 1ns/1ps
module i2c_slave_model #(
    parameter [6:0] ADDR = 7'h5C,
    parameter LOG = 0,                    // 1: $display every register write and read
    parameter PAGED = 0,                  // 1: LT8618SX-style pages, register FFh selects page (low 3 bits)
    parameter AUTO_INC = 1                // 0: the register pointer stays where the register byte put it
) (
    input  wire scl,
    input  wire sda,
    output reg  sda_low
);
    reg [7:0] regs [0:2047];              // {page[2:0], reg} when PAGED
    reg [7:0] ptr, sh, page;
    wire [10:0] ix = PAGED ? {page[2:0], ptr} : {3'd0, ptr};
    integer   bitc, phase;
    reg       active, reading, me, send, master_ack;
    reg       wr_protect;
    integer   writes;
    integer   nack_data, dcount;              // see above; data bytes seen in this write
    integer   nack_reg;                       // >= 0: the register byte with this value is not acknowledged
    integer i;
    task tvp_reset;
        begin
            regs[8'h00] = 8'h00; regs[8'h03] = 8'h01; regs[8'h04] = 8'hDC; regs[8'h0D] = 8'h00;
            regs[8'h02] = 8'h00; regs[8'h28] = 8'h00;
        end
    endtask
    initial begin
        for (i = 0; i < 2048; i = i + 1) regs[i] = 8'h00;
        page = 0;
        tvp_reset;
        regs[8'h80] = 8'h51; regs[8'h81] = 8'h50;          // device ID 5150
        regs[8'h88] = 8'h0E; regs[8'h89] = 8'h00;          // healthy NTSC
        sda_low = 0; active = 0; writes = 0; wr_protect = 0; nack_data = -1; nack_reg = -1; dcount = 0;
    end

    always @(negedge sda) if (scl === 1'b1) begin          // START / repeated START
        active = 1; bitc = 0; phase = 0; reading = 0; me = 0; send = 0; sda_low = 0; dcount = 0;
    end
    always @(posedge sda) if (scl === 1'b1) begin          // STOP
        active = 0; sda_low = 0;
    end

    always @(posedge scl) if (active) begin
        if (bitc < 8) begin
            if (!reading) sh = {sh[6:0], sda};
            bitc = bitc + 1;
        end else if (bitc == 8) begin
            if (reading) master_ack = (sda === 1'b0);
            bitc = 9;
        end
    end

    always @(negedge scl) if (active) begin
        if (bitc == 8) begin                                // byte complete: ACK slot
            if (reading) sda_low = 0;                       // master answers
            else if (phase == 0) begin
                me = (sh[7:1] == ADDR); reading = sh[0]; send = sh[0] && me;
                sda_low = me; phase = 1;
            end else if (me) begin
                sda_low = 1;
                if (phase == 1 && sh == nack_reg) begin            // refuse this register (writes and reads)
                    me = 0; sda_low = 0;
                end else if (phase == 1) begin ptr = sh; phase = 2; end
                else if (dcount == nack_data) begin
                    if (LOG) $display("I2C N %02x %02x", ptr, sh);
                    me = 0; sda_low = 0;                    // NACK, and nothing more in this write
                end else begin
                    if (LOG) $display("I2C W %02x %02x", ptr, sh);
                    if (PAGED && ptr == 8'hFF) page = sh;
                    else if (!wr_protect) regs[ix] = sh;
                    if (AUTO_INC) ptr = ptr + 1;
                    writes = writes + 1; dcount = dcount + 1;
                end
            end
        end else if (bitc == 9) begin                       // ACK slot over
            bitc = 0; sda_low = 0;
            if (reading && phase > 1) send = master_ack;
            if (reading) phase = 2;
            if (reading && send) begin
                sh = regs[ix];
                if (LOG) $display("I2C R %02x %02x", ptr, sh);
                if (AUTO_INC) ptr = ptr + 1;
                sda_low = !sh[7];
            end
        end else if (reading && send) begin
            sda_low = !sh[7 - bitc];
        end
    end
endmodule
