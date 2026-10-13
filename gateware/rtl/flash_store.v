// Saved settings in the Tang Nano 20K's SPI flash (XTX XT25F64F on the MSPI pins 59-62,
// WP# on 57; Sipeed schematic 3923), after configuration. Model: model/flash_store_ref.py.
// Testbench: sim/tb_flash_store.v with sim/spi_flash_model.v.
//
// Layout: the last two 4 KB sectors (SECTOR0 = 7FE000h and 7FF000h), far above the bitstream
// (a GW2AR-18 bitstream ends below about E0000h). Each sector holds 256 records of 16 bytes:
//   A5h, seq[15:8], seq[7:0], payload (10 bytes, see below), FFh, FFh, CRC-8 (poly 07h, init 0)
//   over the first 15 bytes.
// A new record goes in the slot after the newest one when that slot is erased, else in slot 0
// of the other sector, which is erased first. A sector is therefore erased once per 256 saves
// (about 25 million saves at the 100k erase cycles the part is rated for), and the newest
// record of the other sector is still there while one is being erased.
//
// Start: one read of both sectors (8 KB, about 10 ms at clk / 4); the valid record (magic and
// CRC) with the newest sequence number (serial-number order, mod 2^16) is loaded: `load` pulses
// with it in `loaded`. Without a valid record nothing is loaded (the defaults stay).
// Saving: when `cur` differs from what was last saved or loaded and has then not changed for
// SAVE_MS, one record is written (only on change, so the flash wears only when settings
// change). The write is read back; `err` is set if it does not match.
// SPI mode 0, SCK = clk / 4. WP# is driven high only from the write enable to the end of a
// program or erase, and released otherwise (a design that held WP# high all the time disturbed
// USB programming of the flash on this board, as reported for the NEORV32 port).
//
// Payload (80 bits): {band[2:0], ch[2:0], mode[1:0]}, {low_lat, filter_vcr, 6'b0},
// RSSI min A, max A, min B, max B (16 bits each, MSB first).
`default_nettype none
module flash_store #(
    parameter CLK_HZ = 27_000_000,
    parameter SAVE_MS = 3000,
    parameter [23:0] SECTOR0 = 24'h7FE000
) (
    input  wire        clk,
    input  wire        rst,
    output reg         flash_cs_n,
    output reg         flash_clk,
    output reg         flash_mosi,
    input  wire        flash_miso,
    output reg         flash_wp_drive,     // 1: drive WP# high (the top tristates it otherwise)
    input  wire [79:0] cur,
    output reg  [79:0] loaded,
    output reg         load,               // one clock, after the start scan found a record
    output reg         ready,              // the start scan is over
    output reg         err,                // a write did not read back
    output reg  [15:0] seq                 // sequence number of the newest record (tests)
);
    localparam MS = CLK_HZ / 1000;

    // ---- byte engine: mode 0, 8 bits, SCK = clk / 4
    reg       x_go, x_busy;
    reg [7:0] x_tx, x_rx;
    reg [3:0] x_bit;
    reg [1:0] x_ph;
    always @(posedge clk) begin
        if (x_go && !x_busy) begin x_busy <= 1'b1; x_bit <= 0; x_ph <= 0; flash_mosi <= x_tx[7]; end
        else if (x_busy) begin
            x_ph <= x_ph + 1'b1;
            case (x_ph)
                2'd1: begin flash_clk <= 1'b1; x_rx <= {x_rx[6:0], flash_miso}; end
                2'd3: begin
                    flash_clk <= 1'b0;
                    if (x_bit == 4'd7) x_busy <= 1'b0;
                    else begin x_bit <= x_bit + 1'b1; flash_mosi <= x_tx[6 - x_bit]; end
                end
                default: ;
            endcase
        end
        if (rst) begin x_busy <= 1'b0; flash_clk <= 1'b0; flash_mosi <= 1'b0; end
    end

    function [7:0] crc8_byte(input [7:0] c, input [7:0] d);
        integer k;
        reg [7:0] r;
        begin
            r = c ^ d;
            for (k = 0; k < 8; k = k + 1) r = r[7] ? {r[6:0], 1'b0} ^ 8'h07 : {r[6:0], 1'b0};
            crc8_byte = r;
        end
    endfunction
    function newer(input [15:0] a, input [15:0] b);      // a after b, mod 2^16
        reg [15:0] d;
        begin d = a - b; newer = (d != 0) && !d[15]; end
    endfunction

    // ---- the record being read or written
    reg  [7:0]  rec [0:15];
    reg  [7:0]  crc;
    reg  [12:0] pos;                      // byte in the 8 KB scan, or in a record
    reg  [8:0]  slot;                     // record index 0..511 over both sectors
    reg  [511:0] erased;                  // per slot: all 16 bytes FFh
    reg         r_ff;
    reg         have;
    reg  [8:0]  best_slot, next_slot;
    reg  [15:0] best_seq;
    reg  [79:0] saved;
    reg         need_erase;
    wire [23:0] slot_addr = SECTOR0 + {11'd0, next_slot, 4'd0};
    function [7:0] out_byte(input [3:0] i);
        case (i)
            4'd0: out_byte = 8'hA5; 4'd1: out_byte = seq[15:8]; 4'd2: out_byte = seq[7:0];
            4'd13, 4'd14: out_byte = 8'hFF;
            4'd15: out_byte = crc;
            default: out_byte = saved[(12 - i) * 8 +: 8];         // i = 3..12: payload, MSB first
        endcase
    endfunction

    localparam S_POWER = 5'd0, S_SCAN_CMD = 5'd1, S_SCAN = 5'd2, S_SCAN_END = 5'd3, S_IDLE = 5'd4,
               S_WREN = 5'd5, S_ERASE = 5'd6, S_POLL = 5'd7, S_POLL_RD = 5'd8, S_PROG = 5'd9,
               S_VERIFY = 5'd10, S_GAP = 5'd11, S_CRC = 5'd12, S_DONE = 5'd13;
    reg [4:0]  st, after_poll, after_gap;
    reg [31:0] t;
    reg [2:0]  k;                         // bytes of a command header
    reg [79:0] cur_d;
    reg        prog_phase;                // 0: erase step, 1: program step
    integer    i;

    always @(posedge clk) begin
        x_go <= 1'b0;
        load <= 1'b0;
        cur_d <= cur;
        case (st)
        S_POWER: begin t <= t + 1; if (t == MS) begin t <= 0; st <= S_SCAN_CMD; k <= 0; flash_cs_n <= 1'b0; end end
        S_SCAN_CMD: if (!x_busy && !x_go) begin                    // 03h + address
            if (k == 3'd4) begin st <= S_SCAN; pos <= 0; slot <= 0; crc <= 0; r_ff <= 1'b1; x_tx <= 8'h00; x_go <= 1'b1; end
            else begin
                x_tx <= (k == 0) ? 8'h03 : (k == 1) ? SECTOR0[23:16] : (k == 2) ? SECTOR0[15:8] : SECTOR0[7:0];
                x_go <= 1'b1; k <= k + 1'b1;
            end
        end
        S_SCAN: if (!x_busy && !x_go) begin                        // one byte arrived in x_rx
            rec[pos[3:0]] <= x_rx;
            if (x_rx != 8'hFF) r_ff <= 1'b0;
            if (pos[3:0] != 4'd15) crc <= crc8_byte(crc, x_rx);
            if (pos[3:0] == 4'd15) begin
                erased[slot] <= r_ff && x_rx == 8'hFF;
                if (rec[0] == 8'hA5 && x_rx == crc && (!have || newer({rec[1], rec[2]}, best_seq))) begin
                    have <= 1'b1; best_seq <= {rec[1], rec[2]}; best_slot <= slot;
                    loaded <= {rec[3], rec[4], rec[5], rec[6], rec[7], rec[8], rec[9], rec[10], rec[11], rec[12]};
                end
                crc <= 0; r_ff <= 1'b1; slot <= slot + 1'b1;
            end
            if (pos == 13'h1FFF) begin flash_cs_n <= 1'b1; st <= S_SCAN_END; end
            else begin pos <= pos + 1'b1; x_go <= 1'b1; end
        end
        S_SCAN_END: begin
            ready <= 1'b1;
            if (have) begin
                load <= 1'b1; saved <= loaded; seq <= best_seq;
                // append after the newest record if that slot is erased and in the same sector
                if (best_slot[7:0] != 8'hFF && erased[best_slot + 1'b1]) begin
                    next_slot <= best_slot + 1'b1; need_erase <= 1'b0;
                end else begin next_slot <= {~best_slot[8], 8'd0}; need_erase <= 1'b1; end
            end else begin
                saved <= cur; seq <= 0; next_slot <= 0; need_erase <= 1'b1;
            end
            t <= 0; st <= S_IDLE;
        end
        S_IDLE: begin
            if (cur != cur_d || cur == saved) t <= 0;
            else if (t != SAVE_MS * MS) t <= t + 1;
            else begin                                             // write one record
                saved <= cur; seq <= seq + 1'b1; t <= 0;
                prog_phase <= !need_erase; st <= S_CRC; pos <= 0; crc <= 0;
            end
        end
        S_CRC: begin                                               // CRC over the first 15 bytes
            if (pos[3:0] == 4'd15) begin pos <= 0; flash_wp_drive <= 1'b1; st <= S_WREN; k <= 0; end
            else begin crc <= crc8_byte(crc, out_byte(pos[3:0])); pos <= pos + 1'b1; end
        end
        S_WREN: if (!x_busy && !x_go) begin                        // 06h, alone
            if (k == 0) begin flash_cs_n <= 1'b0; x_tx <= 8'h06; x_go <= 1'b1; k <= 1; end
            else begin flash_cs_n <= 1'b1; k <= 0; after_gap <= prog_phase ? S_PROG : S_ERASE; st <= S_GAP; end
        end
        S_GAP: begin t <= t + 1; if (t == 3) begin t <= 0; st <= after_gap; end end   // CS high between commands
        S_ERASE: if (!x_busy && !x_go) begin                       // 20h + sector address
            if (k == 0) flash_cs_n <= 1'b0;
            if (k == 3'd4) begin flash_cs_n <= 1'b1; k <= 0; after_poll <= S_WREN; prog_phase <= 1'b1; after_gap <= S_POLL; st <= S_GAP; end
            else begin
                x_tx <= (k == 0) ? 8'h20 : (k == 1) ? slot_addr[23:16] : (k == 2) ? {slot_addr[15:12], 4'd0} : 8'h00;
                x_go <= 1'b1; k <= k + 1'b1;
            end
        end
        S_PROG: if (!x_busy && !x_go) begin                        // 02h + address + 16 bytes
            if (k == 0) flash_cs_n <= 1'b0;
            if (k < 3'd4) begin
                x_tx <= (k == 0) ? 8'h02 : (k == 1) ? slot_addr[23:16] : (k == 2) ? slot_addr[15:8] : slot_addr[7:0];
                x_go <= 1'b1; k <= k + 1'b1;
            end else if (pos != 13'd16) begin x_tx <= out_byte(pos[3:0]); x_go <= 1'b1; pos <= pos + 1'b1; end
            else begin flash_cs_n <= 1'b1; k <= 0; pos <= 0; after_poll <= S_VERIFY; after_gap <= S_POLL; st <= S_GAP; end
        end
        S_POLL: if (!x_busy && !x_go) begin                        // 05h until not busy
            if (k == 0) begin flash_cs_n <= 1'b0; x_tx <= 8'h05; x_go <= 1'b1; k <= 1; end
            else if (k == 1) begin x_tx <= 8'h00; x_go <= 1'b1; k <= 2; end
            else begin
                flash_cs_n <= 1'b1; k <= 0;
                if (x_rx[0]) begin after_gap <= S_POLL; st <= S_GAP; end
                else begin
                    after_gap <= after_poll; st <= S_GAP;
                    if (after_poll == S_VERIFY) flash_wp_drive <= 1'b0;
                end
            end
        end
        S_VERIFY: if (!x_busy && !x_go) begin                      // read the record back
            if (k == 0) flash_cs_n <= 1'b0;
            if (k < 3'd4) begin
                x_tx <= (k == 0) ? 8'h03 : (k == 1) ? slot_addr[23:16] : (k == 2) ? slot_addr[15:8] : slot_addr[7:0];
                x_go <= 1'b1; k <= k + 1'b1;
            end else if (k == 3'd4) begin x_tx <= 8'h00; x_go <= 1'b1; k <= 3'd5; pos <= 0; end
            else begin
                if (x_rx != out_byte(pos[3:0])) err <= 1'b1;
                if (pos == 13'd15) begin flash_cs_n <= 1'b1; k <= 0; st <= S_DONE; end
                else begin pos <= pos + 1'b1; x_go <= 1'b1; end
            end
        end
        S_DONE: begin
            need_erase <= (next_slot[7:0] == 8'hFF);
            next_slot <= (next_slot[7:0] == 8'hFF) ? {~next_slot[8], 8'd0} : next_slot + 1'b1;
            t <= 0; st <= S_IDLE;
        end
        default: st <= S_POWER;
        endcase
        if (rst) begin
            st <= S_POWER; t <= 0; flash_cs_n <= 1'b1; flash_wp_drive <= 1'b0; ready <= 1'b0; load <= 1'b0;
            err <= 1'b0; have <= 1'b0; seq <= 0; k <= 0; x_go <= 1'b0; loaded <= 0;
        end
    end
endmodule
`default_nettype wire
