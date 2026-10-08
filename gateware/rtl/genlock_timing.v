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
`default_nettype none
module genlock_timing #(
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter H_FP_ALT = 440,
    parameter V_ACTIVE = 720,  V_FP = 5,   V_SYNC = 5,  V_BP = 20,   // V_BP >= 2
    parameter H_POL = 1, V_POL = 1,
    parameter MAX_WAIT = 8,
    parameter JUMP_AFTER = 3,                                       // 1 .. 7
    parameter HOLD = 32                                             // 0 .. 63 frames
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
    wire       on_time = vc >= V_SYNC_START;
    wire       line_end = (hc == h_last);
    wire       recover_jump = recover && vc >= V_SYNC_END && vc < V_TOTAL - 1 && (pend || trig);
    wire       frame_end = line_end && lock && !jump && vc == V_TOTAL - 1 && (pend || trig || wait_n == MAX_WAIT);

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
            triggered <= 1'b0;
        end else if (line_end) begin
            hc <= 0;
            if (!lock) begin
                vc <= (vc == V_TOTAL - 1) ? 12'd0 : vc + 12'd1;
                pend <= 1'b0; jump <= 1'b0; wait_n <= 0; early_n <= 0;
                cut <= 1'b0; recover <= 1'b0;
                if (vc == V_TOTAL - 1) triggered <= 1'b0;
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
    wire       f_wrap = line_end && !rst && (lock ? frame_end : vc == V_TOTAL - 1);
    always @(posedge clk)
        if (rst) begin f_lines <= 0; f_cut <= 1'b0; f_recover <= 1'b0; f_left <= 0; f_sync_lines <= 0; end
        else begin
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
        if (wait_n != 0) assert (vc == V_TOTAL - 1);
        if (!(hc == 0 && vc == 0)) assert (f_lines <= vc + wait_n);
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
    end
`endif
endmodule
`default_nettype wire
