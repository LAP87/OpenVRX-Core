// RX5808 channel writes: when the synthesiser register is written.
//
//   - FIRST_MS after reset, always. The receivers need their power-up time; a
//     write straight after configuration is lost on a receiver that is not up yet.
//   - At once when `write_now` pulses (the user changed the channel).
//   - Again each time REPEAT_MS have passed with no write and with no decoder
//     locked. A receiver that got its power late, or lost it, is back on its
//     default channel (RTC6715: 5865 MHz); then nothing locks and it is retuned
//     within REPEAT_MS.
//
// A locked decoder stops the repeats: whether rewriting an unchanged synthesiser
// register disturbs the picture is not known (not tried on hardware). So a
// receiver that restarts on 5865 MHz and finds a signal there stays there until
// the channel is changed or the FPGA restarts.
//
// Both modules get the same word (shared CLK, DATA and SEL): rx5808_spi.v.
`default_nettype none
module rx5808_tune #(
    parameter CLK_HZ = 27_000_000,
    parameter FIRST_MS = 500,
    parameter REPEAT_MS = 2000
) (
    input  wire        clk,
    input  wire        rst,
    input  wire [19:0] synth,             // synthesiser register B of the wanted channel (vtx_channels.vh)
    input  wire        write_now,         // pulse: the channel changed
    input  wire        any_locked,        // clk domain: at least one decoder reports lock
    output wire        spi_clk,
    output wire        spi_data,
    output wire [1:0]  spi_sel_n
);
    localparam integer FIRST  = FIRST_MS * (CLK_HZ / 1000);
    localparam integer REPEAT = REPEAT_MS * (CLK_HZ / 1000);
    localparam W = $clog2((FIRST > REPEAT ? FIRST : REPEAT) + 1);

    reg          start, pending, first_done;
    reg  [W-1:0] t;                       // clocks since reset, the last write or the last locked moment
    wire         spi_busy;
    rx5808_spi #(.HALF(CLK_HZ / 1_000_000 > 0 ? CLK_HZ / 1_000_000 : 1)) spi (
        .clk(clk), .rst(rst), .start(start), .sel_mask(2'b11), .addr(4'h1), .data(synth),
        .busy(spi_busy), .spi_clk(spi_clk), .spi_data(spi_data), .spi_sel_n(spi_sel_n));

    always @(posedge clk) begin
        start <= 1'b0;
        if (write_now) pending <= 1'b1;
        if (!first_done) begin
            if (t == FIRST - 1) begin first_done <= 1'b1; pending <= 1'b1; t <= 0; end
            else t <= t + 1'b1;
        end else if (any_locked || start || spi_busy) t <= 0;
        else if (t == REPEAT - 1) begin pending <= 1'b1; t <= 0; end
        else t <= t + 1'b1;
        // `synth` follows the channel one clock after write_now, and the SPI master latches it with start
        if (pending && !spi_busy && !start && !write_now) begin start <= 1'b1; pending <= 1'b0; end
        if (rst) begin t <= 0; first_done <= 1'b0; pending <= 1'b0; start <= 1'b0; end
    end
endmodule
`default_nettype wire
