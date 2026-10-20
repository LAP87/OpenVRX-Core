// M0: first light on Tang Nano 20K — 720p60 test pattern on the onboard HDMI.
// Colour bars with a 4:3 frame (where the analog picture will go) and a
// bouncing square, so frame rate and scan are visible. LED0 blinks once a second.
`default_nettype none

module m0_testpattern (
    input  wire       clk,          // 27 MHz crystal (pin 4)
    input  wire       rst_i,        // S1 button (pin 88), high when pressed
    output wire       tmds_clk_p, tmds_clk_n,
    output wire [2:0] tmds_d_p, tmds_d_n,
    output wire [5:0] led
);
    wire clk_serial, clk_pixel, locked;
    clocks_720p clocks (.clk_27(clk), .clk_serial(clk_serial), .clk_pixel(clk_pixel), .locked(locked));

    reg [3:0] rst_sr = 4'hF;
    always @(posedge clk_pixel) rst_sr <= {rst_sr[2:0], ~locked | rst_i};
    wire rst = rst_sr[3];

    wire [11:0] x, y;
    wire de, hs, vs, fs;
    video_timing timing (.clk(clk_pixel), .rst(rst), .x(x), .y(y), .de(de), .hsync(hs), .vsync(vs), .frame_start(fs));

    // bouncing 64x64 square
    reg [10:0] bx = 100, by = 100;
    reg        dx = 1, dy = 1;
    always @(posedge clk_pixel) if (fs) begin
        if (dx) begin
            if (bx >= 1280 - 64 - 3) begin bx <= 1280 - 64; dx <= 0; end
            else bx <= bx + 11'd3;
        end else begin
            if (bx <= 3) begin bx <= 0; dx <= 1; end
            else bx <= bx - 11'd3;
        end
        if (dy) begin
            if (by >= 720 - 64 - 2) begin by <= 720 - 64; dy <= 0; end
            else by <= by + 11'd2;
        end else begin
            if (by <= 2) begin by <= 0; dy <= 1; end
            else by <= by - 11'd2;
        end
    end

    // 4:3 window 960x720 centred: x 160..1119
    wire in43  = (x >= 160) && (x < 1120);
    wire edge43 = (x == 160) || (x == 1119) || (y == 0) || (y == 719);
    wire [2:0] bar = (x - 160) / 120;          // 8 bars of 120 px
    wire in_box = (x >= bx) && (x < bx + 64) && (y >= by) && (y < by + 64);
    reg [7:0] r, g, b;
    always @(posedge clk_pixel) begin
        if (in_box)                {r, g, b} <= 24'hFF8000;
        else if (in43 && edge43)   {r, g, b} <= 24'hFFFFFF;
        else if (in43)             {r, g, b} <= {{8{bar[1]}}, {8{bar[2]}}, {8{bar[0]}}} & {3{8'hC0}};
        else                       {r, g, b} <= {3{y[7:0] >> 3}};   // grey ramp in the side bars
    end
    // colour is registered once: delay timing by one clock to match
    reg de_d, hs_d, vs_d;
    always @(posedge clk_pixel) {de_d, hs_d, vs_d} <= {de, hs, vs};

    dvi_tx_gowin dvi (.clk_pixel(clk_pixel), .clk_serial(clk_serial), .rst(rst),
                      .de(de_d), .hsync(hs_d), .vsync(vs_d), .r(r), .g(g), .b(b), .hz50(1'b0), .rgb_full(1'b1),
                      .tmds_clk_p(tmds_clk_p), .tmds_clk_n(tmds_clk_n), .tmds_d_p(tmds_d_p), .tmds_d_n(tmds_d_n));

    reg [26:0] sec;
    always @(posedge clk) sec <= (sec == 27_000_000 - 1) ? 0 : sec + 1;
    assign led = {5'b11111, ~(sec < 13_500_000)};   // LEDs are active low
endmodule
`default_nettype wire
