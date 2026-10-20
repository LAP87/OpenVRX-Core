# Bench bitstreams 2026-10-20

Built with gateware/build.sh (yowasp yosys / nextpnr-himbaechel-gowin 0.11.1, Apicula 0.32), seed and options in each .build.json. Load with: openFPGALoader -b tangnano20k <file>.fs

| File | Source | What |
|---|---|---|
| m2u_uart27.fs | bench/uart-check | fixed UART line from the 27 MHz clock |
| m2u_uart64.fs | bench/uart-check | the same line from the SDRAM PLL clock |
| m2a_memtest.fs | main 8dff8d1 | SDRAM memory test (BRINGUP 2.1) |
| m3_probe.fs | main 8dff8d1 | wiring probe for the decoders |
| m0_testpattern.fs | fix/m0-bounce a169638 | test pattern with the edge fix (task 46) |

This branch holds build outputs only; it is not part of main.
| m2a_memtest_ioreg0.fs | main b440ece, IOREG=0 | the memory test without the I/O-cell registers: the discriminator for the scrambled report (task 47) |
