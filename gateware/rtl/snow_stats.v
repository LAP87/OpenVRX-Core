// "Snow meter" statistics for the puck OLED (mixer / SDRAM clock domain).
//
// Per receiver: mean high-frequency energy per line (the same sum |Y[n]-Y[n-1]|
// the mixer decides on) over windows of 2^LOG_N lines. Weak signal snow raises
// it, so it doubles as a self-interference meter (design/PUCK_2027_KONCEPT.md).
// Mixer usage: how many of the last 2^LOG_N decisions showed A, B or a blend.
//
// Each finished window updates the outputs and flips `toggle`; the values stay
// stable until the next window, so another clock domain can copy them after
// synchronising the toggle.
`default_nettype none
module snow_stats #(
    parameter LOG_N = 10
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        line_a,            // a line of channel A is released (its metrics on hf_a)
    input  wire [19:0] hf_a,
    input  wire        line_b,
    input  wire [19:0] hf_b,
    input  wire        dec_valid,
    input  wire [1:0]  dec_use,           // 01 A, 10 B, 11 blend, 00 dropped
    output reg  [19:0] mean_a,
    output reg  [19:0] mean_b,
    output reg  [LOG_N:0] use_a, use_b, use_mix,
    output reg         toggle_a,          // new mean_a
    output reg         toggle_b,
    output reg         toggle_use
);
    reg [LOG_N+19:0] sum_a, sum_b;
    reg [LOG_N-1:0]  n_a, n_b, n_d;
    reg [LOG_N:0]    ca, cb, cm;

    always @(posedge clk) begin
        if (line_a) begin
            if (&n_a) begin
                mean_a <= (sum_a + hf_a) >> LOG_N; sum_a <= 0; toggle_a <= ~toggle_a;
            end else sum_a <= sum_a + hf_a;
            n_a <= n_a + 1'b1;
        end
        if (line_b) begin
            if (&n_b) begin
                mean_b <= (sum_b + hf_b) >> LOG_N; sum_b <= 0; toggle_b <= ~toggle_b;
            end else sum_b <= sum_b + hf_b;
            n_b <= n_b + 1'b1;
        end
        if (dec_valid) begin
            if (&n_d) begin
                use_a   <= ca + (dec_use == 2'b01);
                use_b   <= cb + (dec_use == 2'b10);
                use_mix <= cm + (dec_use == 2'b11);
                ca <= 0; cb <= 0; cm <= 0; toggle_use <= ~toggle_use;
            end else begin
                ca <= ca + (dec_use == 2'b01);
                cb <= cb + (dec_use == 2'b10);
                cm <= cm + (dec_use == 2'b11);
            end
            n_d <= n_d + 1'b1;
        end
        if (rst) begin
            sum_a <= 0; sum_b <= 0; n_a <= 0; n_b <= 0; n_d <= 0; ca <= 0; cb <= 0; cm <= 0;
            mean_a <= 0; mean_b <= 0; use_a <= 0; use_b <= 0; use_mix <= 0;
            toggle_a <= 1'b0; toggle_b <= 1'b0; toggle_use <= 1'b0;
        end
    end
endmodule
`default_nettype wire
