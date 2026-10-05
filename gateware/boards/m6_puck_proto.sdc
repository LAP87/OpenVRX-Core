# The board clock is 27 MHz; twice that is asked of its domain (the menu arithmetic in puck_ui.v does
# not reach 75 MHz). build.sh asks 75 MHz of every clock not named here.
create_clock -name clk27 -period 18.5 [get_nets {clocks.clk_27}]
