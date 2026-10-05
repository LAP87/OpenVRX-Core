# Real clock requirements (the build's --freq default would apply 75 MHz to every clock).
# sd_clk is 64.8 MHz (clocks_sdram.v), the pixel clock 74.25 MHz (720p), the decoder SCLKs and the board clock 27 MHz.
create_clock -period 15.432 -name sd_clk [get_nets sd_clk]
create_clock -period 13.468 -name clk_pixel [get_nets clk_pixel]
create_clock -period 37.037 -name clk_27 [get_nets clocks.clk_27]
create_clock -period 37.037 -name tvpa_sclk [get_nets mix.a_clk]
create_clock -period 37.037 -name tvpb_sclk [get_nets mix.b_clk]
