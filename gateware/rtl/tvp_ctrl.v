// Brings up our own TVP5150AM1 decoders over I2C and polls their status.
// Not for the Moneagle tap: there the Moneagle SoC owns the I2C bus.
//
// Sequence (Linux tvp5150.c and TI SLES209E): hold RESETB low 2 ms after
// power-up settles (20 ms), release, wait 1 ms, then per decoder write
//   00h = 00h  input AIP1A (composite)
//   03h = 0Dh  YCbCr, sync and SCLK outputs enabled (default 01h keeps the bus off)
//   0Dh = 47h  8-bit 4:2:2 ITU-R BT.656, embedded syncs
// then every POLL_MS read 88h (status 1: bit1 H lock, bit2 V lock, bit3
// colour lock, bit4 lost lock since last read, bit5 60 Hz) and 89h (status 2:
// bit6 weak signal). I2C addresses 5Ch (B8h) and 5Dh (BAh), set by YOUT7's
// pull at reset. Two identical modules have the same address (the pull is fixed
// on the module): then use SPLIT_SDA = 1, one SDA line per decoder and a shared
// SCL; DEV1 may then equal DEV0.
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
    output reg         init_done,
    output reg  [1:0]  dev_err,           // sticky: a decoder did not acknowledge
    output reg  [15:0] status0,           // {89h, 88h} of decoder 0
    output reg  [15:0] status1,
    output reg  [1:0]  status_valid,      // a poll result has arrived since reset
    input  wire        hold,              // another master on the same bus wants it: start nothing new
    output wire        active             // a transaction is starting or running
);
    localparam MS = CLK_HZ / 1000;
    localparam N_INIT = 3;

    function [15:0] init_rom(input [1:0] i);
        case (i)
            2'd0: init_rom = 16'h00_00;
            2'd1: init_rom = 16'h03_0D;
            default: init_rom = 16'h0D_47;
        endcase
    endfunction

    localparam S_POWER = 3'd0, S_RESET = 3'd1, S_BOOT = 3'd2, S_INIT = 3'd3, S_WAIT = 3'd4, S_POLL = 3'd5;
    reg [2:0]  st, ret;                   // ret: state after the running transaction
    reg [31:0] t;
    reg        di;                        // decoder index
    reg [1:0]  ii;                        // init entry / poll register (0: 88h, 1: 89h)

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
            if (nack) dev_err[di] <= 1'b1;
            if (ret == S_INIT) begin
                if (ii == N_INIT - 1) begin
                    ii <= 0;
                    if (di == N_DEV - 1) begin di <= 0; init_done <= 1'b1; t <= 0; st <= S_POLL; end
                    else begin di <= di + 1'b1; st <= S_INIT; end
                end else begin ii <= ii + 1'b1; st <= S_INIT; end
            end else begin
                if (!nack) begin
                    if (di) begin if (ii[0]) status1[15:8] <= rdata; else status1[7:0] <= rdata; end
                    else    begin if (ii[0]) status0[15:8] <= rdata; else status0[7:0] <= rdata; end
                    if (ii[0]) status_valid[di] <= 1'b1;
                end
                if (!ii[0]) begin ii <= 2'd1; st <= S_POLL; t <= POLL_MS * MS; end        // now 89h
                else begin
                    ii <= 0;
                    if (di == N_DEV - 1) begin di <= 0; t <= 0; end
                    else begin di <= di + 1'b1; t <= POLL_MS * MS; end
                    st <= S_POLL;
                end
            end
        end
        S_POLL: begin
            if (t < POLL_MS * MS) t <= t + 1;
            else if (!busy && !start && !hold) begin
                start <= 1'b1; rw <= 1'b1; dev <= di ? DEV1 : DEV0; addr <= ii[0] ? 8'h89 : 8'h88;
                st <= S_WAIT; ret <= S_POLL;
            end
        end
        default: st <= S_POWER;
        endcase
        if (rst) begin
            st <= S_POWER; t <= 0; tvp_resetb <= 1'b1; init_done <= 1'b0; dev_err <= 2'b00;
            status_valid <= 2'b00; status0 <= 0; status1 <= 0; di <= 0; ii <= 0; start <= 1'b0;
        end
    end
endmodule
`default_nettype wire
