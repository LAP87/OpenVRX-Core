// Margins the formal proofs leave open (gateware/formal/README.md, "Inte bevisat", items 4 and 5),
// checked in simulation. Included inside tb_fb.v and tb_chain.v with `MC_BE set to the fb_backend
// instance; uses their sd_clk, pix_clk, rst, V_TOTAL, V_ACTIVE and T_P. One line per check in
// margin.txt, read by test_fb.py (run_sim) and test_fuzz_chain.py (check_margins):
//   F t ok margin   frame_low taken at line 0 of a BUF frame with video (fb_display.v, low_r)
//   W t ok margin   ll_low taken at line 0 of a LOW frame with video
//   R t ok margin   the line-buffer slot of a BUF output line with video, at its first window pixel
//   B t ok margin   the same for the second line's slot (the second read port, VINTERP = 1), at the
//                   first window pixel of an output line whose weight is not 0
// t: simulation time (ns). ok: the value taken is the one decided for this frame and was there one
// pixel clock earlier too (F, W); the slot holds the requested line, written up to its last word (R, B).
// margin (ns): from the decision to the read, less three pixel clocks for the synchroniser (F, W), or
// from the line's last word to the read (R, B). The tests require ok and a margin of one pixel clock.
integer   mc_f;
real      mc_t_req = -1.0, mc_t_dec = -1.0, mc_t_fire = -1.0;
reg       mc_fl_d = 1'b0, mc_lw_d = 1'b0, mc_in_d = 1'b0;
reg [9:0] mc_line [0:3];
reg [3:0] mc_done = 4'd0;
real      mc_t_done [0:3];
initial mc_f = $fopen("margin.txt", "w");

// SDRAM side: when a frame's line-0 decision is taken, when the ring writer decides ll_low, and
// which line each line-buffer slot was asked for and when its last word was written
always @(posedge sd_clk) if (!rst) begin
    if (`MC_BE.fb.resetn && `MC_BE.fb.first) mc_t_dec = $realtime;
    if (`MC_BE.ll_fire) mc_t_fire = $realtime;
    if (`MC_BE.fb.resetn && `MC_BE.fb.accept) begin
        mc_line[`MC_BE.fb.fetch_slot] = `MC_BE.fb.fetch_line;
        mc_done[`MC_BE.fb.fetch_slot] = 1'b0;
    end
    if (`MC_BE.fb.lb_we && `MC_BE.fb.lb_addr[8:0] == 9'd359) begin
        mc_done[`MC_BE.fb.lb_addr[10:9]] = 1'b1;
        mc_t_done[`MC_BE.fb.lb_addr[10:9]] = $realtime;
    end
end

// pixel side: the reads
always @(posedge pix_clk) if (!rst) begin
    if (`MC_BE.x == 12'd0 && `MC_BE.y == V_TOTAL - 1) mc_t_req = $realtime;   // the frame's first request
    if (`MC_BE.x == 12'd0 && `MC_BE.y == 12'd0) begin                         // low_r is taken at this edge
        if (!`MC_BE.disp.ll && `MC_BE.disp.have_pub)
            $fwrite(mc_f, "F %.1f %0d %.1f\n", $realtime,
                    mc_t_dec > mc_t_req && `MC_BE.disp.fl_q === `MC_BE.fb.frame_low && mc_fl_d === `MC_BE.fb.frame_low,
                    (mc_t_dec > mc_t_req) ? $realtime - mc_t_dec - 3.0 * T_P : -1.0);
        if (`MC_BE.disp.ll && `MC_BE.disp.ll_alive && `MC_BE.disp.ll_triggered)
            $fwrite(mc_f, "W %.1f %0d %.1f\n", $realtime,
                    `MC_BE.disp.lw_q === `MC_BE.s_ll_low && mc_lw_d === `MC_BE.s_ll_low,
                    (mc_t_fire >= 0.0) ? $realtime - mc_t_fire - 3.0 * T_P : -1.0);
    end
    if (`MC_BE.disp.in43 && !mc_in_d && `MC_BE.y < V_ACTIVE && !`MC_BE.disp.ll && `MC_BE.disp.have_video)
        $fwrite(mc_f, "R %.1f %0d %.1f\n", $realtime,
                mc_done[`MC_BE.disp.src_cur[1:0]] && mc_line[`MC_BE.disp.src_cur[1:0]] == `MC_BE.disp.src_cur,
                mc_done[`MC_BE.disp.src_cur[1:0]] ? $realtime - mc_t_done[`MC_BE.disp.src_cur[1:0]] : -1.0);
    if (`MC_BE.disp.in43 && !mc_in_d && `MC_BE.y < V_ACTIVE && !`MC_BE.disp.ll && `MC_BE.disp.have_video
        && `MC_BE.disp.w_cur != 4'd0)
        $fwrite(mc_f, "B %.1f %0d %.1f\n", $realtime,
                mc_done[`MC_BE.disp.src_b_cur[1:0]] && mc_line[`MC_BE.disp.src_b_cur[1:0]] == `MC_BE.disp.src_b_cur,
                mc_done[`MC_BE.disp.src_b_cur[1:0]] ? $realtime - mc_t_done[`MC_BE.disp.src_b_cur[1:0]] : -1.0);
    mc_fl_d <= `MC_BE.disp.fl_q;
    mc_lw_d <= `MC_BE.disp.lw_q;
    mc_in_d <= `MC_BE.disp.in43;
end
