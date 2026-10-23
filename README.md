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
| m4_dual_mix_low.fs | build/m4-low | M4 in the low-latency mode (no SDRAM field store), decoders at 5C |
| m4_dual_mix_low_tvp5d.fs | build/m4-low | the same for decoders at 5D: the first-picture bitstream for the CP803A module (council 2026-10-21) |
| m6_puck_proto.fs, m6_puck_proto_hdmi.fs | main fcad832 | M6 with the flight view (task 42), decoders at 5C, DVI and HDMI=1 |

| cd90e6e/m3_probe.fs, m4_dual_mix.fs, m6_puck_proto.fs | main cd90e6e (merged as e71a268), night pass 2026-10-21/22 | tasks 49-52: SDRAM DQ capture as a plain flop with the self-test (M4: LED 1/2 for 3 s, M6: last log digit), tvp_ctrl tries 5C and 5D itself, unknown decoder status counts as bad, small findings. On the bench 2026-10-22: M4 showed the first camera picture, M6 answered 2 in the self-test |
| ce2f3ad/m6_puck_proto_devcmd.fs | main 26e6fa2 (task 58, code ce2f3ad; built from a tree with its source hashes) | M6 with DEVCMD=1: commands on the UART (pin 70), 101-byte log line, status line; 115200 baud. Not tried on the board |
| 18f2ab5/m6_puck_proto_devcmd.fs, m6_puck_proto_devcmd_baud921600.fs | m6/field-dump 18f2ab5 (task 59) | M6 with DEVCMD=1 and the field dump (D decoder A, F mixer output), at 115200 and at UART_BAUD=921600 (divider 29: 931034 baud). Not tried on the board |
