// Brings up our own TVP5150AM1 decoders over I2C, polls their status and
// brings a decoder up again when it has been reset.
// Not for the Moneagle tap: there the Moneagle SoC owns the I2C bus.
//
// Sequence (TI SLES209E 3.18 and 5.2, Linux tvp5150.c): hold RESETB low 2 ms
// after power-up settles (20 ms), release, wait 1 ms, then per decoder write
//   00h = 00h  input AIP1A (composite)
//   04h = FCh  autoswitch mask: SECAM masked as well. SLES209E 3.21.5, bit 5 SEC_OFF:
//              "1 = SECAM is masked from the autoswitch process. Autoswitch does not
//              switch to SECAM." Default DCh already masks NTSC 4.43, PAL-N and PAL-M;
//              (M) NTSC and (B, G, H, I) PAL stay. Bits 7:6 are written as in the
//              default and in TI's example 5.2.2 (C0h). Two decoders on noise can
//              then not disagree about SECAM.
//   0Dh = 47h  8-bit 4:2:2 ITU-R BT.656, embedded syncs
//   03h = 0Dh  YCbCr, sync and SCLK outputs enabled (default 01h keeps the bus off)
// 03h goes last, and the list stops at the first write that is not
// acknowledged. So 03h = 0Dh means the whole list arrived.
//
// Then every POLL_MS, per decoder, read
//   88h  status 1: bit0 VCR, bit1 H lock, bit2 V lock, bit3 colour lock, bit4 lost
//        lock since the last read, bit5 field rate (0 = 60 Hz, 1 = 50 Hz), bit6 line
//        alternating (PAL), bit7 peak white
//   89h  status 2: bit3 AGC frozen, bit4 field, bit5 PAL switch, bit6 weak signal
//   03h  read-back. Anything but 0Dh means the decoder has been reset (supply dip,
//        glitch on RESETB) and its outputs are off: the init list is written again
//        and reinitN counts it. RESETB is not pulsed, the other decoder keeps running.
// A poll round counts as a whole: its status words are published and dev_err
// cleared only when all three reads were acknowledged, and status_valid is set
// only if 03h also read 0Dh. A NACK on any read ends the round with dev_err set
// and status_valid cleared (the words from before stay, no longer valid). A
// reset decoder publishes its words but clears status_valid until a later
// whole round finds it up. A later ACK never makes a failed round valid.
//
// I2C addresses 5Ch (B8h) and 5Dh (BAh), set by YOUT7's pull at reset. Two
// identical modules have the same address (the pull is fixed on the module):
// then use SPLIT_SDA = 1, one SDA line per decoder and a shared SCL; DEV1 may
// then equal DEV0. The F bit setting (15h) is left at its default.
`default_nettype none
module tvp_ctrl #(
    parameter CLK_HZ = 27_000_000,
    parameter I2C_DIV = 68,
    parameter N_DEV = 2,
    parameter [6:0] DEV0 = 7'h5C,
    parameter [6:0] DEV1 = 7'h5D,
    parameter POWER_MS = 20, RESET_MS = 2, BOOT_MS = 1, POLL_MS = 20,
    parameter SPLIT_SDA = 0
) (
    input  wire        clk,
    input  wire        rst,
    output reg         tvp_resetb,
    output wire        scl_low,
    output wire [1:0]  sda_low,           // [0] shared bus (or decoder 0), [1] decoder 1 when SPLIT_SDA
    input  wire        scl_in,
    input  wire [1:0]  sda_in,
    output reg         init_done,         // the init list has been tried on every decoder
    output reg  [1:0]  dev_err,           // the decoder's last init list or poll round had a NACK
    output reg  [15:0] status0,           // {89h, 88h} of decoder 0, from its last round with all reads acknowledged
    output reg  [15:0] status1,
    output reg  [1:0]  status_valid,      // the decoder's last poll round was whole and found it up
    output reg  [7:0]  reinit0,           // times decoder 0 was found reset and brought up again (stops at FFh)
    output reg  [7:0]  reinit1,
    input  wire        hold,              // another master on the same bus wants it: start nothing new
    output wire        active             // a transaction is starting or running
);
    localparam MS = CLK_HZ / 1000;
    localparam N_INIT = 4;
    localparam [7:0] MISC_ON = 8'h0D;     // register 03h when the decoder is up

    function [15:0] init_rom(input [1:0] i);
        case (i)
            2'd0: init_rom = 16'h00_00;
            2'd1: init_rom = 16'h04_FC;
            2'd2: init_rom = 16'h0D_47;
            default: init_rom = {8'h03, MISC_ON};
        endcase
    endfunction
    function [7:0] poll_reg(input [1:0] i);
        case (i)
            2'd0: poll_reg = 8'h88;
            2'd1: poll_reg = 8'h89;
            default: poll_reg = 8'h03;
        endcase
    endfunction
    localparam [1:0] P_LAST = 2'd2;       // index of the read-back in poll_reg

    localparam S_POWER = 3'd0, S_RESET = 3'd1, S_BOOT = 3'd2, S_INIT = 3'd3, S_WAIT = 3'd4, S_POLL = 3'd5,
               S_NEXT = 3'd6;
    reg [2:0]  st, ret;                   // ret: state after the running transaction
    reg [31:0] t;
    reg        di;                        // decoder index
    reg [1:0]  ii;                        // init entry / poll register
    reg        again;                     // the running init list is a re-initialisation inside a poll round
    reg [7:0]  p88, p89;                  // the running poll round's status, published when the round is whole

    reg        start, rw;
    reg [6:0]  dev;
    reg [7:0]  addr, wdata;
    wire       busy, done, nack;
    wire [7:0] rdata;
    wire       m_sda_low;
    wire       sel1 = SPLIT_SDA && di;
    assign sda_low = {sel1 & m_sda_low, ~sel1 & m_sda_low};
    i2c_master #(.DIV(I2C_DIV)) i2c (
        .clk(clk), .rst(rst), .start(start), .rw(rw), .dev(dev), .addr(addr), .wdata(wdata),
        .wextra(8'd0), .wreq(),                                   // single-byte writes only
        .busy(busy), .done(done), .nack(nack), .rdata(rdata),
        .scl_low(scl_low), .sda_low(m_sda_low), .scl_in(scl_in), .sda_in(sel1 ? sda_in[1] : sda_in[0]));


    assign active = start | busy;

    always @(posedge clk) begin
        start <= 1'b0;
        case (st)
        S_POWER: begin tvp_resetb <= 1'b1; t <= t + 1; if (t == POWER_MS * MS) begin t <= 0; st <= S_RESET; end end
        S_RESET: begin tvp_resetb <= 1'b0; t <= t + 1; if (t == RESET_MS * MS) begin t <= 0; st <= S_BOOT; end end
        S_BOOT:  begin tvp_resetb <= 1'b1; t <= t + 1; if (t == BOOT_MS * MS) begin t <= 0; di <= 0; ii <= 0; st <= S_INIT; end end
        S_INIT: if (!busy && !start && !hold) begin
            start <= 1'b1; rw <= 1'b0; dev <= di ? DEV1 : DEV0;
            {addr, wdata} <= init_rom(ii);
            st <= S_WAIT; ret <= S_INIT;
        end
        S_WAIT: if (done) begin
            if (ret == S_INIT) begin
                dev_err[di] <= nack;
                if (ii == N_INIT - 1 || nack) begin                  // list done, or nobody there
                    ii <= 0;
                    if (again) begin again <= 1'b0; st <= S_NEXT; end
                    else if (di == N_DEV - 1) begin di <= 0; init_done <= 1'b1; t <= 0; st <= S_POLL; end
                    else begin di <= di + 1'b1; st <= S_INIT; end
                end else begin ii <= ii + 1'b1; st <= S_INIT; end
            end else begin
                if (nack) begin                                      // the round is void
                    dev_err[di] <= 1'b1; status_valid[di] <= 1'b0; st <= S_NEXT;
                end else if (ii != P_LAST) begin                     // next register at once
                    if (ii == 2'd0) p88 <= rdata; else p89 <= rdata;
                    ii <= ii + 1'b1; st <= S_POLL; t <= POLL_MS * MS;
                end else begin                                       // a whole round: publish it
                    if (di) status1 <= {p89, p88}; else status0 <= {p89, p88};
                    dev_err[di] <= 1'b0;
                    if (rdata != MISC_ON) begin                      // ... but the decoder has been reset
                        if (di) begin if (reinit1 != 8'hFF) reinit1 <= reinit1 + 1'b1; end
                        else    begin if (reinit0 != 8'hFF) reinit0 <= reinit0 + 1'b1; end
                        status_valid[di] <= 1'b0;
                        again <= 1'b1; ii <= 0; st <= S_INIT;
                    end else begin
                        status_valid[di] <= 1'b1;
                        st <= S_NEXT;
                    end
                end
            end
        end
        S_POLL: begin
            if (t < POLL_MS * MS) t <= t + 1;
            else if (!busy && !start && !hold) begin
                start <= 1'b1; rw <= 1'b1; dev <= di ? DEV1 : DEV0; addr <= poll_reg(ii);
                st <= S_WAIT; ret <= S_POLL;
            end
        end
        S_NEXT: begin                                                // next decoder; a pause after the last one
            ii <= 0; st <= S_POLL;
            if (di == N_DEV - 1) begin di <= 0; t <= 0; end
            else begin di <= di + 1'b1; t <= POLL_MS * MS; end
        end
        default: st <= S_POWER;
        endcase
        if (rst) begin
            st <= S_POWER; t <= 0; tvp_resetb <= 1'b1; init_done <= 1'b0; dev_err <= 2'b00;
            status_valid <= 2'b00; status0 <= 0; status1 <= 0; di <= 0; ii <= 0; start <= 1'b0;
            again <= 1'b0; reinit0 <= 0; reinit1 <= 0;
        end
    end
endmodule
`default_nettype wire
