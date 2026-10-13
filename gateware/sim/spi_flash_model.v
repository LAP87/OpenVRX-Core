// Behavioural SPI NOR flash (mode 0, single I/O) for the settings store (flash_store.v):
// the standard command set that openFPGALoader uses for the Tang Nano 20K's XTX XT25F64F
// (src/spiFlash.cpp): 03h read, 06h write enable, 04h write disable, 05h status (bit 0 busy,
// bit 1 write enabled), 02h page program (256-byte page, the address wraps inside the page),
// 20h 4 KB sector erase. Program and erase need WEL, clear it, and keep the chip busy for
// T_PP_NS / T_SE_NS; commands other than 05h are ignored while busy. Programming only clears
// bits (1 -> 0), as in NOR flash: programming a byte that is not erased leaves the AND of old
// and new, and `dirty_programs` counts such bytes. WP# low during a program or erase blocks
// it (a protected chip; the store must drive WP# high when it writes).
//
// Only the top MEM_BYTES of the 8 MB array are modelled (the settings sectors); reads below
// that return FFh. mem.hex (MEM_BYTES bytes) is loaded at start if LOAD = 1, and the testbench
// dumps the array with dump().
`timescale 1ns/1ps
module spi_flash_model #(
    parameter MEM_BYTES = 8192,
    parameter LOAD = 0,
    parameter real T_PP_NS = 400_000.0,       // 0.4 ms (typical, distributor summary of XT25F64F)
    parameter real T_SE_NS = 65_000_000.0     // 65 ms
) (
    input  wire cs_n,
    input  wire clk,
    input  wire mosi,
    output reg  miso,
    input  wire wp_n
);
    localparam [23:0] BASE = 24'h800000 - MEM_BYTES;
    reg [7:0] mem [0:MEM_BYTES-1];
    reg [7:0] cmd, sh, out;
    reg [23:0] addr, e_addr;
    integer nbit, nbyte, i;
    reg wel, busy;
    integer programs, erases, dirty_programs, blocked;
    integer erase_count [0:15];

    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1) mem[i] = 8'hFF;
        if (LOAD) $readmemh("mem.hex", mem);
        wel = 0; busy = 0; miso = 1'bz; programs = 0; erases = 0; dirty_programs = 0; blocked = 0;
        for (i = 0; i < 16; i = i + 1) erase_count[i] = 0;
    end
    function [7:0] rd(input [23:0] a);
        rd = (a >= BASE) ? mem[a - BASE] : 8'hFF;
    endfunction

    task dump;
        integer fd, k;
        begin
            fd = $fopen("mem_out.hex", "w");
            for (k = 0; k < MEM_BYTES; k = k + 1) $fwrite(fd, "%02x\n", mem[k]);
            $fclose(fd);
        end
    endtask

    always @(negedge cs_n) begin nbit = 0; nbyte = 0; cmd = 8'h00; miso = 1'bz; end
    always @(posedge cs_n) begin
        miso = 1'bz;
        if (nbit == 0 && nbyte >= 1 && !busy) begin
            if (cmd == 8'h06) wel = 1;
            if (cmd == 8'h04) wel = 0;
            if (cmd == 8'h20 && nbyte == 4) begin
                if (!wel) ;
                else if (wp_n !== 1'b1) begin blocked = blocked + 1; wel = 0; end
                else begin
                    erases = erases + 1; wel = 0; busy = 1;
                    e_addr = {addr[23:12], 12'd0};          // later commands (status polls) must not move it
                    if (e_addr >= BASE) erase_count[(e_addr - BASE) >> 12] = erase_count[(e_addr - BASE) >> 12] + 1;
                    #(T_SE_NS);
                    for (i = 0; i < 4096; i = i + 1)
                        if (e_addr + i >= BASE) mem[e_addr + i - BASE] = 8'hFF;
                    busy = 0;
                end
            end
        end
    end
    // page program data is taken byte by byte below; the busy time starts when CS rises
    reg pp_active;
    always @(posedge cs_n) if (pp_active) begin
        pp_active = 0;
        busy = 1; #(T_PP_NS); busy = 0;
    end

    always @(posedge clk) if (!cs_n) begin
        sh = {sh[6:0], mosi};
        nbit = nbit + 1;
        if (nbit == 8) begin
            nbit = 0;
            if (nbyte == 0) begin
                cmd = sh;
                if (busy && cmd != 8'h05) cmd = 8'h00;     // ignored while busy
            end else if (nbyte <= 3 && (cmd == 8'h03 || cmd == 8'h02 || cmd == 8'h20)) addr = {addr[15:0], sh};
            else if (cmd == 8'h02 && nbyte >= 4) begin
                if (nbyte == 4) begin
                    if (!wel) cmd = 8'h00;
                    else if (wp_n !== 1'b1) begin blocked = blocked + 1; wel = 0; cmd = 8'h00; end
                    else begin wel = 0; pp_active = 1; programs = programs + 1; end
                end
                if (cmd == 8'h02) begin
                    if (addr >= BASE) begin
                        if (mem[addr - BASE] != 8'hFF) dirty_programs = dirty_programs + 1;
                        mem[addr - BASE] = mem[addr - BASE] & sh;
                    end
                    addr = {addr[23:8], addr[7:0] + 8'd1};    // wraps inside the page
                end
            end
            nbyte = nbyte + 1;
        end
    end
    // output on the falling edge: read data, status
    always @(negedge clk) if (!cs_n) begin
        if (cmd == 8'h03 && nbyte >= 4) begin
            if (nbit == 0) begin out = rd(addr); addr = addr + 1; end
            miso = out[7 - nbit];
        end else if (cmd == 8'h05 && nbyte >= 1) begin
            out = {6'd0, wel, busy};
            miso = out[7 - nbit];
        end
    end
endmodule
