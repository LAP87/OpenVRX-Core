// Sequential binary -> BCD (double dabble, shift-and-add-3): W bits in,
// D decimal digits out, W + 1 clocks per conversion. Cheap alternative to
// combinational division for slow displays.
`default_nettype none
module bin2bcd #(
    parameter W = 20,
    parameter D = 6
) (
    input  wire           clk,
    input  wire           start,          // pulse while !busy
    input  wire [W-1:0]   bin,
    output reg            busy,
    output reg            done,           // pulse; bcd valid from then on
    output reg  [4*D-1:0] bcd
);
    reg [W-1:0]   sh;
    reg [4*D-1:0] acc;
    reg [$clog2(W+1)-1:0] n;
    integer k;
    reg [4*D-1:0] adj;
    always @* begin
        adj = acc;
        for (k = 0; k < D; k = k + 1)
            if (adj[4*k +: 4] >= 4'd5) adj[4*k +: 4] = adj[4*k +: 4] + 4'd3;
    end
    always @(posedge clk) begin
        done <= 1'b0;
        if (!busy) begin
            if (start) begin busy <= 1'b1; sh <= bin; acc <= 0; n <= 0; end
        end else if (n == W) begin
            busy <= 1'b0; done <= 1'b1; bcd <= acc;
        end else begin
            {acc, sh} <= {adj[4*D-2:0], sh, 1'b0};
            n <= n + 1'b1;
        end
    end
    initial begin busy = 1'b0; done = 1'b0; end
endmodule
`default_nettype wire
