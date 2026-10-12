// Self-running testbench for the picture chain of M4 (top/m4_dual_mix.v without
// the I2C, the PLLs and TMDS): two BT.656 byte streams, each on its own clock,
// -> mixer2 -> fb_backend (field store with the behavioural SDRAM, or the
// low-latency ring) -> the display's pixels. Decoder status (ext_bad) and
// ll_mode come from a control file, by SDRAM clock cycle. Everything the checks
// in sim/test_fuzz_chain.py need is written to three text files:
//   mix.txt  mixer clock domain: line markers leaving the capture FIFOs, the
//            noise meter's line counts, mixer decisions, words the back end takes
//   sd.txt   SDRAM clock domain (the same clock): the field store's decisions as
//            in tb_fb.v, every word written to the SDRAM, an accepted-read marker and checksum
//            for every line loaded into the line buffer, the low-latency writer
//   pix.txt  pixel clock domain: frame geometry, the source line and word shown on
//            every output line, optional bound LOW-gate probe, vsync, X/Z on the outputs
`timescale 1ns/1ps
`default_nettype none
module tb_chain;
    parameter N_A = 1, N_B = 1, N_CTL = 1;    // stream lengths (bytes), control entries
    parameter real T_A = 37.0, T_B = 37.0, T_S = 15.4, T_P = 13.4;
    parameter real START_A = 600000.0, START_B = 600000.0;   // ns after reset
    parameter LL = 0;                         // ll_mode at reset
    parameter V_TOTAL = 87, V_ACTIVE = 72, V_FP = 1, V_SYNC = 1;
    parameter RT_EN = 1, RT_NTSC = 4, RT_PAL = 8, RT_HYST = 2, RT_SPLIT = 26;
    parameter T_PAIR = 1024, N_STEP = 8, N_DEAD = 40;
    parameter real TAIL = 1500000.0;          // ns to run after both streams end
    parameter real DRAIN_SAFE_TIMEOUT_NS = 30000000.0;
    parameter integer DRAIN_MAX_CYCLES = 4096, DRAIN_STABLE_CYCLES = 4;
    parameter DRAIN_STALL_READ = 0;             // negative-control hook; never enabled in normal runs
    parameter integer GATE_PROBE = 0;             // 0: off, 1: alive-low, 2: trigger-low

    reg a_clk = 0, b_clk = 0, sd_clk = 0, pix_clk = 0, rst = 1;
    reg pix_run = 1, pix_frozen = 0, drain_stall_armed = 0;
    reg gate_probe_pending = 0, gate_probe_done = 0;
    integer gate_probe_frame_pc = 0;
    reg [1:0] gate_probe_kind = 0;
    reg gate_probe_original_alive = 0, gate_probe_original_triggered = 0;
    always #(T_A / 2) a_clk = ~a_clk;
    always #(T_B / 2) b_clk = ~b_clk;
    always #(T_S / 2) sd_clk = ~sd_clk;
    always #(T_P / 2) if (pix_run) pix_clk = ~pix_clk;
    reg sd_clk_shift = 0;                     // as clocks_sdram.v: 225 degrees after sd_clk
    always @(sd_clk) sd_clk_shift <= #(0.625 * T_S) sd_clk;

    // ---- the two decoders' byte streams (as tb_mixer.v)
    reg [7:0] mem_a [0:N_A-1];
    reg [7:0] mem_b [0:N_B-1];
    reg [7:0] a_d = 8'h80, b_d = 8'h80;
    integer ia = 0, ib = 0;
    reg run_a = 0, run_b = 0;
    always @(negedge a_clk) if (run_a) begin
        if (ia < N_A) begin a_d <= mem_a[ia]; ia <= ia + 1; end else a_d <= 8'h80;
    end
    always @(negedge b_clk) if (run_b) begin
        if (ib < N_B) begin b_d <= mem_b[ib]; ib <= ib + 1; end else b_d <= 8'h80;
    end

    // ---- control: {cycle[31:0], kind[1:0], value}; kind 0 ext_bad A, 1 ext_bad B, 2 ll_mode.
    // One entry per cycle at most; the cycle is the SDRAM clock count before the edge.
    reg [34:0] ctl [0:N_CTL-1];
    integer ci = 0, cyc = 0;
    reg ext_a = 0, ext_b = 0, ll_r = (LL != 0);
    always @(posedge sd_clk) begin
        cyc <= cyc + 1;
        if (ci < N_CTL && ctl[ci][34:3] == cyc) begin
            case (ctl[ci][2:1])
                2'd0: ext_a <= ctl[ci][0];
                2'd1: ext_b <= ctl[ci][0];
                default: ll_r <= ctl[ci][0];
            endcase
            ci <= ci + 1;
        end
    end

    // ---- the chain, wired as in m4_dual_mix.v
    wire        m_empty, m_pop, a_lines, b_lines, alive_a, alive_b, cur, overflow;
    wire [51:0] m_data;
    wire        dec_valid, dec_field;
    wire [1:0]  dec_use, dec_pop;
    wire [9:0]  dec_line;
    mixer2 #(.T_PAIR(T_PAIR), .N_STEP(N_STEP), .N_DEAD(N_DEAD)) mix (
        .a_clk(a_clk), .a_d(a_d), .b_clk(b_clk), .b_d(b_d), .sys_clk(sd_clk), .rst_async(rst),
        .ext_bad_a(ext_a), .ext_bad_b(ext_b),
        .out_empty(m_empty), .out_data(m_data), .out_pop(m_pop),
        .a_lines(a_lines), .b_lines(b_lines), .alive_a(alive_a), .alive_b(alive_b), .cur(cur),
        .overflow(overflow), .dec_valid(dec_valid), .dec_use(dec_use), .dec_pop(dec_pop),
        .dec_field(dec_field), .dec_line(dec_line),
        .snow_a(), .snow_b(), .use_a(), .use_b(), .use_mix(), .snow_toggle_a(), .snow_toggle_b(), .use_toggle(),
        .noise_a(), .noise_b(), .noise_toggle_a(), .noise_toggle_b());

    wire [31:0] dq;
    wire [10:0] a;
    wire [1:0]  ba;
    wire [3:0]  dqm;
    wire ncs, nwe, nras, ncas, sclk, cke;
    wire [7:0] r, g, b, yo, cbo, cro;
    wire [11:0] tx, ty;
    wire de, hsync, vsync, have_video, sdram_ready;
    fb_backend #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .V_FP(V_FP), .V_SYNC(V_SYNC), .SDRAM_FREQ(5_000_000),
                 .RT_EN(RT_EN), .RT_NTSC(RT_NTSC), .RT_PAL(RT_PAL), .RT_HYST(RT_HYST), .RT_SPLIT(RT_SPLIT)) be (
        .sd_clk(sd_clk), .sd_clk_shift(sd_clk_shift), .pix_clk(pix_clk), .rst_async(rst), .ll_mode(ll_r),
        .f_empty(m_empty), .f_data(m_data), .f_pop(m_pop),
        .SDRAM_DQ(dq), .SDRAM_A(a), .SDRAM_BA(ba), .SDRAM_nCS(ncs), .SDRAM_nWE(nwe), .SDRAM_nRAS(nras),
        .SDRAM_nCAS(ncas), .SDRAM_CLK(sclk), .SDRAM_CKE(cke), .SDRAM_DQM(dqm),
        .r(r), .g(g), .b(b), .de(de), .hsync(hsync), .vsync(vsync), .yo(yo), .cbo(cbo), .cro(cro), .tx(tx), .ty(ty),
        .have_video(have_video), .sdram_ready(sdram_ready));
    // Stop only at vertical blank after the fixed tail. This freezes new pixel fetches while
    // leaving the SDRAM clock running to finish every request already in the CDC/arbiter/burst path.
    wire drain_idle = !be.fetch_ev && !be.s_fetch_req && be.fb.look == 2'd0 &&
                      !be.fb.fetching && !be.fb.rd_inflight && !be.req_valid &&
                      !be.fb.grp_ready && !be.fb.writing && be.fb.grp_mask == 8'd0 &&
                      be.sdram.state == 3'd2;     // sdram_burst.IDLE
    // Arm the stall only on an actual accepted nonblank read, before blanking can freeze pixels.
    // This makes the native deadlock negative exercise the same pending-read state as EOF checks.
    always @(posedge sd_clk) if (!rst && DRAIN_STALL_READ && !drain_stall_armed &&
                                  be.fb.req_valid && be.fb.req_ready && !be.fb.req_write) begin
        force be.rdata_valid = 1'b0;
        drain_stall_armed = 1'b1;
    end
    // as tb_fb.v: the controller's power-up wait is shortened, the model is told 15 us;
    // STRICT ends the simulation at the first protocol error (then sd.txt has no "end" line)
    sdram_model #(.AW(21), .T_PWRUP_PS(15_000_000), .REF_WINDOW(8), .STRICT(1)) mem (
        .clk(sclk), .cke(cke), .ncs(ncs), .nras(nras), .ncas(ncas), .nwe(nwe),
        .ba(ba), .a(a), .dqm(dqm), .dq(dq));

    integer fm, fs, fp;
    integer drain_cycles, drain_stable;

    // ---- mixer domain log
    integer npop = 0;                         // words the back end has taken from the mixer
    reg ov_d = 0;
    always @(posedge sd_clk) if (!rst) begin
        if (mix.ch_a.in_pop && mix.ch_a.in_data[52])
            $fwrite(fm, "K 0 %0d %0d %0d %0d %0d %0d %0d %0d %0d\n", cyc, mix.ch_a.in_data[51], mix.ch_a.in_data[50:41],
                    mix.ch_a.complete, mix.ch_a.mark, mix.ch_a.in_data[40:21], mix.ch_a.in_data[20:17],
                    mix.ch_a.in_data[16:13], mix.ch_a.in_data[12:1]);
        if (mix.ch_b.in_pop && mix.ch_b.in_data[52])
            $fwrite(fm, "K 1 %0d %0d %0d %0d %0d %0d %0d %0d %0d\n", cyc, mix.ch_b.in_data[51], mix.ch_b.in_data[50:41],
                    mix.ch_b.complete, mix.ch_b.mark, mix.ch_b.in_data[40:21], mix.ch_b.in_data[20:17],
                    mix.ch_b.in_data[16:13], mix.ch_b.in_data[12:1]);
        if (mix.noise_a_st.line_valid)
            $fwrite(fm, "N 0 %0d %0d %0d\n", mix.noise_a_st.line_field, mix.noise_a_st.line_no, mix.noise_a_st.line_count);
        if (mix.noise_b_st.line_valid)
            $fwrite(fm, "N 1 %0d %0d %0d\n", mix.noise_b_st.line_field, mix.noise_b_st.line_no, mix.noise_b_st.line_count);
        // `cur` already shows the value this decision left behind (as tb_mixer.v)
        if (dec_valid) $fwrite(fm, "D %0d %0d %0d %0d %0d %0d\n", dec_use, dec_pop, dec_field, dec_line, cur, cyc);
        if (m_pop && !m_empty) begin
            $fwrite(fm, "O %0d %0d %0d %08x %0d %0d\n", m_data[51], m_data[50:41], m_data[40:32], m_data[31:0], be.ll_s, cyc);
            npop <= npop + 1;
        end
        ov_d <= overflow;
        if (overflow && !ov_d) $fwrite(fm, "V %0d\n", cyc);
    end

    // ---- SDRAM domain log (as tb_fb.v; order within a cycle: what the display asked and was
    // told, then what the writer did)
    reg        look3_d = 0, w_have = 0, w_f, trig_d = 0, lls_d = 0;
    reg [9:0]  w_line;
    reg [31:0] cs;
    reg        cs_x;
    reg        lb_run_active = 0;
    reg [12:0] lb_run_first, lb_run_last;
    integer    lb_run_first_cyc, lb_run_last_cyc;
    real       lb_run_first_ns, lb_run_last_ns;
    integer    lb_write_count = 0, lb_run_count = 0;
    always @(posedge sd_clk) if (!rst) begin
        lls_d <= be.ll_s;
        if (lls_d != be.ll_s) $fwrite(fs, "L %0d %0d\n", cyc, be.ll_s);
        if (be.fb.resetn) begin
            if (be.fb.first)
                $fwrite(fs, "D %0d %0d %0d %0d %0d %0d\n", be.fb.s_dec, be.fb.p_dec, be.fb.pok_dec,
                        be.fb.d_cur ? be.fb.ph_low : be.fb.low_of[be.fb.latest], be.fb.rt_now, cyc);
            if (be.fb.stored) $fwrite(fs, "M %0d\n", be.fb.grp_line);
            if (be.fb.accept) $fwrite(fs, "F %0d\n", be.fb.fetch_line);
            look3_d <= be.fb.look == 2'd3;
            if (look3_d && be.fb.f_blank) $fwrite(fs, "S blank %0d\n", be.fb.f_src);
            else if (look3_d) $fwrite(fs, "S %0d %0d\n", be.fb.f_buf, be.fb.f_src);
            // The source decision above can precede the end of an active writer burst. Record the
            // accepted first read burst, when the arbiter has actually started fetching the line.
            if (be.fb.req_valid && be.fb.req_ready && !be.fb.req_write && be.fb.req_addr[8:0] == 0)
                $fwrite(fs, "I %0d %0d %0d %0d %0d\n", be.fb.f_buf, be.fb.f_src,
                        be.fb.f_slot, be.fb.req_addr, cyc);
            if (be.fb.first_word) $fwrite(fs, "A %0d %0d %0d\n", be.fb.e_field, be.fb.e_line, be.fb.cur_buf);
            if (be.fb.discard) $fwrite(fs, "J %0d %0d %0d\n", be.fb.e_field, be.fb.e_line, be.fb.nxt);
            if (be.fb.publish)
                $fwrite(fs, "N %0d %0d %0d %0d %0d\n", be.fb.e_field, be.fb.e_line, be.fb.cur_buf, be.fb.n_now, be.fb.nxt);
            if (be.fb.pub_valid) $fwrite(fs, "P %0d\n", be.fb.pub_lines);
            if (be.fb.take && (!w_have || w_f != be.fb.e_field || w_line != be.fb.e_line)) begin
                $fwrite(fs, "W %0d %0d %0d %0d %0d\n", be.fb.e_field, be.fb.e_line, be.fb.e_idx, cyc, npop);
                w_have <= 1; w_f <= be.fb.e_field; w_line <= be.fb.e_line;
            end
            // every word written to the SDRAM
            if (be.fb.writing && be.wdata_take) $fwrite(fs, "w %0d %08x\n", be.fb.req_addr + be.fb.wr_k, be.wdata);
            // a line written into the line buffer: a checksum of its 360 words, X if any bit was X/Z
            if (be.fb.lb_we) begin
                if (be.fb.lb_addr[8:0] == 0) begin cs = 0; cs_x = 0; end
                cs = {cs[30:0], cs[31]} ^ be.fb.lb_data;
                if ((^be.fb.lb_data) === 1'bx) cs_x = 1;
                if (be.fb.lb_addr[8:0] == 359) begin
                    if (cs_x) $fwrite(fs, "R %0d %0d x\n", be.fb.f_blank, be.fb.lb_addr[10:9]);
                    else $fwrite(fs, "R %0d %0d %08x\n", be.fb.f_blank, be.fb.lb_addr[10:9], cs);
                end
            end
        end else begin
            w_have <= 0;
        end
        // low-latency mode: field starts, lines completed, frame triggers, word 52 of each line in the ring
        if (be.ll_take && (!be.ll_have || be.ll_new_field)) $fwrite(fs, "G %0d\n", cyc);
        if (be.ll_end) $fwrite(fs, "E %0d %0d %0d %0d\n", be.e_field, be.e_line, cyc, be.ll_fire);
        trig_d <= be.s_ll_trig;
        if (trig_d != be.s_ll_trig) $fwrite(fs, "T %0d %0d %0d\n", cyc, be.s_ll_low, be.s_ll_lines);
        if (be.ll_take && be.e_idx == 9'd52)
            $fwrite(fs, "Q %0d %0d %0d %08x %0d %.1f\n", be.e_line[3:0], be.e_field, be.e_line, be.f_data[31:0], npop, $realtime);
        // Compact accepted line-buffer writes: each LW is a maximal run of
        // physically consecutive addresses; L52 records the displayed sample
        // word and its writer provenance. The Python model expands LW itself.
        if (be.lbw_we) begin
            lb_write_count = lb_write_count + 1;
            if (be.lbw_addr[8:0] == 9'd52)
                $fwrite(fs, "L52 %0d %08x %0d %0d %0d %0d %0d %.1f\n", be.lbw_addr,
                        be.lbw_data, npop, be.ll_s, be.fb.f_buf, be.fb.f_src, be.fb.f_blank, $realtime);
            if (lb_run_active && be.lbw_addr != lb_run_last + 13'd1) begin
                $fwrite(fs, "LW %0d %0d %0d %0d %.1f %.1f\n", lb_run_first, lb_run_last,
                        lb_run_first_cyc, lb_run_last_cyc, lb_run_first_ns, lb_run_last_ns);
                lb_run_count = lb_run_count + 1;
                lb_run_active = 1'b0;
            end
            if (!lb_run_active) begin
                lb_run_active = 1'b1;
                lb_run_first = be.lbw_addr;
                lb_run_first_cyc = cyc;
                lb_run_first_ns = $realtime;
            end
            lb_run_last = be.lbw_addr;
            lb_run_last_cyc = cyc;
            lb_run_last_ns = $realtime;
            // The coverage oracle needs the exact completion edge. Do not let a
            // physically consecutive run merge across the end of one 360-word line.
            if (be.lbw_addr[8:0] == 9'd359) begin
                $fwrite(fs, "LW %0d %0d %0d %0d %.1f %.1f\n", lb_run_first, be.lbw_addr,
                        lb_run_first_cyc, cyc, lb_run_first_ns, $realtime);
                lb_run_count = lb_run_count + 1;
                lb_run_active = 1'b0;
            end
        end
    end

    // ---- pixel domain log: frame geometry, source line and word per output line, the mode
    integer pc = 0, nl = 0, nl_last = 0;  // nl: line starts since the last frame start (line lengths may differ)
    always @(posedge pix_clk) begin
        pc <= pc + 1;
        if (!rst) begin
            if (be.x == 0) nl <= (be.y == 0) ? 1 : nl + 1;
            if (be.x == 0 && be.y == 0) nl_last <= nl;       // lines of the frame that just ended
            if (be.x == 1 && be.y == 0)                        // x = 1: have_video is decided at x = 0
                $fwrite(fp, "V %0d %0d %0d %0d %0d %0d %0d %0d\n", pc, be.disp.lines, be.disp.have_video,
                        be.ll_p, be.timing.alt, nl_last, be.ll_alive, be.timing.triggered);
            if (be.x == 4 && be.y == 0) $fwrite(fp, "B %0d\n", be.disp.low_r);
            if (be.x == 300 && be.y < V_ACTIVE) $fwrite(fp, "Y %0d %0d\n", be.y, be.disp.src_cur);
            // the word read for source pixel 104/105 (x = 300 is window pixel 140, source pixel 105)
            if (be.x == 302 && be.y < V_ACTIVE) begin
                $fwrite(fp, "RAW %0d %08x %.1f\n", be.y, be.lb_rdata, $realtime);
                $fwrite(fp, "X %0d %08x %.1f\n", be.y, be.disp.lb_rdata, $realtime);
            end
        end
    end

    integer mode_change_pc = 0;
    reg        vs_d = 0, bad_line = 0, ll_p_d = 0, mode_change_d = 0, mode_change_value = 0;
    // Deterministically exercise each LOW frame gate. Arm on a negedge before the x=0
    // decision, keep the selected input low through the x=1 V sample, and release at x=2.
    // The GATE record binds the forced input to the exact V.pc without using have_video as an
    // oracle. The original gate values must both be high at arm time.
    always @(negedge pix_clk) if (!rst && GATE_PROBE != 0) begin
        if (!gate_probe_pending && !gate_probe_done && be.ll_p && ll_p_d == be.ll_p &&
            be.x == 0 && be.y == 0 &&
            be.ll_alive && be.timing.triggered) begin
            gate_probe_kind = GATE_PROBE[1:0];
            gate_probe_frame_pc = pc + 1;
            gate_probe_original_alive = be.ll_alive;
            gate_probe_original_triggered = be.timing.triggered;
            gate_probe_pending = 1'b1;
            if (GATE_PROBE == 1) force be.ll_alive = 1'b0;
            else if (GATE_PROBE == 2) force be.timing.triggered = 1'b0;
        end else if (gate_probe_pending && be.x == 2 && be.y == 0 &&
                     pc == gate_probe_frame_pc + 1) begin
            if (gate_probe_kind == 1) release be.ll_alive;
            else if (gate_probe_kind == 2) release be.timing.triggered;
            gate_probe_pending = 1'b0;
            gate_probe_done = 1'b1;
            $fwrite(fp, "GATE %0d %0d %0d %0d\n", gate_probe_kind, gate_probe_frame_pc,
                    gate_probe_original_alive, gate_probe_original_triggered);
        end
    end

    // Log the synchronized mode at the display and sample have_video one pixel edge later, after
    // fb_display has applied its mode-change blanking assignment. This checks the running frame,
    // while V's trigger metadata permits a triggered first frame after the switch.
    always @(posedge pix_clk) if (!rst) begin
        if (mode_change_d) $fwrite(fp, "M %0d %0d %0d\n", mode_change_pc, mode_change_value, be.disp.have_video);
        mode_change_d <= (ll_p_d != be.ll_p);
        if (ll_p_d != be.ll_p) begin mode_change_value <= be.ll_p; mode_change_pc <= pc; end
        ll_p_d <= be.ll_p;
        vs_d <= vsync;
        if (vsync && !vs_d) $fwrite(fp, "S %0d\n", pc);
        if ((^{r, g, b, de, hsync, vsync}) === 1'bx) bad_line <= 1'b1;
        if (be.x == 0) begin
            if (bad_line) $fwrite(fp, "Z %0d\n", pc);
            bad_line <= 1'b0;
        end
    end

    // reason 1: no safe blank; 2: SDRAM failed to drain; 3: the stall negative was not armed.
    task automatic drain_failure(input integer reason, input integer cycles, input integer stable);
        begin
            $fwrite(fs, "DRAIN fail_%0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
                    reason, cycles, stable, be.fetch_ev, be.s_fetch_req, be.fb.look, be.fb.fetching,
                    be.fb.rd_inflight, be.req_valid, be.fb.grp_ready, be.fb.writing, be.fb.grp_mask,
                    be.sdram.state, drain_stall_armed, pix_frozen, pc, be.x, be.y);
            $fflush(fs);
            $fatal(1, "tb_chain: bounded drain failed, reason %0d", reason);
        end
    endtask

    initial begin
        $readmemh("a.hex", mem_a);
        $readmemh("b.hex", mem_b);
        $readmemh("ctl.hex", ctl);
        fm = $fopen("mix.txt", "w");
        fs = $fopen("sd.txt", "w");
        fp = $fopen("pix.txt", "w");
        $fwrite(fs, "LBTRACE 1\n");
        #500 rst = 0;
        fork
            begin #(START_A); run_a = 1; end
            begin #(START_B); run_b = 1; end
        join
        wait (ia == N_A && ib == N_B);
        #(TAIL);
        // The 30 ms simulated-time bound covers a complete 720p frame plus the genlock wait budget.
        // If timing never reaches vertical blank, fail rather than leave a pixel clock running
        // forever or silently cut a pending read.
        fork : SAFE_BLANK_WAIT
            begin
                wait (be.x == 0 && be.y == V_ACTIVE);
                @(negedge pix_clk);
                pix_run = 0;
                pix_frozen = 1;
            end
            begin
                #(DRAIN_SAFE_TIMEOUT_NS);
                if (!pix_frozen) drain_failure(1, 0, 0);
            end
        join_any
        disable SAFE_BLANK_WAIT;

        drain_cycles = 0;
        drain_stable = 0;
        while (drain_stable < DRAIN_STABLE_CYCLES && drain_cycles < DRAIN_MAX_CYCLES) begin
            @(posedge sd_clk);
            #0.001;
            drain_cycles = drain_cycles + 1;
            if (drain_idle) drain_stable = drain_stable + 1;
            else drain_stable = 0;
        end
        if (drain_stable < DRAIN_STABLE_CYCLES)
            drain_failure(2, drain_cycles, drain_stable);
        if (DRAIN_STALL_READ && !drain_stall_armed)
            drain_failure(3, drain_cycles, drain_stable);
        #1;
        if (lb_run_active) begin
            $fwrite(fs, "LW %0d %0d %0d %0d %.1f %.1f\n", lb_run_first, lb_run_last,
                    lb_run_first_cyc, lb_run_last_cyc, lb_run_first_ns, lb_run_last_ns);
            lb_run_count = lb_run_count + 1;
        end
        $fwrite(fs, "LBEND %0d %0d\n", lb_write_count, lb_run_count);
        $fwrite(fs, "DRAIN pass %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d\n",
                drain_cycles, drain_stable, be.fetch_ev, be.s_fetch_req, be.fb.look, be.fb.fetching,
                be.fb.rd_inflight, be.req_valid, be.fb.grp_ready, be.fb.writing, be.fb.grp_mask,
                be.sdram.state, drain_stall_armed, pix_frozen, pc, be.x, be.y);
        $fwrite(fm, "end %0d %0d\n", overflow, cur);
        $fwrite(fs, "end %0d\n", mem.errors);
        $fclose(fm); $fclose(fs); $fclose(fp);
        $finish;
    end
    // margins the formal proofs leave open (formal/README.md, items 4 and 5), see margin_checks.vh
`define MC_BE be
`include "margin_checks.vh"
`undef MC_BE
endmodule
`default_nettype wire
