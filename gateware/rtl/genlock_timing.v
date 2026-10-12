// Video timing generator that can be locked to the input fields (low-latency
// mode, see fb_backend.v). With lock = 0 it is identical to video_timing.v
// (CEA-861 720p60 by default).
//
// With lock = 1 every output frame is started by `trig` (one input field
// ready to be shown):
// * the natural frame is one line shorter (the first back-porch line is
//   skipped), so it always ends before the next field arrives;
// * the last back-porch line then repeats until `trig` has come (at most
//   MAX_WAIT extra lines; with no input the timing free-runs), and the next
//   line is active line 0. NTSC fields (750.75 lines of 720p) give frames of
//   750 / 751 lines; PAL fields with h_alt (720p50 line) give 750 lines.
// * a trigger during the vertical blanking is on time: the frame ends as it
//   would have. A trigger before that is early. One early trigger (a field
//   that was cut short, a false field start) is ignored. JUMP_AFTER early
//   triggers in a row mean that the input has moved: the frame is then cut
//   short once, and not again for HOLD frames. The cut keeps a full vsync
//   pulse and skips the rest of its back porch. Only the following frame may
//   skip back-porch lines, after its full active area and vsync, to recover
//   the phase. Both keep the last line used to prepare the display's line 0.
//   All other frames have at least V_TOTAL - 1 lines.
// h_alt selects the H_FP_ALT front porch (720p50) and is taken at frame start.
//
// WAIT_BEFORE_VSYNC = 1 (default 0) moves the varying line before vsync, so that the distance
// from vsync to the first active line is the same in every frame (V_SYNC + V_BP lines): the
// natural frame skips the first front-porch line instead of the first back-porch line, the last
// front-porch line repeats until `trig`, and then the frame runs its full sync and back porch.
// The first active line therefore comes V_SYNC + V_BP lines after the trigger instead of on the
// next line: 25 lines (0.56 ms) at 720p, and the low-latency ring writer is about 9 source lines
// further ahead of the display, more than its 16 lines hold (fb_backend.v). A trigger is on time in
// the V_SYNC + V_BP lines up to the wait line, as many as before vsync otherwise. A cut goes straight
// to the sync lines and keeps them and the full back porch; no recovery frame is needed. Needs
// V_FP >= 2. For trying the other placement on a screen (gateware/README.md); not the default.
`default_nettype none
module genlock_timing #(
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter H_FP_ALT = 440,
    parameter V_ACTIVE = 720,  V_FP = 5,   V_SYNC = 5,  V_BP = 20,   // V_BP >= 2
    parameter H_POL = 1, V_POL = 1,
    parameter MAX_WAIT = 8,
    parameter JUMP_AFTER = 3,                                       // 1 .. 7
    parameter HOLD = 32,                                            // 0 .. 63 frames
    parameter WAIT_BEFORE_VSYNC = 0                                 // 1: wait on the last front-porch line
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        lock,
    input  wire        trig,       // one pulse per input field (pixel clock domain)
    input  wire        h_alt,
    output reg  [11:0] x,          // pixel within the line (valid when de)
    output reg  [11:0] y,          // line within the frame (valid when de)
    output reg         de,
    output reg         hsync,
    output reg         vsync,
    output reg         frame_start,// one pulse at the first active pixel
    output reg         triggered   // the running frame was started by a trigger (0: free-running, or
                                   // the wait for a trigger ran out)
);
    localparam V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;
    localparam V_SYNC_START = V_ACTIVE + V_FP;
    localparam V_SYNC_END = V_ACTIVE + V_FP + V_SYNC;          // first back-porch line
    reg [11:0] hc, vc;
    localparam [11:0] FP0 = H_FP, FP1 = H_FP_ALT;
    reg        alt;
    wire [11:0] fp = alt ? FP1 : FP0;
    wire [11:0] h_last = H_ACTIVE + fp + H_SYNC + H_BP - 1;
    reg        pend, jump;
    reg        cut, recover;      // cut frame, then exactly one frame allowed to shorten its back porch
    reg [3:0]  wait_n;
    reg [2:0]  early_n;            // early triggers in a row (saturates at JUMP_AFTER - 1)
    reg [5:0]  hold;               // frames until the next short frame is allowed
    reg        rel_trig;           // WAIT_BEFORE_VSYNC: this frame's wait was ended by a trigger
    wire       rel = vc >= V_SYNC_START;   // WAIT_BEFORE_VSYNC: the wait is over, sync and back porch run
    // a trigger is on time in the V_SYNC + V_BP lines before the frame can end: the vertical blanking
    // (WAIT_BEFORE_VSYNC = 0), or the lines up to the wait line before vsync (= 1)
    wire       on_time = (WAIT_BEFORE_VSYNC != 0) ? (!rel && vc + (V_SYNC + V_BP) >= V_SYNC_START)
                                                  : (vc >= V_SYNC_START);
    wire       line_end = (hc == h_last);
    wire       recover_jump = recover && vc >= V_SYNC_END && vc < V_TOTAL - 1 && (pend || trig);
    wire       frame_end = line_end && lock && !jump && vc == V_TOTAL - 1 && (pend || trig || wait_n == MAX_WAIT);
    wire       frame_end_b = line_end && lock && vc == V_TOTAL - 1;          // WAIT_BEFORE_VSYNC: fixed end

    always @(posedge clk) begin
        if (trig && lock) begin
            if (on_time) begin pend <= 1'b1; early_n <= 0; end
            else if (early_n == JUMP_AFTER - 1 && hold == 0) begin
                pend <= 1'b1; jump <= 1'b1; early_n <= 0; hold <= HOLD;
            end else if (early_n != JUMP_AFTER - 1) early_n <= early_n + 1'b1;
        end
        if (rst) begin
            hc <= 0; vc <= 0; alt <= 1'b0; pend <= 1'b0; jump <= 1'b0; wait_n <= 0; early_n <= 0; hold <= 0;
            cut <= 1'b0; recover <= 1'b0;
            triggered <= 1'b0; rel_trig <= 1'b0;
        end else if (line_end) begin
            hc <= 0;
            if (!lock) begin
                vc <= (vc == V_TOTAL - 1) ? 12'd0 : vc + 12'd1;
                pend <= 1'b0; jump <= 1'b0; wait_n <= 0; early_n <= 0;
                cut <= 1'b0; recover <= 1'b0; rel_trig <= 1'b0;
                if (vc == V_TOTAL - 1) triggered <= 1'b0;
            end else if (WAIT_BEFORE_VSYNC != 0) begin
                if (frame_end_b) begin                           // end of the fixed back porch: next frame
                    vc <= 0; wait_n <= 0; triggered <= rel_trig; rel_trig <= 1'b0; cut <= 1'b0; jump <= 1'b0;
                    if (hold != 0 && !jump) hold <= hold - 1'b1;  // a jump taken here starts its hold now
                end else if (jump && !rel) begin                 // cut: straight to the sync lines
                    vc <= V_SYNC_START; jump <= 1'b0; pend <= 1'b0; wait_n <= 0;
                    cut <= 1'b1; rel_trig <= 1'b1;
                end else if (!rel && vc == V_SYNC_START - 1) begin   // the wait line, before vsync
                    if (pend || trig || wait_n == MAX_WAIT) begin
                        vc <= V_SYNC_START; rel_trig <= pend || trig; pend <= 1'b0; wait_n <= 0;
                    end else
                        wait_n <= wait_n + 1'b1;                 // repeat the last front-porch line
                end else if (vc == V_ACTIVE - 1)
                    vc <= V_ACTIVE + 1;                          // natural frame: skip the first front-porch line
                else begin
                    vc <= vc + 12'd1;
                    if (rel) jump <= 1'b0;                       // a jump while sync runs: its pend starts the next frame
                end
            end else if (frame_end) begin
                vc <= 0; pend <= 1'b0; wait_n <= 0; triggered <= pend || trig;
                recover <= cut; cut <= 1'b0;
                if (hold != 0) hold <= hold - 1'b1;
            end else if (jump) begin
                // A trigger on the last clock of the front porch can leave jump pending
                // until a sync line. Advance that line normally: never repeat or skip sync.
                vc <= (vc < V_SYNC_START) ? V_SYNC_START :
                      (vc == V_SYNC_END - 1) ? V_TOTAL - 1 : vc + 12'd1;
                jump <= 1'b0; wait_n <= 0; cut <= 1'b1;
            end else if (recover_jump) begin
                // Keep one full last line: fb_display resets its scaler there even in LOW.
                // This adds at most one line of phase, recovered by the next normal frame.
                vc <= V_TOTAL - 1;
            end else if (vc == V_SYNC_END - 1) begin
                if (cut) vc <= V_TOTAL - 1;                      // cut keeps sync, then one last porch line
                else vc <= vc + 12'd2;                           // normal frame skips one back-porch line
            end else if (vc == V_TOTAL - 1) begin
                wait_n <= wait_n + 1'b1;                         // repeat the last line
            end else
                vc <= vc + 12'd1;
            if (vc == V_TOTAL - 1) alt <= h_alt;
        end else
            hc <= hc + 12'd1;
        de          <= (hc < H_ACTIVE) && (vc < V_ACTIVE);
        x           <= hc;
        y           <= vc;
        hsync       <= ((hc >= H_ACTIVE + fp) && (hc < H_ACTIVE + fp + H_SYNC)) ? H_POL[0] : ~H_POL[0];
        vsync       <= ((vc >= V_ACTIVE + V_FP) && (vc < V_SYNC_END)) ? V_POL[0] : ~V_POL[0];
        frame_start <= (hc == 0) && (vc == 0);
    end

`ifdef FORMAL
    // Proven by formal/run.sh with lock, trig and h_alt free at every clock:
    // * the counters stay in range, and every frame ends within V_TOTAL + MAX_WAIT
    //   lines (the output never stalls, whatever the triggers do);
    // * a frame has at least V_TOTAL - 1 lines unless it was cut or immediately
    //   follows a cut; two cuts have at least HOLD frame starts between them;
    // * every complete frame traverses exactly V_SYNC sync lines.
    localparam [11:0] H_LAST_MAX = H_ACTIVE + (FP1 > FP0 ? FP1 : FP0) + H_SYNC + H_BP - 1;
    reg [11:0] f_lines;                                   // lines finished since the frame started
    reg        f_cut;                                     // this frame was cut short
    reg        f_recover;                                 // the immediately preceding frame was cut
    reg [11:0] f_sync_lines;
    reg [5:0]  f_left;                                    // frame starts still to come before the next cut
    wire       f_wrap = line_end && !rst && (lock ? (WAIT_BEFORE_VSYNC != 0 ? frame_end_b : frame_end) : vc == V_TOTAL - 1);
    reg [11:0] f_bp_lines;                                // back-porch lines finished in this frame
    always @(posedge clk)
        if (rst) begin f_lines <= 0; f_cut <= 1'b0; f_recover <= 1'b0; f_left <= 0; f_sync_lines <= 0; f_bp_lines <= 0; end
        else begin
            if (hc == 0 && vc == 0) f_bp_lines <= 0;
            else if (line_end && vc >= V_SYNC_END && f_bp_lines != 12'hFFF) f_bp_lines <= f_bp_lines + 1'b1;
            if (hc == 0 && vc == 0) begin f_lines <= 0; f_sync_lines <= 0; end
            else if (line_end && f_lines != 12'hFFF) f_lines <= f_lines + 1'b1;
            if (line_end && vc >= V_SYNC_START && vc < V_SYNC_END) f_sync_lines <= f_sync_lines + 1'b1;
            if (line_end && lock && jump) begin f_cut <= 1'b1; f_left <= HOLD; end
            if (f_wrap) begin
                f_cut <= 1'b0;
                f_recover <= f_cut;
                if (f_left != 0) f_left <= f_left - 1'b1;
            end
        end
    always @* begin
        assert (vc < V_TOTAL);
        assert (hc <= H_LAST_MAX);
        assert (wait_n <= MAX_WAIT);
        assert (f_lines <= V_TOTAL + MAX_WAIT);
        // induction strengthening: waiting only happens on the last line, and the
        // frame so far is no longer than the lines counted plus the repeats
        if (wait_n != 0) assert (vc == (WAIT_BEFORE_VSYNC != 0 ? V_SYNC_START - 1 : V_TOTAL - 1));
        // (with WAIT_BEFORE_VSYNC the frame goes on after its wait: at most MAX_WAIT lines more than vc then)
        if (!(hc == 0 && vc == 0)) begin
            if (WAIT_BEFORE_VSYNC == 0 || vc < V_SYNC_START) assert (f_lines <= vc + wait_n);
            else assert (f_lines <= vc + MAX_WAIT);
        end
        assert (early_n < JUMP_AFTER);
        assert (hold <= HOLD);
        assert (f_left <= hold);
        assert (recover <= f_recover);
        assert (cut <= f_cut);
        if (jump) assert (f_left == 0);                                         // cuts are HOLD frames apart
        if (f_wrap && !f_cut && !f_recover) assert (f_lines + 1 >= V_TOTAL - 1);
        if (f_wrap && !f_cut && f_recover) assert (f_lines + 1 >= V_SYNC_END + 1);
        if (!(hc == 0 && vc == 0)) begin
            if (vc < V_SYNC_START) assert (f_sync_lines == 0);
            else if (vc < V_SYNC_END) assert (f_sync_lines == vc - V_SYNC_START);
            else assert (f_sync_lines == V_SYNC);
        end
        if (f_wrap) assert (f_sync_lines == V_SYNC);
        if (WAIT_BEFORE_VSYNC != 0) begin
            // the point of this placement: every frame ends with its full back porch after the sync
            if (f_wrap && lock) assert (f_bp_lines + 1 == V_BP);
            assert (!recover);                                                  // nothing recovers
            if (!(hc == 0 && vc == 0) && vc >= V_SYNC_END) assert (f_bp_lines == vc - V_SYNC_END);
        end
    end
`endif
endmodule
`default_nettype wire
