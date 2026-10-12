// Self-running testbench for fb_backend with the behavioural SDRAM: source
// lines from a file (when each starts, field bit, line number, a tag for its
// contents) are sent as 360 tagged words at one word per cycle, the way the
// mixer sends them. Every decision of the field store and what the display
// reads is written to text files. Driven by sim/test_fb.py.
//
// Word contents: {0, tag[11:0], line[9:0], idx[8:0]}, so that a line read back
// can be recognised whole.
`timescale 1ns/1ps
`default_nettype none
module tb_fb;
    parameter N_LINES = 1;                    // entries in lines.hex
    parameter LL = 0;                         // 1: low-latency mode (the mode at reset)
    parameter SW1 = 0, SW2 = 0, SW3 = 0;      // SDRAM clock cycle at which ll_mode goes to 1 / to 0 / to 1 (0 = never)
    parameter FAULT = 0;                      // bit mask of test-bench side faults for negative controls (test_fb.py):
                                              // bit 0: one source word of field FAULT_TAG carries a wrong tag
                                              // bit 1: the observed r has an X for one pixel clock at pixel clock FAULT_PC
                                              // bit 2: the observed vsync gets a spurious extra pulse at pixel clock FAULT_PC2
    parameter FAULT_TAG = 0, FAULT_PC = 0, FAULT_PC2 = 0;
    parameter V_TOTAL = 40, V_ACTIVE = 36, V_FP = 1, V_SYNC = 1;
    parameter BOB = 1, RT_EN = 1, RT_NTSC = 4, RT_PAL = 44, RT_HYST = 16, RT_SPLIT = 270, LL_EQ = 1;
    parameter JUMP_AFTER = 3, HOLD = 32, WAIT_BEFORE_VSYNC = 0;
    parameter VINTERP = 0;                    // fb_display.v: blend two source lines (BUF)
    parameter LOGPX = 0;                      // 1: log the words and YCbCr of one pixel per line (as VINTERP does)
    parameter real T_S = 15.4, T_P = 13.4;
    parameter real TAIL = 2000000.0;          // ns to run after the last line

    reg sd_clk = 0, pix_clk = 0, rst = 1;
    always #(T_S / 2) sd_clk = ~sd_clk;
    always #(T_P / 2) pix_clk = ~pix_clk;
    // SDRAM clock as from clocks_sdram.v: sd_clk shifted 225 degrees
    reg sd_clk_shift = 0;
    always @(sd_clk) sd_clk_shift <= #(0.625 * T_S) sd_clk;

    // ll_mode as the DUT sees it: set at reset, switched by cycle count (SDRAM clock, so it is
    // synchronous to the SDRAM domain and asynchronous to the pixel domain, as the real one)
    reg ll_mode_r = (LL != 0);
    wire ll_any = ll_mode_r;
    always @(posedge sd_clk) begin
        if (SW1 != 0 && cyc == SW1) ll_mode_r <= 1'b1;
        if (SW2 != 0 && cyc == SW2) ll_mode_r <= 1'b0;
        if (SW3 != 0 && cyc == SW3) ll_mode_r <= 1'b1;
    end

    // ---- source: lines.hex entries {start cycle[31:0], field, line[9:0], tag[11:0]}
    reg [54:0] src [0:N_LINES-1];
    reg [51:0] fifo [0:4095];
    reg [11:0] wp = 0, rp = 0;
    wire        f_empty = (wp == rp);
    wire [51:0] f_data  = fifo[rp];
    wire        f_pop;
    integer cyc = 0, li = 0, wi = 360;
    wire [54:0] e = src[li];
    always @(posedge sd_clk) begin
        cyc <= cyc + 1;
        if (f_pop && !f_empty) rp <= rp + 1'b1;
        if (!rst && sdram_ready) begin
            if (wi < 360) begin
                fifo[wp] <= {e[22], e[21:12], wi[8:0], 1'b0,
                             (FAULT[0] && e[11:0] == FAULT_TAG && e[21:12] == 3 && wi == 52) ? e[11:0] ^ 12'h40 : e[11:0],
                             e[21:12], wi[8:0]};
                wp <= wp + 1'b1;
                wi <= wi + 1;
                if (wi == 359) li <= li + 1;
            end else if (li < N_LINES && cyc >= e[54:23]) wi <= 0;
        end
    end

    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    wire [7:0] r, g, b, yo, cbo, cro;
    wire [11:0] tx, ty;
    wire de, hsync, vsync, have_video, sdram_ready;
    fb_backend #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .V_FP(V_FP), .V_SYNC(V_SYNC), .SDRAM_FREQ(5_000_000),
                 .BOB(BOB), .RT_EN(RT_EN), .RT_NTSC(RT_NTSC), .RT_PAL(RT_PAL), .RT_HYST(RT_HYST), .RT_SPLIT(RT_SPLIT),
                 .LL_EQ(LL_EQ), .JUMP_AFTER(JUMP_AFTER), .HOLD(HOLD), .VINTERP(VINTERP),
                 .WAIT_BEFORE_VSYNC(WAIT_BEFORE_VSYNC)) dut (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(pix_clk), .rst_async(rst), .ll_mode(ll_mode_r),
        .f_empty(f_empty), .f_data(f_data), .f_pop(f_pop),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hsync), .vsync(vsync), .yo(yo), .cbo(cbo), .cro(cro), .tx(tx), .ty(ty),
        .have_video(have_video), .sdram_ready(sdram_ready));
    // As in tb_m2.v: SDRAM_FREQ above shortens the controller's power-up wait, so the model is told 15 us;
    // refresh is checked over 8 refreshes; STRICT ends the simulation at the first protocol error.
    sdram_model #(.AW(21), .T_PWRUP_PS(15_000_000), .REF_WINDOW(8), .STRICT(1)) mem (
        .clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
        .ba(ba), .a(a), .dqm(dqm), .dq(dq));

    // ---- SDRAM domain log. Order within a cycle: what the display asked and was told,
    // then what the writer did (the model replays the lines in this order).
    integer fs, fp;
    reg        look3_d = 0, w_have = 0, w_f, trig_d = 0;
    reg [9:0]  w_line;
    reg        rd_bad;
    always @(posedge sd_clk) if (!rst && (dut.fb.resetn || ll_any)) begin
        if (dut.fb.first)
            $fwrite(fs, "D %0d %0d %0d %0d %0d %0d\n", dut.fb.s_dec, dut.fb.p_dec, dut.fb.pok_dec,
                    dut.fb.d_cur ? dut.fb.ph_low : dut.fb.low_of[dut.fb.latest], dut.fb.rt_now, cyc);
        // a line stored at this edge is seen by a request accepted at the same edge, but not by the frame decision
        if (dut.fb.stored) $fwrite(fs, "M %0d\n", dut.fb.grp_line);
        if (dut.fb.accept) $fwrite(fs, "F %0d\n", dut.fb.fetch_line);
        look3_d <= dut.fb.look == 2'd3;
        if (look3_d && dut.fb.f_blank) $fwrite(fs, "S blank %0d\n", dut.fb.f_src);
        else if (look3_d) $fwrite(fs, "S %0d %0d\n", dut.fb.f_buf, dut.fb.f_src);
        if (dut.fb.first_word) $fwrite(fs, "A %0d %0d %0d\n", dut.fb.e_field, dut.fb.e_line, dut.fb.cur_buf);
        if (dut.fb.discard) $fwrite(fs, "J %0d %0d %0d\n", dut.fb.e_field, dut.fb.e_line, dut.fb.nxt);
        if (dut.fb.publish)
            $fwrite(fs, "N %0d %0d %0d %0d %0d\n", dut.fb.e_field, dut.fb.e_line, dut.fb.cur_buf, dut.fb.n_now, dut.fb.nxt);
        if (dut.fb.pub_valid) $fwrite(fs, "P %0d\n", dut.fb.pub_lines);
        if (dut.fb.take && (!w_have || w_f != dut.fb.e_field || w_line != dut.fb.e_line)) begin
            $fwrite(fs, "W %0d %0d %0d %0d\n", dut.fb.e_field, dut.fb.e_line, dut.fb.e_idx, cyc);
            w_have <= 1; w_f <= dut.fb.e_field; w_line <= dut.fb.e_line;
        end
        // a line read from the SDRAM into the line buffer: tag and line of its first word,
        // and whether all 360 words belonged to that line; or a black line, and whether all
        // 360 words were black
        if (dut.fb.lb_we) begin
            if (dut.fb.lb_addr[8:0] == 0) rd_bad = 0;
            if (dut.fb.f_blank) begin
                if (dut.fb.lb_data !== 32'h10801080) rd_bad = 1;
                if (dut.fb.lb_addr[8:0] == 359) $fwrite(fs, "R blank blank %0d %0d\n", dut.fb.lb_addr[10:9], rd_bad);
            end else begin
                if (dut.fb.lb_data[8:0] != dut.fb.lb_addr[8:0] || dut.fb.lb_data[18:9] != dut.fb.f_src) rd_bad = 1;
                if (dut.fb.lb_addr[8:0] == 359)
                    $fwrite(fs, "R %0d %0d %0d %0d\n", dut.fb.lb_data[30:19], dut.fb.lb_data[18:9], dut.fb.lb_addr[10:9], rd_bad);
            end
        end
        // low-latency mode: field starts, lines completed and frame triggers
        if (dut.ll_take && (!dut.ll_have || dut.ll_new_field)) $fwrite(fs, "G\n");
        if (dut.ll_end) $fwrite(fs, "E %0d %0d %0d %0d\n", dut.e_field, dut.e_line, cyc, dut.ll_fire);
        trig_d <= dut.s_ll_trig;
        if (trig_d != dut.s_ll_trig) $fwrite(fs, "T %0d %0d %0d\n", cyc, dut.s_ll_low, dut.s_ll_lines);
    end

    // ---- pixel domain log: frame geometry, source line per output line, what is on the line
    integer pc = 0;
    reg [11:0] xs;
    always @(posedge pix_clk) begin
        pc <= pc + 1;
        if (!rst) begin
            if (dut.x == 0 && dut.y == V_TOTAL - 1) $fwrite(fp, "L %0d\n", pc);            // a line of the frame-start row begins
            if (dut.x == 1 && dut.y == 0) $fwrite(fp, "V %0d %0d %0d\n", pc, dut.disp.lines, dut.disp.have_video);   // x = 1: have_video is decided at x = 0
            if (dut.x == 4 && dut.y == 0) $fwrite(fp, "B %0d\n", dut.disp.low_r);
            if (dut.x == 300 && dut.y < V_ACTIVE) $fwrite(fp, "Y %0d %0d\n", dut.y, dut.disp.src_cur);
            // the word read for source pixel 104/105 (x = 300 is window pixel 140, source pixel 105)
            if (dut.x == 302 && dut.y < V_ACTIVE)
                $fwrite(fp, "X %0d %0d %0d %0d\n", dut.y, dut.lb_rdata[30:19], dut.lb_rdata[18:9], dut.lb_rdata[8:0]);
            // VINTERP: the second line and the weight of the output line; for window pixel 136 (x = 296,
            // source pixel 102, an even one: Y0 = bits 15:8) the two words read and the YCbCr put out, which
            // is registered 6 clocks after x (yo is sampled here before the edge that would replace it)
            if (VINTERP != 0 && dut.x == 300 && dut.y < V_ACTIVE)
                $fwrite(fp, "I %0d %0d %0d\n", dut.y, dut.disp.src_b_cur, dut.disp.w_cur);
            if (VINTERP != 0 && dut.x == 302 && dut.y < V_ACTIVE)
                $fwrite(fp, "X2 %0d %0d %0d %0d\n", dut.y, dut.lb_rdata_b[30:19], dut.lb_rdata_b[18:9], dut.lb_rdata_b[8:0]);
            if ((VINTERP != 0 || LOGPX != 0) && dut.x == 298 && dut.y < V_ACTIVE)
                $fwrite(fp, "W %0d %08x %08x\n", dut.y, dut.lb_rdata, dut.lb_rdata_b);
            if ((VINTERP != 0 || LOGPX != 0) && dut.x == 302 && dut.y < V_ACTIVE)
                $fwrite(fp, "O %0d %0d %0d %0d\n", dut.y, yo, cbo, cro);
        end
    end

    // mode switches, vsync starts and lines with an X/Z on an output (observed outputs; the
    // faults 2 and 3 corrupt only what is observed here, never the DUT)
    reg        vs_d = 0, bad_line = 0;
    reg  [1:0] m_d = 0;
    wire       vs_obs = (FAULT[2] && pc >= FAULT_PC2 && pc < FAULT_PC2 + 40) ? 1'b1 : vsync;
    wire [7:0] r_obs  = (FAULT[1] && pc == FAULT_PC) ? 8'bx : r;
    always @(posedge pix_clk) if (!rst) begin
        m_d <= {m_d[0], ll_mode_r};
        if (m_d[1] != m_d[0]) $fwrite(fp, "M %0d %0d\n", pc, m_d[0]);
        vs_d <= vs_obs;
        if (vs_obs && !vs_d) $fwrite(fp, "S %0d\n", pc);
        if ((^{r_obs, g, b, de, hsync, vs_obs}) === 1'bx) bad_line <= 1'b1;
        if (dut.x == 0) begin
            if (bad_line) $fwrite(fp, "Z %0d\n", pc);
            bad_line <= 1'b0;
        end
    end

    initial begin
        $readmemh("lines.hex", src);
        fs = $fopen("sd.txt", "w");
        fp = $fopen("pix.txt", "w");
        #500 rst = 0;
        wait (li == N_LINES);
        #(TAIL);
        $fwrite(fs, "end %0d\n", mem.errors);
        $fclose(fs); $fclose(fp);
        $finish;
    end
    // margins the formal proofs leave open (formal/README.md, items 4 and 5), see margin_checks.vh
`define MC_BE dut
`include "margin_checks.vh"
`undef MC_BE
endmodule
`default_nettype wire
