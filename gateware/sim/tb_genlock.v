`timescale 1ns/1ps
`default_nettype none
module tb_genlock;
    parameter H_ACTIVE = 4, H_FP = 1, H_SYNC = 1, H_BP = 2, H_FP_ALT = 2;
    parameter V_ACTIVE = 8, V_FP = 2, V_SYNC = 2, V_BP = 4;
    parameter H_POL = 1, V_POL = 1;
    parameter MAX_WAIT = 8, JUMP_AFTER = 3, HOLD = 32;
    parameter N_CYCLES = 10000;

    reg clk = 0;
    always #5 clk = ~clk;

    reg rst = 1, lock = 0, trig = 0, h_alt = 0;
    wire [11:0] x, y;
    wire de, hsync, vsync, frame_start, triggered;

    reg [3:0] inputs [0:N_CYCLES-1];
    integer i, fd;
    reg [1023:0] vectors_path, trace_path;

    genlock_timing #(
        .H_ACTIVE(H_ACTIVE), .H_FP(H_FP), .H_SYNC(H_SYNC), .H_BP(H_BP), .H_FP_ALT(H_FP_ALT),
        .V_ACTIVE(V_ACTIVE), .V_FP(V_FP), .V_SYNC(V_SYNC), .V_BP(V_BP),
        .H_POL(H_POL), .V_POL(V_POL), .MAX_WAIT(MAX_WAIT),
        .JUMP_AFTER(JUMP_AFTER), .HOLD(HOLD)
    ) dut (
        .clk(clk), .rst(rst), .lock(lock), .trig(trig), .h_alt(h_alt),
        .x(x), .y(y), .de(de), .hsync(hsync), .vsync(vsync),
        .frame_start(frame_start), .triggered(triggered)
    );

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors_path)) $fatal(1, "missing +VECTORS");
        if (!$value$plusargs("TRACE=%s", trace_path)) $fatal(1, "missing +TRACE");
        $readmemh(vectors_path, inputs);
        fd = $fopen(trace_path, "w");
        if (fd == 0) $fatal(1, "cannot open trace");

        for (i = 0; i < N_CYCLES; i = i + 1) begin
            {rst, lock, trig, h_alt} = inputs[i];
            @(posedge clk);
            #1;
            $fdisplay(fd, "%0d %0d %0d %0d %0d %0d %0d", i,
                      frame_start, y, x, vsync, de, triggered);
            @(negedge clk);
        end

        $fclose(fd);
        $finish;
    end
endmodule
`default_nettype wire
