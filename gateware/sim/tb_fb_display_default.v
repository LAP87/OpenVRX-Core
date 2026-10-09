// Focused bench for the zero-line-count fallback in fb_display.
`timescale 1ns/1ps
`default_nettype none
module tb_fb_display_default;
    parameter V_ACTIVE = 72;
    localparam V_TOTAL = V_ACTIVE == 720 ? 750 : V_ACTIVE + 15;

    reg clk = 0, rst = 1;
    always #5 clk = ~clk;

    reg [11:0] x = 0, y = 0;
    reg ll = 1, ll_alive = 1, ll_triggered = 1, ll_low = 0;
    reg [9:0] ll_lines = 0;
    wire [12:0] lb_raddr;
    wire [7:0] r, g, b, yo, cbo, cro;
    wire de_o, hs_o, vs_o;
    wire have_video;

    fb_display #(.V_TOTAL(V_TOTAL), .V_ACTIVE(V_ACTIVE), .H_WIN0(0), .H_WIN(4), .BOB(1)) dut (
        .clk(clk), .rst(rst), .x(x), .y(y), .de(1'b0), .hsync(1'b0), .vsync(1'b0),
        .pub_toggle(1'b0), .pub_lines(10'd0), .frame_low(1'b0),
        .fetch_toggle(), .fetch_line(), .fetch_slot(), .fetch_first(),
        .ll(ll), .ll_lines(ll_lines), .ll_alive(ll_alive), .ll_triggered(ll_triggered), .ll_low(ll_low),
        .lb_raddr(lb_raddr), .lb_rdata(32'h12345678),
        .r(r), .g(g), .b(b), .yo(yo), .cbo(cbo), .cro(cro),
        .de_o(de_o), .hs_o(hs_o), .vs_o(vs_o), .have_video(have_video)
    );

    task set_xy(input [11:0] next_x, input [11:0] next_y);
        begin
            @(negedge clk);
            x = next_x;
            y = next_y;
            @(posedge clk);
            #1;
        end
    endtask

    integer j;
    initial begin
        repeat (3) begin @(posedge clk); #1; end
        rst = 0;

        // The first frame start samples ll_lines=0. Drive only the three x positions used by
        // fb_display's line-start and source-step logic; each trace row is read after its NBA.
        set_xy(0, V_TOTAL - 1);
        set_xy(1, V_TOTAL - 1);
        set_xy(2, V_TOTAL - 1);
        for (j = 0; j < V_TOTAL; j = j + 1) begin
            set_xy(0, j);
            set_xy(1, j);
            if (j < V_ACTIVE)
                $display("TRACE %0d %0d %0d %0d", y, dut.lines, dut.src_cur, lb_raddr[12:9]);
            set_xy(2, j);
        end
        $display("END %0d", dut.lines);
        $finish;
    end
endmodule
`default_nettype wire
