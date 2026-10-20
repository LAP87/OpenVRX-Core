// The bouncing square of m0_testpattern.v, frame by frame: the top with the clocks, the timing and
// the DVI transmitter replaced by stubs (nothing here says anything about video, PLLs or HDMI), and
// frame_start forced once per three clocks. Prints "T <frame> <bx> <by> <dx> <dy>" after every
// frame step and "H ..." one clock later (the values must hold between frames).
// Driven by sim/test_m0_motion.py. Exported from the home bench 2026-10-20 (hub docs/bench).
`timescale 1ns/1ps
`default_nettype none
module tb_m0_motion;
    parameter FRAMES = 5000;
    reg clk = 0;
    always #5 clk = ~clk;
    reg advance = 0;
    wire tcp, tcn;
    wire [2:0] tdp, tdn;
    wire [5:0] led;
    m0_testpattern dut (.clk(clk), .rst_i(1'b0), .tmds_clk_p(tcp), .tmds_clk_n(tcn), .tmds_d_p(tdp), .tmds_d_n(tdn), .led(led));
    integer i;
    initial begin
        force dut.fs = advance;
        for (i = 0; i < FRAMES; i = i + 1) begin
            @(negedge clk); advance = 1;
            @(negedge clk); advance = 0;
            $display("T %0d %0d %0d %0d %0d", i, dut.bx, dut.by, dut.dx, dut.dy);
            @(negedge clk);
            $display("H %0d %0d %0d %0d %0d", i, dut.bx, dut.by, dut.dx, dut.dy);
        end
        $display("MOTION_END %0d", FRAMES);
        $finish;
    end
endmodule

// stubs: the top's other blocks, with the ports of the real ones (dvi_tx_gowin has rgb_full since 2026-10-18)
module clocks_720p (input wire clk_27, output wire clk_serial, output wire clk_pixel, output wire locked);
    assign clk_serial = clk_27; assign clk_pixel = clk_27; assign locked = 1'b1;
endmodule
module video_timing (input wire clk, input wire rst, output wire [11:0] x, output wire [11:0] y,
                     output wire de, output wire hsync, output wire vsync, output wire frame_start);
    assign x = 0; assign y = 0; assign de = 0; assign hsync = 0; assign vsync = 0; assign frame_start = 0;
endmodule
module dvi_tx_gowin (input wire clk_pixel, input wire clk_serial, input wire rst, input wire de, input wire hsync,
                     input wire vsync, input wire [7:0] r, input wire [7:0] g, input wire [7:0] b, input wire hz50,
                     input wire rgb_full, output wire tmds_clk_p, output wire tmds_clk_n,
                     output wire [2:0] tmds_d_p, output wire [2:0] tmds_d_n);
    assign tmds_clk_p = 0; assign tmds_clk_n = 0; assign tmds_d_p = 0; assign tmds_d_n = 0;
endmodule
`default_nettype wire
