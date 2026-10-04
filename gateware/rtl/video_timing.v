// Free-running video timing generator. Defaults: CEA-861 1280x720p60
// (74.25 MHz pixel clock, 1650 x 750 total, positive syncs).
`default_nettype none

module video_timing #(
    parameter H_ACTIVE = 1280, H_FP = 110, H_SYNC = 40, H_BP = 220,
    parameter V_ACTIVE = 720,  V_FP = 5,   V_SYNC = 5,  V_BP = 20,
    parameter H_POL = 1, V_POL = 1
) (
    input  wire        clk,
    input  wire        rst,
    output reg  [11:0] x,          // pixel within the line (valid when de)
    output reg  [11:0] y,          // line within the frame (valid when de)
    output reg         de,
    output reg         hsync,
    output reg         vsync,
    output reg         frame_start // one pulse at the first active pixel
);
    localparam H_TOTAL = H_ACTIVE + H_FP + H_SYNC + H_BP;
    localparam V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;
    reg [11:0] hc, vc;

    always @(posedge clk) begin
        if (rst) begin
            hc <= 0; vc <= 0;
        end else if (hc == H_TOTAL - 1) begin
            hc <= 0;
            vc <= (vc == V_TOTAL - 1) ? 12'd0 : vc + 12'd1;
        end else
            hc <= hc + 12'd1;
        de          <= (hc < H_ACTIVE) && (vc < V_ACTIVE);
        x           <= hc;
        y           <= vc;
        hsync       <= ((hc >= H_ACTIVE + H_FP) && (hc < H_ACTIVE + H_FP + H_SYNC)) ? H_POL[0] : ~H_POL[0];
        vsync       <= ((vc >= V_ACTIVE + V_FP) && (vc < V_ACTIVE + V_FP + V_SYNC)) ? V_POL[0] : ~V_POL[0];
        frame_start <= (hc == 0) && (vc == 0);
    end
endmodule
`default_nettype wire
