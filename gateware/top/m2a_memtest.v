// M2a: SDRAM memory test for bring-up, before M2 and M4. Only the board: no decoder, no video.
// rtl/memtest_core.v writes the whole SDRAM with two patterns, reads it back at three read sample
// points in turn and prints one line per sample point on the onboard USB-UART (PIN69, 115200 8N1),
// about four lines a second:
//
//   M rs=5 pass=0012 err=00000000 bits=00000000000000000000000000000000 pos=00000000
//
// The fields are explained in memtest_core.v. A line with err=00000000 is a sample point that works.
// LEDs (active low): 0 flips with every line, 1 SDRAM initialised, 2 the default sample point
// (rs = 5) had errors in its last line.
// S1 restarts the test. S2 held: one deliberate error per line (err=00000001 where the read works).
// Another SDRAM clock phase without editing sources (sixteenths of a period, 10 = 225 degrees is the
// default):  SDRAM_PHASE=12 gateware/build.sh m2a_memtest  -> build/m2a_memtest_phase12.fs
`default_nettype none
module m2a_memtest (
    input  wire        clk,               // 27 MHz
    input  wire        rst_i,             // S1, high when pressed
    input  wire        key_i,             // S2, high when pressed
    output wire [2:0]  led,
    output wire        uart_txd,
    // embedded SDRAM (names fixed by the constraints)
    output wire        O_sdram_clk, O_sdram_cke, O_sdram_cs_n, O_sdram_cas_n, O_sdram_ras_n, O_sdram_wen_n,
    output wire [3:0]  O_sdram_dqm,
    output wire [10:0] O_sdram_addr,
    output wire [1:0]  O_sdram_ba,
    inout  wire [31:0] IO_sdram_dq
);
    wire sd_clk, sd_clk_shift, sd_locked;
    clocks_sdram sdclk (.clk_27(clk), .clk(sd_clk), .clk_shift(sd_clk_shift), .locked(sd_locked));

    wire      rst_async = rst_i | ~sd_locked;
    reg [2:0] rst_s;
    reg [1:0] key_s;
    always @(posedge sd_clk or posedge rst_async) if (rst_async) rst_s <= 3'b111; else rst_s <= {rst_s[1:0], 1'b0};
    always @(posedge sd_clk) key_s <= {key_s[0], key_i};

    wire init_done, line_toggle, fail_default;
    memtest_core core (
        .clk(sd_clk), .clk_sdram(sd_clk_shift), .rst(rst_s[2]), .inject(key_s[1]),
        .SDRAM_DQ(IO_sdram_dq), .SDRAM_A(O_sdram_addr), .SDRAM_BA(O_sdram_ba), .SDRAM_nCS(O_sdram_cs_n),
        .SDRAM_nWE(O_sdram_wen_n), .SDRAM_nRAS(O_sdram_ras_n), .SDRAM_nCAS(O_sdram_cas_n),
        .SDRAM_CLK(O_sdram_clk), .SDRAM_CKE(O_sdram_cke), .SDRAM_DQM(O_sdram_dqm),
        .uart_txd(uart_txd), .init_done(init_done), .line_toggle(line_toggle), .fail_default(fail_default));

    assign led = ~{fail_default, init_done, line_toggle};
endmodule
`default_nettype wire
