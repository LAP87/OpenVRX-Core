// Focused line-buffer initialization and display-input bench for fb_backend.
// LOW words use the public mixer input; BUF words use controlled fb_sdram
// outputs so both writers exercise the shared RAM and sticky coverage tracker.
`timescale 1ns/1ps
`default_nettype none
module tb_ll_ring;
    reg sd_clk = 0, pix_clk = 0, rst = 1;
    always #5 sd_clk = ~sd_clk;
    initial begin #2; forever #4 pix_clk = ~pix_clk; end
    reg sd_clk_shift = 0;
    always @(sd_clk) sd_clk_shift <= #(6.25) sd_clk;

    reg ll_mode = 0;
    reg f_empty = 1;
    reg [51:0] f_data = 0;
    wire f_pop;
    tri [31:0] dq;
    wire [10:0] a;
    wire [1:0] ba;
    wire [3:0] dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    wire [7:0] r, g, b, yo, cbo, cro;
    wire [11:0] tx, ty;
    wire de, hsync, vsync, have_video, sdram_ready;

    fb_backend #(.V_TOTAL(87), .V_ACTIVE(72), .V_FP(1), .V_SYNC(1), .SDRAM_FREQ(5_000_000),
                 .RT_EN(1), .RT_NTSC(4), .RT_PAL(8), .RT_HYST(2), .RT_SPLIT(26)) dut (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(pix_clk), .rst_async(rst), .ll_mode(ll_mode),
        .f_empty(f_empty), .f_data(f_data), .f_pop(f_pop),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hsync), .vsync(vsync), .yo(yo), .cbo(cbo), .cro(cro), .tx(tx), .ty(ty),
        .have_video(have_video), .sdram_ready(sdram_ready));

    integer fd;
    integer accepted = 0;
    reg probe_active = 0;
    reg [12:0] pixel_address;
    reg pixel_low, pixel_reset, pixel_probe;
    real pixel_edge_ns;
    always @(posedge sd_clk) if (!rst && dut.lbw_we) begin
        $fwrite(fd, "W %.1f %0d %08x\n", $realtime, dut.lbw_addr, dut.lbw_data);
        accepted = accepted + 1;
    end
    always @(posedge pix_clk) if (!rst) begin
        pixel_edge_ns = $realtime;
        pixel_address = dut.lb_raddr;
        pixel_low = dut.ll_p;
        pixel_reset = dut.prst;
        pixel_probe = probe_active;
        #1;
        $fwrite(fd, "P %.1f %0d %08x %08x %0d %0d %0d\n", pixel_edge_ns, pixel_address,
                dut.lb_rdata, dut.disp.lb_rdata, pixel_low, pixel_reset, pixel_probe);
    end

    task probe(input [12:0] address);
        begin
            @(negedge pix_clk);
            force dut.lb_raddr = address;
            probe_active = 1;
            @(posedge pix_clk);
            #2;
            probe_active = 0;
            @(negedge pix_clk);
            release dut.lb_raddr;
        end
    endtask

    task write_buf_word(input [1:0] slot, input [8:0] index, input [31:0] data);
        begin
            @(negedge sd_clk);
            force dut.lb_we = 1'b1;
            force dut.lb_waddr = {slot, index};
            force dut.lb_wdata = data;
            @(posedge sd_clk);
            #1;
            release dut.lb_we;
            release dut.lb_waddr;
            release dut.lb_wdata;
        end
    endtask

    task write_low_word(input [9:0] line, input [8:0] index, input [31:0] data);
        begin
            @(negedge sd_clk);
            f_empty = 0;
            f_data = {1'b0, line, index, data};
            @(posedge sd_clk);
            if (!dut.lbw_we) $fatal(1, "LOW word %0d was not accepted", index);
            #1;
        end
    endtask

    integer i;
    initial begin
        fd = $fopen("ll_ring.txt", "w");
        if (fd == 0) $fatal(1, "could not open ll_ring.txt");
        $fwrite(fd, "RESET %.1f\n", $realtime);
        #100 rst = 0;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);

        // Every virgin ring slot is black even though the RAM has no reset value.
        ll_mode = 1;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        for (i = 0; i < 16; i = i + 1)
            probe(i[3:0] * 13'd512 + 13'd52);

        // Initialize physical BUF slot 2. This history must remain visible in LOW.
        ll_mode = 0;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        for (i = 0; i < 360; i = i + 1)
            write_buf_word(2, i[8:0], 32'hB2000000 + i);
        ll_mode = 1;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        probe(13'd2 * 13'd512 + 13'd0);
        probe(13'd2 * 13'd512 + 13'd52);
        probe(13'd2 * 13'd512 + 13'd359);

        // A LOW field entered mid-line and ending at 359 is still not a full slot line.
        for (i = 53; i < 360; i = i + 1)
            write_low_word(10'd25, i[8:0], 32'hA5000000 + i);
        @(negedge sd_clk);
        f_empty = 1;
        repeat (5) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd52);

        // Pause after accepted index 358, then observe before index 359 arrives.
        for (i = 0; i <= 358; i = i + 1) begin
            write_low_word(10'd25, i[8:0], 32'hA5000000 + i);
            if (i == 358) begin
                @(negedge sd_clk);
                f_empty = 1;
                repeat (5) @(posedge pix_clk);
                probe(13'd9 * 13'd512 + 13'd52);
            end
        end
        write_low_word(10'd25, 9'd359, 32'hA5000000 + 359);
        @(negedge sd_clk);
        f_empty = 1;
        repeat (5) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd0);
        probe(13'd9 * 13'd512 + 13'd52);
        probe(13'd9 * 13'd512 + 13'd359);

        // Missing lines and later partial writes preserve slot validity and the last word.
        repeat (5) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd52);
        write_low_word(10'd25, 9'd52, 32'hD5000052);
        @(negedge sd_clk);
        f_empty = 1;
        repeat (5) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd52);

        // Mode changes preserve the shared RAM and initialized history.
        ll_mode = 0;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        ll_mode = 1;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd52);

        // Global reset clears validity but does not clear the dual-clock RAM.
        rst = 1;
        $fwrite(fd, "RESET %.1f\n", $realtime);
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        rst = 0;
        repeat (6) @(posedge sd_clk);
        repeat (6) @(posedge pix_clk);
        probe(13'd9 * 13'd512 + 13'd52);
        probe(13'd2 * 13'd512 + 13'd52);

        $fwrite(fd, "END %0d\n", accepted);
        $fclose(fd);
        $finish;
    end
endmodule
`default_nettype wire
