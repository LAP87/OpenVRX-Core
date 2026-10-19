// SSD1306 128x32 OLED over I2C as a 4 x 21 character text display (5x7 font,
// 6-pixel cells). No frame buffer: each column byte is generated from the
// character at (row, col) supplied by the user through text_row/text_col ->
// text_char (read one clock after the address is presented).
// text_big[k] draws row pair k (rows 0-1, 2-3) as one double-size row: 10 cells of
// 12 pixels, every glyph column and row twice, the top page with glyph rows 0-3 and
// the bottom page with rows 4-6; both pages ask for the pair's top row (text_row
// 0 or 2, text_col 0..9). Reference: model/oled_ref.py.
//
// Sequence: wait POWER_MS, send the init commands, then refresh forever
// (column 0-127, page 0-3, 512 data bytes in horizontal addressing mode).
// Every byte is its own I2C write: S, 3Ch+W, control (00h command / 40h data),
// byte, P — the display's address pointer advances by itself.
//
// Shared bus: before each transfer `hold_other` is raised; the transfer starts
// once `other_active` (the other master is mid-transaction) has been low for two
// clocks, and hold is dropped for a few clocks after each byte so the other
// master gets its turn. Both masters must run on the same clock. `active` lets a third
// master (rssi_adc.v in M6) wait for this one.
`default_nettype none
module ssd1306_text #(
    parameter CLK_HZ = 27_000_000,
    parameter I2C_DIV = 17,               // 27 MHz / 17 / 4 = 397 kHz
    parameter [6:0] DEV = 7'h3C,
    parameter POWER_MS = 100
) (
    input  wire       clk,
    input  wire       rst,
    output wire       scl_low, sda_low,
    input  wire       scl_in, sda_in,
    output reg        hold_other,
    input  wire       other_active,
    output reg  [1:0] text_row,
    output reg  [4:0] text_col,
    input  wire [6:0] text_char,
    input  wire [1:0] text_big,          // row pair 0-1 / 2-3 drawn double size
    output reg        frame_done,         // pulse after each full refresh
    output reg        nack_error,         // sticky: display did not acknowledge
    output wire       active              // a transfer is starting or running (other masters wait)
);
    `include "font5x7.vh"
    localparam MS = CLK_HZ / 1000;
    localparam N_INIT = 25, N_SETUP = 6;

    function [7:0] init_cmd(input [4:0] i);
        case (i)            // 128x32 module, charge pump on (common SSD1306 init)
            5'd0: init_cmd = 8'hAE;  5'd1: init_cmd = 8'hD5;  5'd2: init_cmd = 8'h80;
            5'd3: init_cmd = 8'hA8;  5'd4: init_cmd = 8'h1F;  5'd5: init_cmd = 8'hD3;
            5'd6: init_cmd = 8'h00;  5'd7: init_cmd = 8'h40;  5'd8: init_cmd = 8'h8D;
            5'd9: init_cmd = 8'h14;  5'd10: init_cmd = 8'h20; 5'd11: init_cmd = 8'h00;
            5'd12: init_cmd = 8'hA1; 5'd13: init_cmd = 8'hC8; 5'd14: init_cmd = 8'hDA;
            5'd15: init_cmd = 8'h02; 5'd16: init_cmd = 8'h81; 5'd17: init_cmd = 8'h8F;
            5'd18: init_cmd = 8'hD9; 5'd19: init_cmd = 8'hF1; 5'd20: init_cmd = 8'hDB;
            5'd21: init_cmd = 8'h40; 5'd22: init_cmd = 8'hA4; 5'd23: init_cmd = 8'hA6;
            default: init_cmd = 8'hAF;
        endcase
    endfunction
    function [7:0] setup_cmd(input [2:0] i);       // full window, start at column 0 / page 0
        case (i)
            3'd0: setup_cmd = 8'h21; 3'd1: setup_cmd = 8'h00; 3'd2: setup_cmd = 8'h7F;
            3'd3: setup_cmd = 8'h22; 3'd4: setup_cmd = 8'h00; default: setup_cmd = 8'h03;
        endcase
    endfunction

    reg        start;
    reg  [7:0] ctrl, byte_out;
    wire       busy, done, nack;
    wire [7:0] rdata;
    i2c_master #(.DIV(I2C_DIV)) i2c (
        .clk(clk), .rst(rst), .start(start), .rw(1'b0), .dev(DEV), .addr(ctrl), .wdata(byte_out),
        .wextra(8'd0), .wreq(),                                   // single-byte writes only
        .busy(busy), .done(done), .nack(nack), .rdata(rdata),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl_in), .sda_in(sda_in));

    assign active = start | busy;

    localparam S_POWER = 3'd0, S_NEXT = 3'd1, S_FONT = 3'd2, S_REQ = 3'd3, S_GO = 3'd4, S_WAIT = 3'd5, S_GAP = 3'd6;
    reg [2:0]  st;
    reg [31:0] t;
    reg [1:0]  phase;                     // 0 init, 1 window setup, 2 data
    reg [4:0]  idx;
    reg [1:0]  pg;                        // page 0..3 being drawn (text_row is its text row)
    reg [3:0]  cx;                        // column inside the cell (6 pixels, 12 double size)
    reg [6:0]  px;                        // pixel column 0..127
    reg [1:0]  free_cnt;
    wire       big  = text_big[pg[1]];
    wire [2:0] gcol = big ? cx[3:1] : cx[2:0];
    wire [1:0] pg_n = pg + 1'b1;
    wire [7:0] glyph = (gcol < 3'd5 && text_col < (big ? 5'd10 : 5'd21)) ? font5x7(text_char, gcol) : 8'h00;
    wire [7:0] gbyte = !big ? glyph
                     : !pg[0] ? {glyph[3], glyph[3], glyph[2], glyph[2], glyph[1], glyph[1], glyph[0], glyph[0]}
                     : {2'b00, glyph[6], glyph[6], glyph[5], glyph[5], glyph[4], glyph[4]};

    always @(posedge clk) begin
        start <= 1'b0;
        frame_done <= 1'b0;
        case (st)
        S_POWER: begin
            t <= t + 1;
            if (t == POWER_MS * MS) begin phase <= 0; idx <= 0; st <= S_NEXT; end
        end
        S_NEXT: begin                     // choose the next byte
            if (phase == 2'd0) begin ctrl <= 8'h00; byte_out <= init_cmd(idx); st <= S_REQ; end
            else if (phase == 2'd1) begin ctrl <= 8'h00; byte_out <= setup_cmd(idx[2:0]); st <= S_REQ; end
            else begin ctrl <= 8'h40; st <= S_FONT; end            // text_row/col already set
        end
        S_FONT: begin                     // text_char valid one clock after the address
            byte_out <= gbyte;
            st <= S_REQ;
        end
        S_REQ: begin hold_other <= 1'b1; free_cnt <= 0; st <= S_GO; end
        S_GO: begin                       // other master idle for two clocks after hold rose
            if (other_active) free_cnt <= 0;
            else if (free_cnt != 2'd3) free_cnt <= free_cnt + 1'b1;
            if (free_cnt == 2'd2 && !other_active && !busy) begin start <= 1'b1; st <= S_WAIT; end
        end
        S_WAIT: if (done) begin
            if (nack) nack_error <= 1'b1;
            hold_other <= 1'b0; t <= 0; st <= S_GAP;
            // advance
            if (phase == 2'd0) begin
                if (idx == N_INIT - 1) begin phase <= 2'd1; idx <= 0; end else idx <= idx + 1'b1;
            end else if (phase == 2'd1) begin
                if (idx == N_SETUP - 1) begin
                    phase <= 2'd2; px <= 0; cx <= 0; pg <= 0; text_row <= 0; text_col <= 0;
                end else idx <= idx + 1'b1;
            end else begin
                if (px == 7'd127) begin
                    px <= 0; cx <= 0; text_col <= 0;
                    if (pg == 2'd3) begin pg <= 0; text_row <= 0; frame_done <= 1'b1; phase <= 2'd1; idx <= 0; end
                    else begin pg <= pg_n; text_row <= text_big[pg_n[1]] ? {pg_n[1], 1'b0} : pg_n; end
                end else begin
                    px <= px + 1'b1;
                    if (cx == (big ? 4'd11 : 4'd5)) begin cx <= 0; text_col <= text_col + 1'b1; end
                    else cx <= cx + 1'b1;
                end
            end
        end
        S_GAP: begin                      // let the other master in
            t <= t + 1;
            if (t == 3) st <= S_NEXT;
        end
        default: st <= S_POWER;
        endcase
        if (rst) begin
            st <= S_POWER; t <= 0; hold_other <= 1'b0; start <= 1'b0; nack_error <= 1'b0;
            text_row <= 0; text_col <= 0; cx <= 0; px <= 0; pg <= 0; phase <= 0; idx <= 0; frame_done <= 1'b0;
        end
    end
endmodule
`default_nettype wire
