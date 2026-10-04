// Minimal I2C master for register access (TVP5150, LT8618SX):
//   write: S, dev+W, reg, data, P
//   read:  S, dev+W, reg, Sr, dev+R, data (NACK), P
// Open drain: *_low = 1 pulls the line low, 0 releases it (top level does the
// tristate). Waits while a slave stretches SCL. ~100 kHz with DIV = clk/400k.
`default_nettype none
module i2c_master #(
    parameter DIV = 68                    // clock cycles per quarter bit (27 MHz / 68 / 4 = 99 kHz)
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,              // pulse while !busy
    input  wire       rw,                 // 0 write, 1 read
    input  wire [6:0] dev,
    input  wire [7:0] addr,
    input  wire [7:0] wdata,
    output reg        busy,
    output reg        done,               // pulse at the end of a transaction
    output reg        nack,               // with done: some byte was not acknowledged
    output reg  [7:0] rdata,
    output reg        scl_low,
    output reg        sda_low,
    input  wire       scl_in,
    input  wire       sda_in
);
    localparam T_START = 3'd0, T_BYTE = 3'd1, T_RSTART = 3'd2, T_READ = 3'd3, T_STOP = 3'd4;

    reg       op_rw;
    reg [6:0] op_dev;
    reg [7:0] op_addr, op_wdata;
    reg [2:0] tk;                         // token index within the transaction

    // token list per transaction type
    reg [2:0] tok;
    reg [7:0] tok_byte;
    reg       tok_last;
    always @* begin
        tok_byte = 8'h00; tok_last = 1'b0;
        if (!op_rw) case (tk)
            3'd0: tok = T_START;
            3'd1: begin tok = T_BYTE; tok_byte = {op_dev, 1'b0}; end
            3'd2: begin tok = T_BYTE; tok_byte = op_addr; end
            3'd3: begin tok = T_BYTE; tok_byte = op_wdata; end
            default: begin tok = T_STOP; tok_last = 1'b1; end
        endcase else case (tk)
            3'd0: tok = T_START;
            3'd1: begin tok = T_BYTE; tok_byte = {op_dev, 1'b0}; end
            3'd2: begin tok = T_BYTE; tok_byte = op_addr; end
            3'd3: tok = T_RSTART;
            3'd4: begin tok = T_BYTE; tok_byte = {op_dev, 1'b1}; end
            3'd5: tok = T_READ;
            default: begin tok = T_STOP; tok_last = 1'b1; end
        endcase
    end

    reg [$clog2(DIV)-1:0] div;
    reg [1:0] ph;                         // quarter-bit phase
    reg [3:0] bitn;                       // 0..8 within a byte (8 = ACK)
    reg [7:0] sh;
    wire tick = (div == DIV - 1);
    reg [1:0] scl_s, sda_s;               // synchronisers
    always @(posedge clk) begin scl_s <= {scl_s[0], scl_in}; sda_s <= {sda_s[0], sda_in}; end
    wire stretch = (ph == 2'd2) && !scl_low && !scl_s[1];

    always @(posedge clk) begin
        done <= 1'b0;
        if (!busy) begin
            div <= 0; ph <= 0; bitn <= 0; tk <= 0;
            if (start) begin
                busy <= 1'b1; nack <= 1'b0;
                op_rw <= rw; op_dev <= dev; op_addr <= addr; op_wdata <= wdata;
            end
        end else begin
            // hold the high phases while a slave stretches the clock
            if (!stretch) div <= tick ? 0 : div + 1'b1;
            if (tick && !stretch) begin
                ph <= ph + 1'b1;
                case (tok)
                T_START: case (ph)         // SDA high, SCL high, SDA low, SCL low
                    2'd0: begin sda_low <= 1'b0; scl_low <= 1'b0; end
                    2'd1: ;
                    2'd2: sda_low <= 1'b1;
                    2'd3: begin scl_low <= 1'b1; tk <= tk + 1'b1; end
                endcase
                T_RSTART: case (ph)        // from SCL low: SDA high, SCL high, SDA low, SCL low
                    2'd0: sda_low <= 1'b0;
                    2'd1: scl_low <= 1'b0;
                    2'd2: sda_low <= 1'b1;
                    2'd3: begin scl_low <= 1'b1; tk <= tk + 1'b1; end
                endcase
                T_STOP: case (ph)          // SDA low, SCL high, SDA high
                    2'd0: sda_low <= 1'b1;
                    2'd1: scl_low <= 1'b0;
                    2'd2: ;
                    2'd3: begin sda_low <= 1'b0; busy <= 1'b0; done <= 1'b1; end
                endcase
                default: case (ph)         // T_BYTE / T_READ: 8 data bits + ACK
                    2'd0: begin
                        if (bitn == 0) sh <= tok_byte;
                        // ACK slot and read bits: release SDA (the master NACKs its single read byte)
                        if (bitn == 8 || tok == T_READ) sda_low <= 1'b0;
                        else sda_low <= ~((bitn == 0) ? tok_byte[7] : sh[7]);
                    end
                    2'd1: scl_low <= 1'b0;
                    2'd2: begin
                        if (bitn == 8) begin
                            if (tok == T_BYTE && sda_s[1]) nack <= 1'b1;
                        end else begin
                            if (tok == T_READ) rdata <= {rdata[6:0], sda_s[1]};
                            sh <= {sh[6:0], 1'b0};
                        end
                    end
                    2'd3: begin
                        scl_low <= 1'b1;
                        if (bitn == 8) begin bitn <= 0; tk <= tk + 1'b1; end
                        else bitn <= bitn + 1'b1;
                    end
                endcase
                endcase
            end
        end
        if (rst) begin
            busy <= 1'b0; done <= 1'b0; nack <= 1'b0; scl_low <= 1'b0; sda_low <= 1'b0;
        end
    end
endmodule
`default_nettype wire
