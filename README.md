# Bench bitstreams 2026-10-20

Built with gateware/build.sh (yowasp yosys / nextpnr-himbaechel-gowin 0.11.1, Apicula 0.32), seed and options in each .build.json. Load with: openFPGALoader -b tangnano20k <file>.fs

| File | Source | What |
|---|---|---|
| m2u_uart27.fs | bench/uart-check | fixed UART line from the 27 MHz clock |
| m2u_uart64.fs | bench/uart-check | the same line from the SDRAM PLL clock |
| m2a_memtest.fs | build/ioreg-default-off (main 8dff8d1 + build.sh: no I/O-cell registers) | SDRAM memory test (BRINGUP 2.1); readable, rs=5 clean on the board 2026-10-21 |
| m3_probe.fs | main 8dff8d1 | wiring probe for the decoders |
| m0_testpattern.fs | fix/m0-bounce a169638 | test pattern with the edge fix (task 46) |

This branch holds build outputs only; it is not part of main.
| m2a_memtest_ioreg0.fs | main b440ece, IOREG=0 | the memory test without the I/O-cell registers: the discriminator for the scrambled report (task 47) |
| m2u_uart64_ioreg1.fs | bench/uart-check, IOREG=1 | the SDRAM-PLL UART check built with the I/O-cell registers, as M2a is (task 47) |
| m4_dual_mix.fs | build/ioreg-default-off | two decoders + mixer, no I/O-cell registers (2026-10-21) |
| m2_moneagle_color.fs | build/ioreg-default-off | one decoder via SDRAM, no I/O-cell registers |
| m6_puck_proto.fs | build/ioreg-default-off | puck prototype (old menu), no I/O-cell registers, seed 2 |

The earlier m2a_memtest_ioreg0.fs equals the new m2a_memtest.fs in options; m2u_uart64_ioreg1.fs and the old IOREG=1 builds are kept as the evidence of the scrambled output.
| m3_probe_tvp5d.fs | build/tvp-addr | the probe for decoders at I2C address 5D (the red CP803A module): i2c OK, 27 MHz, NTSC timing on the board 2026-10-21 |
| m4_dual_mix_tvp5d.fs | build/tvp-addr | M4 for decoders at 5D |
