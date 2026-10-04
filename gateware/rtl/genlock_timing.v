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
// * a trigger before the vertical sync (output and input far apart, e.g.
//   when the input appears) jumps to the last line at once: one short frame,
//   then locked.
// h_alt selects the H_FP_ALT front porch (720p50) and is taken at frame start.
`default_nettype none
module genlock_timing #(
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter H_FP_ALT = 440,
    parameter V_ACTIVE = 720,  V_FP = 5,   V_SYNC = 5,  V_BP = 20,   // V_BP >= 2
    parameter H_POL = 1, V_POL = 1,
    parameter MAX_WAIT = 8
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
    output reg         frame_start // one pulse at the first active pixel
);
    localparam V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;
    localparam V_SYNC_END = V_ACTIVE + V_FP + V_SYNC;          // first back-porch line
    reg [11:0] hc, vc;
    localparam [11:0] FP0 = H_FP, FP1 = H_FP_ALT;
    reg        alt;
    wire [11:0] fp = alt ? FP1 : FP0;
    wire [11:0] h_last = H_ACTIVE + fp + H_SYNC + H_BP - 1;
    reg        pend, jump;
    reg [3:0]  wait_n;

    always @(posedge clk) begin
        if (trig) begin
            pend <= 1'b1;
            if (lock && vc < V_ACTIVE + V_FP) jump <= 1'b1;
        end
        if (rst) begin
            hc <= 0; vc <= 0; alt <= 1'b0; pend <= 1'b0; jump <= 1'b0; wait_n <= 0;
        end else if (hc == h_last) begin
            hc <= 0;
            if (!lock) begin
                vc <= (vc == V_TOTAL - 1) ? 12'd0 : vc + 12'd1;
                pend <= 1'b0; jump <= 1'b0; wait_n <= 0;
            end else if (jump) begin
                vc <= V_TOTAL - 1; jump <= 1'b0; wait_n <= 0;
            end else if (vc == V_SYNC_END - 1) begin
                vc <= vc + 12'd2;                                // skip one back-porch line
            end else if (vc == V_TOTAL - 1) begin
                if (pend || trig || wait_n == MAX_WAIT) begin
                    vc <= 0; pend <= 1'b0; wait_n <= 0;
                end else
                    wait_n <= wait_n + 1'b1;                     // repeat the last line
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
endmodule
`default_nettype wire
