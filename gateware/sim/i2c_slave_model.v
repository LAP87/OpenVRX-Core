// Behavioural I2C register slave (TVP5150-like: 8-bit register pointer,
// auto-increment). Drives sda_low only while SCL is low.
`timescale 1ns/1ps
module i2c_slave_model #(
    parameter [6:0] ADDR = 7'h5C,
    parameter LOG = 0,                    // 1: $display every register write and read
    parameter PAGED = 0                   // 1: LT8618SX-style pages, register FFh selects page (low 3 bits)
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
    integer   writes;
    integer i;
    initial begin
        for (i = 0; i < 2048; i = i + 1) regs[i] = 8'h00;
        page = 0;
        regs[8'h03] = 8'h01; regs[8'h0D] = 8'h00;
        regs[8'h80] = 8'h51; regs[8'h81] = 8'h50;          // device ID 5150
        regs[8'h88] = 8'h0E; regs[8'h89] = 8'h00;          // H, V and colour locked, 60 Hz; no weak signal (SLES209E 3.21.49-50)
        sda_low = 0; active = 0; writes = 0;
    end

    always @(negedge sda) if (scl === 1'b1) begin          // START / repeated START
        active = 1; bitc = 0; phase = 0; reading = 0; me = 0; send = 0; sda_low = 0;
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
                if (phase == 1) begin ptr = sh; phase = 2; end
                else begin
                    if (LOG) $display("I2C W %02x %02x", ptr, sh);
                    if (PAGED && ptr == 8'hFF) page = sh;
                    else regs[ix] = sh;
                    ptr = ptr + 1; writes = writes + 1;
                end
                sda_low = 1;
            end
        end else if (bitc == 9) begin                       // ACK slot over
            bitc = 0; sda_low = 0;
            if (reading && phase > 1) send = master_ack;
            if (reading) phase = 2;
            if (reading && send) begin
                sh = regs[ix];
                if (LOG) $display("I2C R %02x %02x", ptr, sh);
                ptr = ptr + 1;
                sda_low = !sh[7];
            end
        end else if (reading && send) begin
            sda_low = !sh[7 - bitc];
        end
    end
endmodule
