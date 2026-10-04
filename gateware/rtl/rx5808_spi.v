// RX5808 (RTC6715) channel programming: one 25-bit write, LSB first —
// 4 address bits, write bit (1), 20 data bits — data set while CLK is low and
// taken on the rising edge, SEL low for the whole frame (sheaivey/
// rx5808-pro-diversity receiver_spi.cpp). Two modules share CLK and DATA;
// each has its own SEL, so they can be tuned together or separately.
// Bit time = 4 * HALF clocks (HALF = 27 -> ~4 us at 27 MHz, like the reference).
`default_nettype none
module rx5808_spi #(
    parameter HALF = 27
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,             // pulse while !busy
    input  wire [1:0]  sel_mask,          // which modules to write (bit 0 = A, bit 1 = B)
    input  wire [3:0]  addr,
    input  wire [19:0] data,
    output reg         busy,
    output reg         spi_clk,
    output reg         spi_data,
    output reg  [1:0]  spi_sel_n
);
    reg [24:0] sh;
    reg [4:0]  bitn;
    reg [1:0]  ph;
    reg [$clog2(HALF+1)-1:0] t;
    reg [1:0]  mask;
    reg        guard;                     // one phase with SEL low before the first bit / after the last

    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0; spi_clk <= 1'b0; spi_data <= 1'b0; spi_sel_n <= 2'b11; t <= 0;
        end else if (!busy) begin
            if (start) begin
                busy <= 1'b1; mask <= sel_mask;
                sh <= {data, 1'b1, addr};          // bit 0 goes first
                bitn <= 0; ph <= 0; t <= 0; guard <= 1'b1;
                spi_sel_n <= ~sel_mask;
                spi_clk <= 1'b0;
            end
        end else if (t != HALF - 1) t <= t + 1'b1;
        else begin
            t <= 0;
            if (guard) begin
                guard <= 1'b0;
                if (bitn == 5'd25) begin                // trailing guard: release SEL, idle low
                    spi_sel_n <= 2'b11; spi_clk <= 1'b0; spi_data <= 1'b0; busy <= 1'b0;
                end
            end else begin
                ph <= ph + 1'b1;
                case (ph)                               // CLK low, set DATA, CLK high, CLK low
                    2'd0: spi_clk <= 1'b0;
                    2'd1: spi_data <= sh[0];
                    2'd2: spi_clk <= 1'b1;
                    2'd3: begin
                        spi_clk <= 1'b0;
                        sh <= sh >> 1;
                        bitn <= bitn + 1'b1;
                        if (bitn == 5'd24) guard <= 1'b1;
                    end
                endcase
            end
        end
    end
endmodule
`default_nettype wire
