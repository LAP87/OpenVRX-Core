// Minimal I2C master for register access (TVP5150, LT8618SX):
//   write: S, dev+W, reg, data, P
//   write with wextra = n > 0: S, dev+W, reg, data 0, data 1 .. data n, P
//          (the slave's register pointer auto-increments)
//   read:  S, dev+W, reg, Sr, dev+R, data (NACK), P
//   read with READ_BYTES = 2: S, dev+W, reg, Sr, dev+R, data 0 (ACK), data 1 (NACK), P;
//          rdata = {data 0, data 1} (ADS1115 conversion register, MSB first)
// Open drain: *_low = 1 pulls the line low, 0 releases it (top level does the
// tristate). Waits while a slave stretches SCL. ~100 kHz with DIV = clk/400k.
//
// Multi-byte write: data 0 is wdata at `start`, as in a single-byte write. Each
// time a data byte that has a successor starts on the bus, wreq pulses; wdata
// must then show the next byte before that byte's ACK slot ends (at least
// 32 x DIV clocks later). A multi-byte write ends with P right after the first
// byte that is not acknowledged (nack with done); the bytes after it are not
// sent and wreq does not pulse for them. A single-byte write (wextra = 0)
// behaves as before: all its bytes are sent, nack reports any NACK.
//
// A slave may stretch SCL for up to STRETCH_MAX clocks at a time. If SCL is
// held low longer, the transaction ends there: both lines are released, done
// pulses with nack and stuck set, and busy drops. Nothing more is sent; the
// next transaction starts with START as usual (and ends the same way if SCL
// is still held low).
`default_nettype none
module i2c_master #(
    parameter DIV = 68,                   // clock cycles per quarter bit (27 MHz / 68 / 4 = 99 kHz)
    parameter LEN_W = 8,                  // width of wextra: up to 2^LEN_W data bytes per write
    parameter STRETCH_MAX = 270_000,      // 10 ms at 27 MHz
    parameter READ_BYTES = 1              // 1 or 2 data bytes per read; the master ACKs all but the last
) (
    input  wire       clk,
    input  wire       rst,
    input  wire       start,              // pulse while !busy
    input  wire       rw,                 // 0 write, 1 read
    input  wire [6:0] dev,
    input  wire [7:0] addr,
    input  wire [7:0] wdata,
    input  wire [LEN_W-1:0] wextra,       // write: data bytes after the first (0 = one byte); read: ignored
    output reg        wreq,               // pulse: put the next data byte on wdata
    output reg        busy,
    output reg        done,               // pulse at the end of a transaction
    output reg        nack,               // with done: some byte was not acknowledged
    output reg        stuck,              // with done: SCL was held low longer than STRETCH_MAX
    output reg  [8*READ_BYTES-1:0] rdata,
    output reg        scl_low,
    output reg        sda_low,
    input  wire       scl_in,
    input  wire       sda_in
);
    localparam T_START = 3'd0, T_BYTE = 3'd1, T_RSTART = 3'd2, T_READ = 3'd3, T_STOP = 3'd4;

    reg       op_rw, op_multi;
    reg [6:0] op_dev;
    reg [7:0] op_addr, op_wdata;
    reg [LEN_W-1:0] rem;                  // write: data bytes still to come after the current one
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
            3'd6: if (READ_BYTES > 1) tok = T_READ; else begin tok = T_STOP; tok_last = 1'b1; end
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
    reg [$clog2(STRETCH_MAX + 1)-1:0] st_n;   // clocks SCL has been held low in this stretch

    // write data token (tk 3) of a write
    wire is_data = !op_rw && (tk == 3'd3);

    always @(posedge clk) begin
        done <= 1'b0;
        wreq <= 1'b0;
        if (!busy) begin
            div <= 0; ph <= 0; bitn <= 0; tk <= 0;
            st_n <= 0;
            if (start) begin
                busy <= 1'b1; nack <= 1'b0; stuck <= 1'b0;
                op_rw <= rw; op_dev <= dev; op_addr <= addr; op_wdata <= wdata;
                rem <= rw ? {LEN_W{1'b0}} : wextra;
                op_multi <= !rw && (wextra != {LEN_W{1'b0}});
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
                        if (bitn == 0 && is_data && rem != {LEN_W{1'b0}}) wreq <= 1'b1;
                        // ACK slot and read bits: release SDA (the master NACKs its last read byte),
                        // except the ACK slot of a read byte that has a successor: ACK it
                        if (bitn == 8 && tok == T_READ && READ_BYTES > 1 && tk == 3'd5) sda_low <= 1'b1;
                        else if (bitn == 8 || tok == T_READ) sda_low <= 1'b0;
                        else sda_low <= ~((bitn == 0) ? tok_byte[7] : sh[7]);
                    end
                    2'd1: scl_low <= 1'b0;
                    2'd2: begin
                        if (bitn == 8) begin
                            if (tok == T_BYTE && sda_s[1]) nack <= 1'b1;
                        end else begin
                            if (tok == T_READ) rdata <= {rdata[8*READ_BYTES-2:0], sda_s[1]};
                            sh <= {sh[6:0], 1'b0};
                        end
                    end
                    2'd3: begin
                        scl_low <= 1'b1;
                        if (bitn == 8) begin
                            bitn <= 0;
                            if (op_multi && nack) tk <= 3'd4;                   // multi-byte write: P now
                            else if (is_data && rem != {LEN_W{1'b0}}) begin     // next data byte
                                op_wdata <= wdata; rem <= rem - 1'b1;
                            end else tk <= tk + 1'b1;
                        end else bitn <= bitn + 1'b1;
                    end
                endcase
                endcase
            end
            // SCL held low too long: give up, release both lines
            st_n <= stretch ? st_n + 1'b1 : 0;
            if (stretch && st_n == STRETCH_MAX - 1) begin
                busy <= 1'b0; done <= 1'b1; nack <= 1'b1; stuck <= 1'b1; scl_low <= 1'b0; sda_low <= 1'b0;
            end
        end
        if (rst) begin
            busy <= 1'b0; done <= 1'b0; nack <= 1'b0; stuck <= 1'b0; scl_low <= 1'b0; sda_low <= 1'b0; wreq <= 1'b0;
        end
    end
endmodule
`default_nettype wire
