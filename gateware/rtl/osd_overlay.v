// On-screen display: draws the 4 x 21 character menu text (the same text as
// the OLED, kept in a small RAM written from the UI clock domain) over the
// video, with SCALE x enlarged 5x7 glyphs in 6 x 8 cells and a darkened box
// behind them. Needed because the puck's OLED is out of sight with XR glasses on.
//
// Timing: x/y come from video_timing; the video (r/g/b/de/hs/vs) arrives LAT
// clocks later (fb_display: 6). Everything here is computed from x/y with
// counters (no division) and delayed to meet the video; the output is one
// register later than the video input (de/hs/vs delayed to match).
//
// Text RAM: address row * 32 + col (row 0-3, col 0-20), 7-bit ASCII,
// written on wclk (any clock) — one dual-clock BSRAM/LUT RAM.
`default_nettype none
module osd_overlay #(
    parameter X0 = 176,                    // top-left corner of the text box
    parameter Y0 = 576,
    parameter SCALE = 3,
    parameter LAT = 6,
    parameter PAD = 4                      // background margin in pixels
) (
    input  wire        clk,                // pixel clock
    input  wire        show,               // any domain; synchronised here
    input  wire [11:0] x, y,
    input  wire [7:0]  r_in, g_in, b_in,
    input  wire        de_in, hs_in, vs_in,
    output reg  [7:0]  r, g, b,
    output reg         de, hs, vs,
    // text RAM write port
    input  wire        wclk,
    input  wire        we,
    input  wire [6:0]  waddr,
    input  wire [6:0]  wchar
);
    `include "font5x7.vh"
    localparam W = 21 * 6 * SCALE, H = 4 * 8 * SCALE;

    reg [6:0] text [0:127];
    always @(posedge wclk) if (we) text[waddr] <= wchar;

    reg [1:0] show_s;
    always @(posedge clk) show_s <= {show_s[0], show};

    // ---- stage 0: position counters (follow x; reset at the box edges)
    reg [4:0] col;  reg [2:0] gx;  reg [$clog2(SCALE+1)-1:0] sx;     // horizontal: char, glyph column, sub-pixel
    reg [1:0] row;  reg [2:0] gy;  reg [$clog2(SCALE+1)-1:0] sy;     // vertical
    wire in_x = (x >= X0) && (x < X0 + W);
    wire in_y = (y >= Y0) && (y < Y0 + H);
    wire in_bg = (x + PAD >= X0) && (x < X0 + W + PAD) && (y + PAD >= Y0) && (y < Y0 + H + PAD);
    always @(posedge clk) begin
        // horizontal: these describe pixel x (valid in the same cycle as x when x is inside)
        if (x == X0 - 1) begin col <= 0; gx <= 0; sx <= 0; end
        else if (in_x) begin
            if (sx == SCALE - 1) begin
                sx <= 0;
                if (gx == 3'd5) begin gx <= 0; col <= col + 1'b1; end else gx <= gx + 1'b1;
            end else sx <= sx + 1'b1;
        end
        // vertical: advance at the end of each line inside the box
        if (x == 0) begin
            if (y == Y0) begin row <= 0; gy <= 0; sy <= 0; end
            else if (y > Y0 && y < Y0 + H) begin
                if (sy == SCALE - 1) begin
                    sy <= 0;
                    if (gy == 3'd7) begin gy <= 0; row <= row + 1'b1; end else gy <= gy + 1'b1;
                end else sy <= sy + 1'b1;
            end
        end
    end
    // The counters are registered so that they describe the pixel x of the current
    // cycle (reset one clock before the box). Stage 1: read the character.
    reg [6:0] ch;
    reg [2:0] p2_gx, p2_gy;
    reg       p2_in, p2_bg;
    always @(posedge clk) begin
        ch <= text[{row, col}];
        p2_gx <= gx; p2_gy <= gy; p2_in <= in_x && in_y; p2_bg <= in_bg;
    end
    // stage 2 (x + 2): glyph bit
    reg p3_on, p3_bg;
    wire [7:0] fcol = font5x7(ch, p2_gx);
    always @(posedge clk) begin
        p3_on <= p2_in && p2_gx < 3'd5 && p2_gy < 3'd7 && fcol[p2_gy];
        p3_bg <= p2_bg;
    end
    // valid-during-cycle bookkeeping: ch / p2_* at x+1, p3_* at x+2, d_*[k] at x+3+k
    reg [LAT-1:0] d_on, d_bg;
    always @(posedge clk) begin
        d_on <= {d_on[LAT-2:0], p3_on};
        d_bg <= {d_bg[LAT-2:0], p3_bg};
    end
    wire on = d_on[LAT - 3], bg = d_bg[LAT - 3];          // x + LAT: aligned with r_in/g_in/b_in
    always @(posedge clk) begin
        de <= de_in; hs <= hs_in; vs <= vs_in;
        if (show_s[1] && on)      {r, g, b} <= 24'hFFFFFF;
        else if (show_s[1] && bg) {r, g, b} <= {1'b0, r_in[7:1], 1'b0, g_in[7:1], 1'b0, b_in[7:1]};
        else                      {r, g, b} <= {r_in, g_in, b_in};
    end
endmodule
`default_nettype wire
