# Gateware (Tang Nano 20K, Verilog)

> Del av [OpenVRX](https://github.com/LAP87/OpenVRX). Sökvägar som `../research/` och `../design/` syftar på den ursprungliga samlade mappen: forskning finns nu i OpenVRX-navet, kortdesignen i OpenVRX-Puck.

Plan: `docs/GATEWARE_PLAN.md` i navet (OpenVRX). Licens: CERN-OHL-S-2.0, se `LICENSE` i repots rot.

## Status

### Nuläge

Hela sviten: **892 test på `9cfdf51` (uppgift 68/69 på bänken 2026-10-27: `cvbs_capture.v` sveper nivåskiljaren tills den hittar synken, skiljaren på ett 8-sampels medelvärde, periodmätningens sampelmiss, M7-proben `top/m7_digin_probe.v`), alla gröna**, 1 715 s, sammanslaget som `518abfb`. Före det: **889 test på `2fdc82e` (uppgift 69: kanal B:s eget lås ur `cvbs_capture.v` som hälsa i mixern och i M4:s hjärtslag med `DIGIN=1`, `mixer2.v` `b_lock`, `sim/test_mixer_digital.py`), alla gröna**, sammanslaget som `c5e66c2`. Före det: **885 test på `792d360` (uppgift 67: genomförbarhetsmodellen `iq_demod_ref.py` med `test_iq_demod.py`), alla gröna**, sammanslaget som `b9fc11b`. Före det: **879 test på `6b845e8` (uppgift 64: den digitala ingången `cvbs_capture.v` med modell och test, byggvalet `DIGIN=1`), alla gröna**, sammanslaget som `3703071`. Före det: **871 test på `4b2e814` (uppgift 59: fältdumpen över UART, `field_dump.v`, byggvalet `UART_BAUD`, `fielddump.py`), alla gröna**, 1 719 s. Före det: **862 test på `ce2f3ad` (uppgift 58: kommandokanalen i M6 bakom byggvalet `DEVCMD=1`, `uart_rx.v`, statusraden, `m6ctl.py`), alla gröna**, 1 772 s. Före det: **844 test på `cd90e6e` (uppgift 52: felräknarna mättar, M3:s fältantal ur radnumreringen, M6-loggens hjärtslag, OSD-spegelns reset, flashens tidsgräns, lysdiod 0 1/2 Hz), alla gröna**, 1 795 s. Före det: **838 test på `54adde2` (uppgift 51: okänd dekoderstatus räknas som dålig, `dec_bad.v`; statusen läses var 5:e ms), alla gröna**. Före det: **835 test på grenen `tvp/addr-search` (uppgift 50: `tvp_ctrl.v` provar båda I2C-adresserna per dekoder, M3 visar den som svarar), alla gröna**, 1 770 s. Före det: **828 test på grenen `sdram/ioreg-pure` (uppgift 49: DQ-infångningen som ren vippa, `IOREG=1` med `iob_regs.py --strict` som grind, SDRAM-självtestet i M4 och M6), alla gröna**, 1 733 s. Före det: **818 test på `0717ad7` (byggvalet `LOW=1` för M4, uppgift 53), alla gröna**, 2 032 s; sammanslagen som `f049aab`. Före det: **814 test på `7354865` (uppgift 42: flygvyn, menyn med en post per skärm, sparstatus, `HOLD`, pilknapparna; ägarens ja 2026-10-21), alla gröna**, 2 005 s; sammanslagen som `2591cec`; M6 byggt ur den utan I/O-cellregister: 13 993 LUT4 (DVI) och 14 262 (`HDMI=1`), 29 BSRAM, lägsta maxfrekvens efter routning `sd_clk` 106,88 / 88,38 MHz. Före det: **803 test på `bed8789` (byggvalet `TVP_ADDR=5D`: dekodrar på I2C-adress 5D, den röda CP803A-modulen), alla gröna**, 1 664 s; sammanslagen som `5142894`. Före det: **799 test på `06d7522` (uppgift 47: I/O-cellregistren av som standard efter bänken, UART-kontrolltopparna, `tools/iob_regs.py`), alla gröna**, 1 624 s; sammanslagen som `734ae58`; snabblistan 720 gröna efter att tre byggartefakttest bytte parameter-id. Före det: **799 test på `a169638` (uppgift 46: kvadraten i M0 begränsas till kanten; första felet hittat på hårdvara, hemmabänken 2026-10-20), alla gröna**, 1 654 s i en omgång; sammanslagen som `61ec85b`. De två nya testen är `sim/test_m0_motion.py` (5 000 bildrutor mot en modell, negativ kontroll = koden som den var). Före det: **797 test på `52c2ffe`, alla gröna** med `tools/run_suite.py` (en process per simuleringstest, tio åt gången, 995 s i en omgång, varav de formella bevisen 986 s), ingen delad byggkatalog. Andra granskningens tre strikta xfail-test (Core #21, #22, #23) är vanliga test sedan uppgift 33, 34 och 35; uppgift 35 gav HDMI-läget omfånget `FULL`/`LTD` i M6-menyn ("Omfånget i HDMI-läget" under M0). Snabbsviten före varje commit: 720 av testen på 204 s, med 15 av de 21 testen från uppgift 35 (listan från 2026-10-18, "Snabbsviten före varje commit" under Verktyg). Före det: 776 test med 775 gröna och 1 xfail på `0f8548c` (uppgift 33–34), och 774 test med 771 gröna och 3 xfail på `76ceedf`. Granskningens rättningar RS-1 och FL-1 kom in med `8a71a0a`. Före det: 772 test med 769 gröna på `d3d9753`, och 761 gröna på `88f5b90` efter uppgift 21. 2026-10-14 ändrades mixerns två ingångs-FIFO:er till block-RAM (`async_fifo.v` `RD_REG`), så att M6 med `HDMI=1` och `VINTERP=1` går att placera ("M6 med HDMI och VINTERP" under "Bygget av M6"); M4 och M6 är ombyggda. Före det: 757 gröna på `2b67dea`, och samma 757 på `bf05ac0` i Codex körning, rootaccepterad 2026-10-13 (navets `docs/overnight/2026-10-08/STATUS.md`). På kortet (Tang Nano 20K rev 3923, en TVP5150-modul; navets `docs/BANK_2026-10-2*.md`): M0 2026-10-20, M2a och M3 2026-10-21, M4 med första kamerabilden och M6 med självtest `2` 2026-10-22; två dekodrar och mixern är inte provade.

| Topp | Byggd ur | Seed | Siffror |
|---|---|---:|---|
| M4 med `DIGIN=1` (kanal B = C5VRX:s sampelbuss, `cvbs_capture.v`) | grenen `digin/b-lock` (Fable, 2026-10-26, uppgift 69; `digin/cvbs-capture` 2026-10-24, uppgift 64) | 0 | 6 864 LUT4, 31 BSRAM; `mix.b_clk` (40 MHz-domänen) 99,71 MHz, `sd_clk` 141,82, övriga över 130; M4 utan valet 6 046 LUT4, 29 BSRAM (`sd_clk` 128,32). Uppgift 64 gav 6 822 LUT4 och `mix.b_clk` 84,53 MHz. Simulerat och byggt; inte provat på kortet |
| M6 med `DEVCMD=1`, och med `DEVCMD=1 UART_BAUD=921600` | `18f2ab5` (Opus, 2026-10-23, uppgift 59; RTL och byggindata samma i `4b2e814`) | 2 | 15 641 / 15 526 LUT4, 31 BSRAM; lägsta maxfrekvens 97,14 MHz; manifesten verifierade mot källorna. Inte provade på kortet (UART-bryggan tyst) |
| M6 med `DEVCMD=1` | `ce2f3ad` (Opus, 2026-10-23, uppgift 58; byggt ur ett arbetsträd vars källhashar är `ce2f3ad`:s, `build_manifest.py verify --root`) | 2 | 15 064 LUT4, 29 BSRAM; lägsta maxfrekvens 109,65 MHz (`clocks.clk_27`). Inte provad på kortet: kortets UART-brygga var tyst hela natten (navets `docs/BENCH.md`, "När loggen tystnar") |
| M6 (standardval) | `e71a268` (Opus, 2026-10-23) | 2 | samma bitström som ur `cd90e6e`, bit för bit (SHA-256 `130d2234…1673`): bygget går att återskapa. Laddad på kortet med manifestkontroll |
| M3, M4, M6 (standardval) | `cd90e6e` (Opus, 2026-10-22, uppgift 52) | 0, 0, 2 | 2 772 / 6 043 / 14 358 LUT4; lägsta maxfrekvens 116,00 (M3 `pb.clk`) / 127,52 (`sd_clk`) / 106,76 MHz (`sd_clk`); manifesten verifierade. M4 och M6 körda på kortet 2026-10-22 (kamerabild i M4, självtest `2` i M6; navets `docs/BANK_2026-10-22.md`); inte rootaccepterade |
| M4, M6 (standardval) | `60af072` (Opus, 2026-10-22, uppgift 51) | 0, 2 | 6 035 / 14 347 LUT4; lägsta maxfrekvens `sd_clk` 123,40 / 89,58 MHz; manifesten verifierade. Inte provade på kortet, inte rootaccepterade |
| M3, M4, M6 (standardval) | `cb1e4db` (Opus, 2026-10-21, uppgift 50: adressökningen) | 0, 0, 2 | 2 824 / 6 017 / 14 151 LUT4; lägsta maxfrekvens 117,50 (M3 `pa.clk`) / 124,88 (`sd_clk`) / 91,70 MHz (`sd_clk`); manifesten verifierade. Inte provade på kortet, inte rootaccepterade |
| M2a, M4, M6 med och utan `IOREG=1` | `669b2ed` (Opus, 2026-10-21, uppgift 49) | 0, 0, 2 | 2 351 / 5 981 / 14 182 LUT4; 33 / 49 / 52 rena vippor i I/O-cellerna med `IOREG=1`; tabellen under "I/O-register i I/O-cellerna". Inte provade på kortet, inte rootaccepterade |
| M2a, M2, M4, M6 utan I/O-cellregister (ny standard) | `06d7522` (Fable, 2026-10-21, uppgift 47) | 0, 0, 0, 2 | 2 373 / 3 404 / 5 810 / 13 190 LUT4; lägsta maxfrekvens `sd_clk` 90,06 / 119,05 / 125,66 / 100,80 MHz (M4 `clk_pixel` 117,70, M6 `clocks.clk_27` 110,08). M2a ur det här bygget läst på kortet: `rs=5 err=00000000` (BRINGUP 2.1). Inte rootaccepterade |
| M0 | `a169638` (Fable, 2026-10-20, uppgift 46: kanträttningen) | 0 | 793 LUT4; `clocks.clk_27` 311,62 MHz, pixelklocka 154,11 MHz. Samma rättning kördes på kortet hemma 2026-10-20 som en privat bänkversion av `bf05ac0` (navets `docs/bench/HANDOFF_CLAUDE_2026-10-20.md`); det här bygget är inte provat på kortet |
| M6 med `HDMI=1 VINTERP=1` | `c852cb9` (Opus, 2026-10-18; samma byggindata som `52c2ffe`); med `--mspi_as_gpio` | 2 | 13 997 LUT4, 33 BSRAM; lägsta maxfrekvens 115,41 MHz (`sd_clk`); "M6 med HDMI och VINTERP" under "Bygget av M6". Inte rootaccepterad |
| M0, M4, M6, var och en med och utan `HDMI=1` | `52c2ffe` (Opus, 2026-10-18, uppgift 35); M6 med `--mspi_as_gpio` | 0, 0, 2 | utan / med `HDMI=1`: 789 / 950, 5 810 / 5 993, 13 190 / 13 544 LUT4; M4 och M6 29 BSRAM; lägsta maxfrekvens 161,16 / 211,10, 115,06 / 123,00, 103,80 / 103,80 MHz; tabellen under "Omfånget i HDMI-läget". Inte rootaccepterade |
| M4, M6 (standardval) | granskningsgrenen, sammanslagen i `8a71a0a` (Fable, 2026-10-17; samma RTL som `main` nu); M6 med `--mspi_as_gpio` | 0, 2 | 5 810 / 13 259 LUT4, 29 BSRAM var; lägsta maxfrekvens 115,06 / 91,70 MHz. Inte rootaccepterade |
| M0, M4, M6 (standardval), M4 och M6 med `HDMI=1 VINTERP=1` | `2c64672` (Opus, samma byggindata som `88f5b90`); M6 med `gowin_pack --mspi_as_gpio` | 0, 0, 2 | 789 / 5 831 / 13 113 LUT4; M4 och M6 med båda valen 6 427 / 13 719; lägsta maxfrekvens 152,35 / 129,17 / 112,07 MHz, med båda valen 116,33 / 99,00 MHz. Inte rootaccepterade |
| M0, M4, M6 (standardval) före FIFO-ändringen | `bf05ac0`, byggda av Codex och rootaccepterade 2026-10-13 | 0, 0, 2 | 789 / 8 245 / 15 505 LUT4; lägsta maxfrekvens 154,58 / 98,95 / 104,58 MHz; M6:s 27 MHz-domän 132,28 MHz |
| M6 | `0958a52` (Opus; samma byggindata som `bf05ac0`, samma LUT4 och 27 MHz-siffra) | 2 | "Sparade inställningar" under M6; utan dem ur `9023ab1` under "RSSI" |
| M4 | `f78fe82` (före `ext_weak`) | 0 | "Den varierande raden" under `LOW` |
| M0; M4, M6 med `HDMI=1` | `4ad5a68` (M4 före `ext_weak`, M6 utan RSSI, SCAN och flash) | 0 (M6: 2) | "DVI eller HDMI" under M0 (äldre tabellen) |
| M4, M6 med `VINTERP=1` | `fc267a8` (samma) | 0 (M6: 2) | "Interpolation i höjdled" under bildvägen |
| M2, M2s | `0da655d` | 0 | "Störningskampanjen C3 avslutad" nedan |
| M2a | `dc307bc` | 0 | "I/O-register i I/O-cellerna" nedan |
| M3; M6 seed 0–3 | `94a2b32` | 0; 0–3 | "Klockroutningen, 2026-10-12" nedan |
| M1, M1s | `62a69be` | 0 | milstolpetabellen |

Alla klockor över kravet 75 MHz efter routning; HDMI-paren i M2, M2s, M4 och M6 packas som i M0. Rootaccepterat av Codex: sviten och M0/M4/M6 med standardval på `bf05ac0`, Codex egna optionsbyggen (`HDMI=1`, `VINTERP=1` och båda) på `46a1e4f`, och `HDMI=1` respektive `VINTERP=1` på `bf05ac0`. Byggena av M2, M2s, M2a, M3, M1 och M1s, och byggena ur `2c64672`, är gjorda av Opus och har ingen rootacceptans i navets STATUS. Ändrat 2026-10-12: parallellkörare och byggkatalogsrevision ("Hela sviten parallellt"), ingen BUFG-flagga på dekodrarnas SCLK, I/O-register i I/O-cellerna för SDRAM-topparna, C3-kampanjen avslutad med en rättning i `fb_sdram.v`, marginalkontroller för de formella bevisens öppna punkter 4 och 5.

Milstolpetabellen nedan har samma byggen. Avsnitten om C2, C1 och C3 efter den är kvitton från sina datum; det de anger som återstående (260-frökampanjen, M6 med seed 2) är gjort 2026-10-12.

### TV/VCR-menyn, källa `c3fda21` (C2)

M6 kan begära TV eller VCR för båda dekodrarna via filterfältet i menyn. Styrenheten håller ett pågående skrivvärde fast, registrerar det faktiskt kvitterade värdet per dekoder och försöker igen efter parad pollning vid NACK. OLED, OSD och USB-logg visar det begärda menyvalet; loggen är 85 byte inklusive CRLF sedan RSSI-fälten kom 2026-10-13 (62 byte före) och `snowlog.py` bevarar de äldre radformaten.

Den frysta sviten gav **604 pass i 39 filer**, utan fel, skips eller xfails, på **5411,439 s (1:30:11)**. Alla 570 tidigare testnoder finns kvar och samtliga 157 källhashar är oförändrade. Root granskade 19 cocotb-rapportidentiteter, 7 formella bevis och 14 verkliga negativa motexempel. Riktad C2-verifiering gav 56 pass och två subtester; nio isolerade gamla BUS-/parser-vakter underkänns för de avsedda semantiska felen. Svitens acceptans-SHA-256: `c783407e79a31e9a09f3bc82f76debff1160aebee80091c25368d261d1c09bfc`.

Färska byggen från samma källa, med beslutade seeds och oförändrade stift, IOB och SDC:

| Topp | Seed | Maxfrekvenser efter routning (MHz), krav 75 för alla klockor | Manifest SHA-256 |
|---|---:|---|---|
| M0 | 0 | pixel 149,37; 27 MHz-domän 359,84 | `23063bf9ae841a126293ed9123a5edfff95a4632fc3e0edf7a89fd64a6d73e78` |
| M4 | 0 | A 149,54; B 161,55; 27 MHz-domän 215,7; SDRAM 101,69; pixel 115,75 | `f839035d920ab3fb8089c72d3b3514492f123ce374e7f2838754cf01831db7b9` |
| M6 | 2 | A 150,22; B 131,08; 27 MHz-domän 128,3; SDRAM 104,85; pixel 120,88 | `d2b55005f80878b99555abe1220d51a76d10b46f66945f08f77433d1a24b667e` |

Samtliga 24 arkiverade byggartefakter och deras manifest är granskade. Alla fyra HDMI-par matchar M0:s IOB-fuses i både M4 och M6. En ny slutkampanj återstår; den gamla kampanjens seed 1345 är fortfarande FAIL med 72 kontrollerade rader mot minst 144. Ingen FPGA-hårdvara eller TV/VCR-bildskillnad är mätt.

### Tidigare mixergräns, källa `6c12099`

Ett helt utelämnat fält kunde förbruka F-gränsen utan att skicka ord. När nästa synliga fält började med ett högre radnummer än det föregående slog BUF och LOW ihop dem. Mixern håller nu gränsen väntande tills en rad skickas; flera helt utelämnade fält ger en enda synlig växling. Kanalval, radurval och dekoderns F-bit är oförändrade.

Den frysta sviten gav **570 pass i 39 filer**, utan fel, skips eller xfails, på **3852,554 s (1:04:13)**. Alla 157 källhashar är oförändrade; 19 cocotb-rapporter, 7 formella bevis och 14 negativa motexempel är granskade. Riktad mixer/backend-verifiering gav 167 pass. Den verkliga gamla RTL-regeln underkänns av kontrollen på skickade ord med riktig BT.656-släcklucka. Svittens acceptans-SHA-256: `abe0f7de09f0500f3edecdc70a3ad2571e76463bf531a67c3390a788bf890692`.

Färska byggen från samma källa, utan pin-, IOB-, SDC- eller seedbyte:

| Topp | Seed | Maxfrekvenser efter routning (MHz), krav 75 för alla klockor | Manifest SHA-256 |
|---|---:|---|---|
| M0 | 0 | pixel 147,56; 27 MHz-domän 325,63 | `fa3b54c95cc3fe9448f0387d7cd734074a0bdbf1a04a57b8abf98f9a83c48ca1` |
| M4 | 0 | A 134,44; B 150,40; 27 MHz-domän 224,57; SDRAM 113,08; pixel 103,84 | `fe33bddd07834312f871900e7d0c6c5ed0b4bc09b47e1940a63a6f22aa145b95` |
| M6 | 2 | A 154,32; B 113,78; 27 MHz-domän 125,47; SDRAM 106,10; pixel 124,66 | `7a2317922e96c3039d3ca51d1c6b1856b6dea184b20215ae4b6554358967eea0` |

Alla fyra HDMI-par matchar M0:s IOB-fuses. Vid denna B-acceptans återstod ny slutkampanj och det separata TV/VCR-paketet. Ingen FPGA-hårdvara var verifierad.

| Milstolpe | Toppmodul | Byggd | Verifierad |
|---|---|---|---|
| M0 — testbild 720p60 på kortets HDMI | `top/m0_testpattern.v` | ✔ `build/m0_testpattern.fs` (788 LUT, 3 %; pixel 152,39 MHz; DVI, se M0) | Simulering av TMDS och tidsbas |
| M1 — Moneagles TVP5150AM1 → HDMI (luma, 360×240, 720p60), inbäddad BT.656-synk | `top/m1_moneagle_view.v` | ✔ `build/m1_moneagle_view.fs` (809 LUT, 44/46 BSRAM) | Hela ingångsvägen mot facit |
| M1s — samma, separata synksignaler (HSYNC/VSYNC/AVID) | `top/m1s_moneagle_view_sync.v` | ✔ `build/m1s_moneagle_view_sync.fs` (1 054 LUT, 44/46 BSRAM) | Båda polariteter och bytefaser |
| **M2 — full upplösning i färg via SDRAM, fältminne med fyra buffertar** | `top/m2_moneagle_color.v` (kärna `rtl/m2_core.v`) | ✔ `build/m2_moneagle_color.fs` (3 474 LUT 16 %, 17 BSRAM, 2 PLL; SDRAM 125,79 MHz, pixel 120,89 MHz) | Tre klockdomäner + SDRAM-modell med databladets tider: SDRAM-innehåll och RGB-pixlar mot modell, inga protokollfel i minnesmodellen |
| M2s — som M2 men separata synksignaler | `top/m2s_moneagle_color_sync.v` (`m2_core` med `DISCRETE_SYNC=1`) | ✔ `build/m2s_moneagle_color_sync.fs` (3 653 LUT 17 %, 17 BSRAM; SDRAM 111,66 MHz) | Mottagaren testad i M1s; kombinationen bara syntes/PnR |
| **M2a — minnestest av SDRAM** (ingen bild; en rad per läspunkt över USB) | `top/m2a_memtest.v` (kärna `rtl/memtest_core.v`) | ✔ `build/m2a_memtest.fs` (2 393 LUT 11 %, 0 BSRAM, 1 PLL; SDRAM 92,68 MHz) | UART-raderna avkodade mot SDRAM-modellen: rätt läspunkt pekas ut för sex kombinationer av kortfördröjning och klockfas (`sim/test_memtest.py`) |
| **M3 — uppstartsprob** för M4/M6-kopplingen (ingen bild; en rad per dekoder och sekund över USB) | `top/m3_probe.v` | ✔ `build/m3_probe.fs` (2 561 LUT 12 %, 0 BSRAM; 27 MHz-domän 196,66 MHz, dekoderklockorna 147,36 och 179,63 MHz) | Rapportraderna mot en frisk och en felkopplad dekoder, lysdioderna och RX5808-skrivningen på stiften (`sim/test_probe.py`) |
| **M4 — två egna TVP5150-moduler + radvis mixer** | `top/m4_dual_mix.v` | ✔ `build/m4_dual_mix.fs` (8 266 LUT 39 %, 25 BSRAM; SDRAM 104,87 MHz, pixel 147,36 MHz) | Mixern mot facit, beslut för beslut och ord för ord, på fält med riktig släcklucka och vid parningsfönstrets kant (33 gröna test i den aktuella sviten; `sim/test_mixer.py`); fältminnet och visningen mot facit (`sim/test_fb.py`); I2C mot slavmodeller; RESETB, lysdioder och RX5808-skrivning på toppmodulens stift (`sim/test_top_pins.py`); hela kedjan från två BT.656-strömmar till pixlarna under slumpade störningar, varje block mot sin modell (`sim/test_fuzz_chain.py`, kampanjen i `sim/FUZZ_2026-10-07.md`) |
| **M5 alt. C — Moneagle → 1080p60 BT.1120 → LT8618SX** (ingår inte, se M5-avsnittet) | `top/m5c_moneagle_1080p.v` | byggd 2026-10-04 ur källor som inte ingår här; går inte att bygga ur det här repot (3 565 LUT 17 %, 16 BSRAM; pixel 206 MHz mot 148,5) | BT.1120-strömmen avkodad som av en mottagare över en hel bild; LT8618SX-sekvensen mot sidindelad I2C-modell |
| **M6 — puckprototyp steg 1** (M4 + RX5808-styrning + OLED-meny + OSD i videon + mätlogg) | `top/m6_puck_proto.v` | ✔ `build/m6_puck_proto.fs` (12 736 LUT 61 %, 25 BSRAM; SDRAM 101,06 MHz, pixel 129,90 MHz, 27 MHz-domän 123,02 MHz; seed 2, se "Bygget av M6") | Meny, SPI, OLED, snö-mätare, brusmått, OSD och UART-logg mot modeller (`sim/test_puck_ui.py`, `sim/test_snow_stats.py`, `sim/test_noise_stats.py`); toppmodulens stift som i M4 (`sim/test_top_pins.py`); M4-delen som ovan |

**Inget är provat på riktig hårdvara.** LUT, BSRAM och klockornas Fmax ovan kommer från nextpnrs slutrapport efter routning, med kravet 75 MHz för alla klockor. Tabellens siffror för M0, M4 och M6 är från byggena ur `4ad5a68`; aktuella byggen ur `bf05ac0` står under "Nuläge". M2 och M2s är byggda ur `0da655d`, M2a ur `dc307bc`, M3 ur `94a2b32` (alla 2026-10-12); M1 och M1s 2026-10-06 ur `62a69be`. HDMI-paren i M2, M2s, M4 och M6 har samma IOB-fuses som M0.

### Historiska C1-byggen (`3aed0b7`, 2026-10-09)

C1-källan byggdes 2026-10-09. M4 seed 0 och M6 seed 3 klarade routning med krav på 75 MHz för alla fem klockor:

| Topp | Seed | LUT4 | BSRAM | Maxfrekvens efter routning (MHz) | Manifest SHA-256 |
|---|---:|---:|---:|---|---|
| `m4_dual_mix` | 0 | 8 271 | 25 | `mix.b_clk` 133,51; `mix.a_clk` 129,53; `clocks.clk_27` 204,96; `sd_clk` 91,26; `clk_pixel` 111,88 | `08e83fd2ce31e185f3d4409208c7a9a87838baa6abde4f32a56390816857b525` |
| `m6_puck_proto` | 3 | 12 575 | 25 | `mix.b_clk` 116,36; `mix.a_clk` 140,29; `clocks.clk_27` 118,47; `sd_clk` 99,54; `clk_pixel` 124,52 | `f33dc2a58c2e346cd4f9b80b56dcee4ae6c26e21e611bbe81cded1687eb68891` |

På samma C1-källa misslyckades M6 seed 2 under global klockroutning med `Can't route the clocks.clk_27 net`; seed 3 routade. `boards/m6_puck_proto.seed` är fortfarande 2. Reproducera det godkända C1-bygget med `SEED=3 FREQ_MHZ=75 gateware/build.sh m6_puck_proto`. Ingen pin-, IOB-, SDC-, BUFG- eller BOM-ändring gjordes för seedbytet. M6 med seed 2 är ett separat senare krav i C2 och är inte styrkt av seed 3.

C1:s frysta fullsvit gav 447 pass, noll fel, skips eller xfails på 5 376,375 s (1:29:36,375). Den råa körjournalens status är fortfarande `FAIL_SOURCE_CHANGED`: de enda tilläggen var 19 genererade cocotb `.result.xml`-filer. Den separata acceptanskontrollen verifierade hash för samtliga 172 frysta indatafiler och accepterade de 447 pytest-utfallen utan att ändra rå sammanfattning. Formell körning gav 7 `PROVEN`-bevis och 14 förväntade motexempel i negativa kontroller på 572,163 s. Fable rapporterade 433 pass på `e113cf6` och stängde Core #17/#18. Äldre `aece6eb`-utfall (432 pass, 2 xfail på 1:26:02) och `7cc4eda`-baslinjen (395 pass, 1 xfail på 1:25:56) är historiska. Kör ett tungt jobb i taget, enligt navets `AGENTS.md`.

### Accepterad C3-källa `8d7b0e9` (2026-10-09)

Den frysta sviten gav **490 pass**, inga fel, skips, xfails, xpasses eller saknade utfall, på 4 861,264 s (1:21:01,264). Alla 39 testfiler kördes och samtliga 157 indatahashar är oförändrade. Formaltestet gav 7 bevis och 14 verkliga negativa motexempel. Acceptanskvittots SHA-256 är `0ad1443dc8927ba6a721044b1e1b13a26807d3b41e225915a517f65f17111de0`.

M4 seed 0 och M6 seed 3 klarade routning med krav på 75 MHz för samtliga fem klockor:

| Topp | Seed | LUT4 | BSRAM | Maxfrekvens efter routning (MHz) | Manifest SHA-256 |
|---|---:|---:|---:|---|---|
| `m4_dual_mix` | 0 | 8 230 | 25 | `mix.b_clk` 163,16; `mix.a_clk` 137,49; `clocks.clk_27` 228,73; `sd_clk` 101,46; `clk_pixel` 104,80 | `135aedd90adfb6bd2ef021fd80fbaf701f73b73c650e20336abc2b7c4b049c53` |
| `m6_puck_proto` | 3 | 12 625 | 25 | `mix.b_clk` 137,46; `mix.a_clk` 142,65; `clocks.clk_27` 119,70; `sd_clk` 108,87; `clk_pixel` 127,84 | `fc7f2e880052f012de6e0105479f16c9f734be52a2ee24740380c5bc6669b42a` |

M0-referensen och alla fyra HDMI-par har godkända manifest/fuse-kontroller; 24 byggartefakter är arkiverade med acceptanskvittot. M6:s standardseed är fortfarande 2. Dessa seed-3-resultat ersätter inte C2:s senare seed-2-krav. En ny 260-frökampanj på accepterad slutlig main återstår. Inget är provat på hårdvara.

### Accepterad C3-displaychecker `79b1406`

Den frysta regressionen gav **566 pass i 39 testfiler**, utan fel, skips, xfails, xpasses eller saknade utfall, på **1:21:34 (4893.875 s)**. Alla 157 frysta källhashar är oförändrade; 7 formella bevis och 14 negativa motexempel passerar. Acceptanskvittots SHA-256: `a1944cc5b161fe12535cee25acb743a91455c3617d1260ff0bde3ce2e0746847`.

Före ett lägesbyte undantas en bild från displaykontrollen bara om dess aktiva bild överlappar bytet. Radlängden kommer från bildens observerade NTSC/PAL-timing; okänd timing är ett fel. Hela bildens tidigare undantag för X/Z-kontrollen och fönstret efter bytet är oförändrade. 23 nya rena kontroller täcker gränserna, inklusive sista aktiva pixeln, fel ringord och fel källmappning. 50 sparade kampanjspår passerar. Native-omspelningen av seed 1249 har byte-identiskt stimulus och råspår, 144 kontrollerade rader och inga findings/known/edges/notes. Den tidigare körningens FAIL med 72 rader bevaras.

Fullsvitens efterkontroll stannade först på `/` i ett rent Python-testnamn. Separat eftervalidering filtrerar bort XML-kandidater som saknar cocotb-modul; alla 19 verkliga XML-identiteter och den strikta SDRAM-kontrollen behålls. Testerna kördes inte om och källan ändrades inte. Produktions-RTL och de 24 arkiverade byggartefakterna är oförändrade; M4 seed 0/M6 seed 3 återanvänds genom identiska byggindata. Ny 260-frökampanj och C2:s M6 seed 2 återstår. FPGA-kedjan är inte verifierad på hårdvara.

### Tidigare accepterat C3-bänkpaket `0dcff5d`

Den frysta regressionen gav **543 pass** i **39 testfiler**, utan fel, skips, xfails, xpasses eller saknade utfall, på **1:23:13 (4993.121 s)**. Alla 157 frysta källhashar är oförändrade. Acceptanskvittots SHA-256: `81eb8e3813a5f0099e06e450257e274df77edd2fdd87a4f880b9a830e8493d7b`. Formalgrinden gav 7 bevis och 14 verkliga motexempel. Ändringen gäller bänk och checker; produktions-RTL är oförändrad.

Efter `TAIL` väntar bänken in vertikalsläckningen och stoppar pixelklockan på följande negativa flank. SDRAM-klockan fortsätter medan CDC-signaler och redan accepterade läsningar och skrivburstar blir inaktiva; fyra inaktiva SDRAM-klockor krävs i följd. Dräneringen har en simulerad tidsgräns och ett slutkvitto för tillstånd och klockor; timeout är ett fel. Varje `V`-bild måste bära `ll_alive` och `triggered`, och LOW-video tillåts bara när båda är sanna. `M`-raden kontrollerar direkt att videon släckts vid lägesbytet. De tio riktade körningarna omfattade fungerande baslinjer, samma stimuli för baslinje och felvarianter av alive-/triggergrinden, switch-clear-fel och blockerad dränering.

De sex fuzzinvarianterna, strikt SDRAM-läsningskontroll och ringadressbindning är kvar; `LOW_LOCK_GROUPS = ()`, alltså inga #17-masker. En äldre avbruten kampanj med 23 sparade rader (17 PASS, 6 FAIL) bevaras för bänk-triage. En ny kampanj med 260 frön på accepterad slutlig main återstår. Den analoga AIO/Moneagle-kamerabilden verifierar inte FPGA-kedjan; FPGA:n är inte provad på hårdvara.

M4 seed 0 och M6 seed 3 ovan återanvänder de godkända `8d7b0e9`-byggena: deras befintliga indata (46/47 poster) matchar de arkiverade manifesten byte för byte. Ingen ny routning eller nya FPGA-byggsiffror hävdas för `0dcff5d`.

## Moduler (`rtl/`)

| Modul | Vad | Test |
|---|---|---|
| `bt656_rx.v` | BT.656-mottagare + mått per rad (synkord med felrättning, radlängd, HF-energi). Radnummer räknas från vertikalsläckningen (två synkord i följd med V = 1), inte från F-biten. Felräknarna för synkord (rättade och trasiga) mättas vid 255 per rad (sedan 2026-10-21; förut slog de runt vid 256, så raden efter en lång följd trasiga koder såg felfri ut; `sim/test_bt656_rx.py::test_bt656_rx_xy_bad_saturates_and_check_is_tested`). Antalet aktiva byte mättas vid 2 047: en rad vars EAV har tappats löper vidare in i nästa, och dess första 1 440 byte förblir dess egna (till 2026-10-07 slog räknaren runt vid 2 048, så orden började om på 0 och raden räknades som ofullständig eller fick ord ur senare rader; hittat med `sim/test_fuzz_chain.py`) | `sim/test_bt656_rx.py`: bitexakt mot `model/bt656.py`; `sim/test_mixer.py::test_run_on_line_is_stored_whole` |
| `luma_writer.v` | Varannan lumasampel → bildminnesadress (360 kolumner × 240 rader) | `sim/test_m1_input.py`: varje skrivning mot modellen |
| `dual_clock_ram.v` | Bildminne, skriv på TVP-klockan, läs på pixelklockan (BSRAM) | via M1-bygget |
| `tmds_encoder.v` | DVI TMDS 8b/10b (utan signerade jämförelser, se nedan) | `sim/test_video.py`: 4 200 symboler mot Python-implementation av DVI-specen |
| `video_timing.v` | 720p60-tidsbas (CEA-861) | `sim/test_video.py` |
| `dvi_tx_gowin.v`, `clocks_720p.v` | OSER10 + TLVDS, rPLL 27→371,25 MHz, /5 → 74,25 MHz | via bygge (primitiver enligt apicula-exemplet) |
| `tvp_sync_rx.v` | Mottagare för separata synksignaler (HSYNC/VSYNC/AVID), självinställande polaritet och bytefas | `sim/test_m1s_input.py` |
| `word_packer.v`, `async_fifo.v`, `sdram_burst.v`, `sdram_selftest.v`, `ycbcr2rgb.v`, `clocks_sdram.v` | Ord om två pixlar, klockdomänsbyte, SDRAM-styrning (burstar om 8 ord; DQ fångas i en ren vippa varje klocka), självtest av läspunkten efter SDRAM-starten (M4, M6), BT.601 till RGB utan signerad aritmetik. `async_fifo.v` med `RD_REG = 1` läser nästa ord till ett register vid varje läsklocka, så att minnet kan ligga i block-RAM; `rd_data` är detsamma som med `RD_REG = 0` vid varje klocka. Mixerns två ingångs-FIFO:er använder det sedan 2026-10-14 (se "M6 med HDMI och VINTERP") | `sim/test_sdram.py` (även självtestet), `sim/test_m2.py`; `sim/test_async_fifo.py` (båda lägena sida vid sida mot en kö, läsare som står still och sedan läser varje klocka; negativ kontroll med registret laddat från nuvarande pekare); formellt bevisad i båda lägena |
| `fb_sdram.v`, `fb_display.v`, `field_phase.v` | Fältminne i SDRAM med fyra buffertar: väljer vid varje bildstart vilket fält som visas, håller reda på vilka rader som är lagrade och täcker de som saknas; radmappning med halv rads förskjutning mellan fälten; vilket fält som är det nedre avgörs på ankomsttid. Tiden från återställning till första referensraden räknas inte som ett intervall (till 2026-10-07 gjorde den det, och en progressiv källa vars första referensrad kom ungefär en radtid före ett fältintervall efter starten ritades ett fält en halv rad lägre; hittat med `sim/test_fuzz_chain.py`). En rad räknas som lagrad bara om dess ord 0 togs i samma fält: raden skrivaren går in i mitt i efter reset eller `LOW` är inte lagrad (till 2026-10-12 var den det, och en bild utan video läste dess oskrivna ord; C3-kampanjens frön 1437 och 1445) | `sim/test_fb.py` mot `model/fb_ref.py` (varje beslut, varje läst rad), `model/test_fb_ref.py`; `sim/test_fb.py::test_first_interval_is_not_measured`, `::test_joined_line_from_the_middle_is_not_stored`; med `VINTERP=1` (interpolation i höjdled, standard av) `::test_vinterp_blends_two_source_lines` och `sim/test_vblend.py` |
| `fb_backend.v`, `cdc_sync.v` | Fältminne och visning, delad av M2 och M4. LOW:s 16 ringplatser delar RAM med BUF. En plats blir initialiserad efter accepterade skrivningar till dess ordadresser 0–359 i ordning, i BUF eller LOW. Global reset nollställer giltighetsmasken, inte RAM. LOW visar svart för en plats som saknar en komplett rad sedan reset. Senare partiella eller uteblivna rader behåller platsens giltighet och dess äldre, ej överskrivna ord. Klockdomänsövergångarna ligger i `cdc_sync.v` | `sim/test_m2.py` (båda lägena); `sim/test_ll_ring.py` mot `model/ll_ring_ref.py`, inklusive sex verkliga RTL-felvarianter; semantisk skriv-/displaykontroll i `sim/test_fuzz_chain.py`; CDC-handskakningar formellt bevisade, se "Formella bevis" |
| `genlock_timing.v` | Tidsbas som `video_timing.v`, låsbar till ingångens fält (låglatensläget) och 720p50 för PAL. Varje fullständig utgångsbild har en full vsync. `JUMP_AFTER` tidiga triggers klipper efter den fulla synken och hoppar till sista porchraden; den direkt följande återhämtningsbilden kan också korta sin back porch. Övriga bilder är minst `V_TOTAL−1` rader. Både klipp och återhämtningsbild kör hela sista porchraden för att återställa skalning och radindex i `fb_display`; `HOLD` gäller mellan klipp. `WAIT_BEFORE_VSYNC = 1` (standard 0) lägger den varierande raden före vsync, se "Den varierande raden" under `LOW` | `sim/test_m2.py::m2_low_latency`, `sim/test_fb.py` (låglatenstesterna med båda placeringarna), `sim/test_genlock.py`, formellt bevis för båda |
| `m2_core.v` | M2: en TVP (BT.656 eller separata synkar) → `fb_backend` | `sim/test_m2.py` |
| `cvbs_capture.v` (+ genererad `cvbs_gain.vh`) | Digital komposit in (6 bitar, 40 MS/s, C5VRX:s PARLIO-buss) → samma radord och markörer som `chan_capture.v`: nivåföljare och slicer, pulsdetektor med svänghjul, vertikalsynk ur de breda pulserna, radnumrering som TVP:ns V-bit, omsampling 40 → 13,5 MS/s, 1H-kamfilter, luma 16–235 (färg är uppgift 65). Kanal B i M4 med `DIGIN=1` (`mixer2.v` `B_DIGITAL`). Utgången `lock` (svänghjulet låst) är kanal B:s hälsa i mixern och räknas i M4:s hjärtslag (uppgift 69). Start (bänken 2026-10-27): olåst sveper skiljaren från 12 ett steg per två radperioder (8–40 och runt) tills en rad med riktig synk mätts; då tas synk- och släckningsnivån ur den raden rakt av, och ett tappat lås släpper dem. Lås kräver att pulsen som startade raden nått `T_EQ`. C5VRX lägger synken på 23 och släckningen på 31, där 12 aldrig såg en puls. Skiljaren ser summan av de 8 samplen före det aktuella (`AVG`): synktoppens brus (±8 koder) flyttade annars kanten upp till 32 sampel. Låst startar raden vid förutsägelsen (händelsen WIN sampel senare, som en svänghjulsstart); första kanten inom ±WIN nudgar nästa förutsägelse med round(err/16), bär periodskattningen kant till kant (`hp_acc` = 64·hp, ingen dödzon, såddad med låsperioden) och gör raden god; dess pulsklass följer med raden. Olåst startar raden vid kanten | `sim/test_cvbs_capture.py`: ren bildruta, brus och fel (saknad synk, kort rad) ord för ord mot `model/cvbs_capture_ref.py`; negativ kontroll utan kamfilter; gain-tabellen; låsspåret mot modellen (lås, låsförlust efter fashoppet, omlås; RTL:n byter 2–3 klockor efter modellens sampel) med negativa kontroller (platt nivå med brus låser aldrig; försvunnen synk släpper efter fyra svänghjulsrader); C5VRX:s nivåer 23/31/62 låser efter minst tio svepsteg och ger två bildrutors fält ord för ord (`test_c5vrx_levels_lock_by_sweep`); negativ kontroll: svart bild med synkpulser kortade under `T_EQ` låser aldrig, RTL och modell (`test_sweep_negative_controls`); C5VRX-nivåer med brus σ 3: ingen rad utanför mixerns längdtolerans, ingen dålig, låset håller, och utan medelvärdet (`AVG=1`) hittas inte ens vertikalsynken (`test_noisy_sync_edges_hold_the_line_length`); kanter flyttade ±8 sampel: alla längder inom toleransen, låset håller; negativ kontroll ±72: kanterna missar fönstret, svänghjulsrader, låset tappas (`test_jittered_edges_keep_the_prediction`) |
| ingen RTL än: `model/iq_demod_ref.py` | Genomförbarhetsmodell för mottagargräns C (uppgift 67): FPV-länken som komplex basbands-IQ i 40 MS/s, kvantiserad till 4 eller 7 bitar per axel, enkel fasderivata som demodulator; mått luma-SNR och synkträffar mot C/N, och vad 6-bitars utgången kostar. Simulerat 2026-10-24: 4 bitar stannar på 20–29 dB SNR, 7 bitar når 30–36 dB och hittar synken i alla rader från 20 dB C/N; 6-bitars utgången kostar under 1 dB | `sim/test_iq_demod.py`: SNR stiger med C/N, 7 bitar minst 8 dB över 4, 6-bitars utgången under 1 dB, negativa kontroller (2 bitar, fel deviation) |
| `chan_capture.v`, `mix_chan.v`, `line_mixer.v`, `mixer2.v` | M4: två TVP-kanaler → radvis mixer → ordström. Reglerna står under M4 nedan. Med `B_DIGITAL` tar `mixer2.v` kanal B:s hälsa ur `cvbs_capture` (`b_lock`) i stället för `ext_bad_b` (uppgift 69; `sim/test_mixer_digital.py`: statusingången hög, B:s synkroniserade `ext_bad` faller när fångsten låser; BT.656-bygget behåller ingången, negativ kontroll) | `sim/test_mixer.py` mot `model/line_mixer_ref.py`; regeln för parade rader mot Python-prototypen och fem egenskaper på slumpade radföljder i `model/test_line_mixer_ref.py` |
| `bt1120_tx.v`, `clocks_1080p.v`, `lt8618_ctrl.v` (+ genererad `lt8618_rom.vh`) | M5: 16-bitars BT.1120 med inbäddad synk, 148,5 MHz-PLL, LT8618SX-uppstart via I2C | `sim/test_bt1120.py`, `sim/test_m5c.py` (hela 1080p-kedjan avkodad som en mottagare), `sim/test_lt8618.py` |
| `rx5808_spi.v`, `rx5808_tune.v`, `vtx_channels.vh` (genererad), `ssd1306_text.v`, `font5x7.vh` (genererad), `puck_ui.v`, `snow_stats.v`, `bin2bcd.v`, `osd_overlay.v`, `uart_tx.v` | Puck: RX5808-kanalstyrning (SPI) och när kanalen skrivs (0,5 s efter start, vid kanalbyte, varannan sekund utan lås), 48 kanaler med svensk-bandflagga, OLED-text 4×21 tecken utan bildbuffert med ett dubbelhögt radpar (`text_big`), flygvy och meny med en post per skärm på två knappar, delad I2C-buss med `tvp_ctrl` (hold/active) | `sim/test_puck_ui.py`: SPI-ord bit för bit mot `model/vtx_channels.py`, skärmbilden (flygvy, meny, mätar- och RSSI-sida) avläst ur pixlarna via teckensnittet och den dubbelhöga raden byte för byte mot `model/oled_ref.py`, HOLD, menytimeout, sparstatus, inga busskollisioner; `sim/test_rx5808_tune.py`: skrivtidpunkterna mot en modell av regeln; `sim/test_snow_stats.py`, `sim/test_osd.py`; UART-loggen och OSD-visningen i `sim/test_puck_ui.py`; `tools/test_snowlog.py` |
| `noise_stats.v` | Brusmått per mottagare: lumasampel utanför 16–235 per rad och summerat över 1 024 rader, räknat på orden ur kanalens FIFO i mixerns klockdomän. Mixern läser det inte; det går till M6-loggen | `sim/test_noise_stats.py`: varje rad och varje fönster mot `luma_outside()` i `model/bt656.py` på vektorn `ntsc_spikes` (injicerade spikar, gränsvärdena 15/16/235/236, krominans utanför intervallet); negativa kontroller: intervallet 15–236 och räkning av krominans ger andra tal |
| `chan_scan.v`, `flash_store.v` | M6: kanalskanning utan RSSI (lås och brus per kanal), sparade inställningar i kortets SPI-flash. Se M6 | `sim/test_chan_scan.py` mot `model/chan_scan_ref.py`; `sim/test_flash_store.py` mot `model/flash_store_ref.py` och `sim/spi_flash_model.v` |
| `rssi_adc.v` | RSSI från båda mottagarna via ADS1115 (48h) på dekoder A:s buss, en gång per fält: kalibrering min/max per mottagare, kalibrerat värde 0–100, låg efter 3 avläsningar under 20 %, varning bara när den andra mottagaren är kalibrerad, giltig och inte låg. Se M6 | `sim/test_rssi_adc.py` mot `model/rssi_ref.py` och `sim/ads1115_model.v`, på samma buss som `tvp_ctrl` och OLED:n |
| `i2c_master.v`, `tvp_ctrl.v`, `dec_bad.v` | I2C; uppstart av egna TVP5150AM1 (reset, 00h/04h/0Dh/28h/02h/03h, se M4; 04h maskar SECAM ur autoswitchen), pollning av status 88h/89h, och ny uppstart av en dekoder som har återställts (03h läses tillbaka vid varje pollning, räknare per dekoder). En pollrunda gäller bara hel: ett NACK på någon av de tre läsningarna, eller en återställd dekoder, gör statusen ogiltig tills nästa hela runda (granskningen 2026-10-06, F2). `i2c_master.v` kan skriva upp till 256 databyte efter registeradressen i en transaktion (`wextra`, `wreq`); `tvp_ctrl.v` och `ssd1306_text.v` skriver en byte i taget. Om en slav håller SCL låg längre än 10 ms ger mastern upp: den släpper båda linjerna och avslutar med `nack` och `stuck`; `dec_bad.v`: en dekoders rader är dåliga för mixern utan en hel pollrunda med H- och V-lås (M4, M6; `sim/test_dec_lock.py`) | `sim/test_tvp_ctrl.py` mot I2C-slavmodeller (två adresser, delad adress med separata SDA, saknad dekoder, återställd dekoder, dekoder som inte tar emot skrivningar, SDA kortsluten låg, dekoder som kommer in sent; init-listan skrivs hel och i ordning, 88h bit 4 rapporteras med sin runda); `sim/test_i2c_master.py`: skrivningar om 1, 2, 8 och 256 byte, NACK mitt i och på första databyten, frånvarande adress, återläsning, allt mot `model/i2c_ref.py` (bussen bit för bit, lagrade register); SCL som hålls låg kort (som vanligt) och för gott (mastern ger upp efter `STRETCH_MAX` klockor, nästa transaktion fungerar); negativa kontroller: slav utan autoinkrement, master som inte avbryter efter NACK, master utan tidsgräns |

## Verktyg (allt i projektmappen, inget på systemet)

- `.venv/` (uv): yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, apycula (gowin_pack), cocotb, pytest.
- `.tools/iverilog/` — Icarus Verilog 12 byggd från källkod.
- Bygg: `gateware/build.sh <toppmodul>` → `gateware/build/<toppmodul>.fs`.
- Före varje commit: `.venv/bin/python gateware/tools/run_suite.py --quick` (snabbsviten, nedan). Före varje sammanslagning till `main`: hela sviten, `.venv/bin/python gateware/tools/run_suite.py`. Ett enstaka test: `.venv/bin/python -m pytest -q gateware/sim/test_m2.py`.

### Hela sviten parallellt

`tools/run_suite.py` startar en pytest-process per test under `gateware/sim` och `gateware/tools` och en per fil för de rena Pythontesten, tio åt gången (`-j`). Varje process har en egen `--basetemp`. Längst först, efter tiderna från förra körningen. I `gateware/sim/build/suite/` (`--out`) hamnar en logg per process, `results.jsonl`, `status.json` och `report.txt`. Returkod 0 bara när alla test gick igenom och ingen byggkatalog delas; 1 vid fel eller delad katalog, 3 när `--budget S` lämnade test kvar. `--resume` kör det som återstår och vägrar med returkod 2 om källorna eller de insamlade testidentiteterna ändrats, eller om en lagrad testpost saknar begärda utfall. Ett vägrat återupptagande lämnar resultatkatalogen orörd. Äldre manifest utan testidentiteter kräver även samma sökvägar och `-k`-uttryck. Använd en ny `--out` för ett annat testurval.

Revisionen av byggkataloger går i samma körning: `tools/suite_trace.py` spelar in vilka kataloger under `gateware/build`, `gateware/sim/build` och `gateware/formal/build` varje tests underprocesser använder, och vilken cocotb-resultatfil. `tools/build_dirs.py --list` skriver ut dem per test och fäller en katalog eller fil som två test använder. Den fann tre sådana par på `main` f32407f (`tb_m2`, `tb_sdram`, `tb_tvp_ctrl_100_0`), som nu har egna kataloger. Med dem: 658 test gröna, 169 byggkataloger och 19 resultatfiler utan delning, 633 s med tio åt gången på en 24-trådars maskin (längst tar `tools/test_formal.py`, 7 minuter).

### Snabbsviten före varje commit

`run_suite.py --quick` kör bara testen i `tools/quick_tests.txt` och skriver till `gateware/sim/build/quick/`, så att den senaste hela körningens loggar, resultat och tider står kvar. `--full`, eller inget val, kör allt. Regeln: snabbsviten före varje commit, hela sviten på den commit som slås ihop före varje sammanslagning till `main`.

Listan väljs ur uppmätta tider: `--pick-quick 300` läser `durations.json` från en hel körning och tar först det snabbaste testet ur varje fil, sedan de snabbaste av resten, så länge den väntade väggtiden med `-j` processer stannar inom 300 s. Listan skrivs längst först, och en snabbkörning utan egna tider startar testen i den ordningen. Huvudet säger när listan valdes och vilka filer som saknas. Står det ett namn i listan som inte längre samlas in vägrar `--quick` med returkod 2; välj då en ny lista ur nästa hela körning.

Listan från 2026-10-18 kommer ur hela körningen på `52c2ffe` (797 test, alla gröna, 995 s): 720 test ur 50 av 51 filer, väntat 297 s med tio åt gången. Utöver varje fils snabbaste test rymdes test upp till 40 s. Utanför listan: de formella bevisen (`tools/test_formal.py`, 986 s i den körningen) och 76 simuleringar på 40–314 s var, de flesta i `sim/test_fb.py` (21), `sim/test_fuzz_chain.py` (21) och `sim/test_mixer.py` (18); varje sådan fil har kvar sina snabbaste test. `sim/test_puck_ui.py::test_puck_ui` tar 314 s, mer än hela gränsen på 300 s, och är inte längre med; filen finns i listan genom `test_hdmi_field_negative_control[no_step]` (92 s), det längsta testet i listan. Av de 21 testen från uppgift 35 är 15 med. De sex andra tar 45–92 s och ligger i filer vars snabbaste test är med: `sim/test_m6_settings.py` med `test_m6_loads_the_hdmi_range[old_vcr]` och `test_m6_settings_negative_control` (`load_from_bit_70`, `range_not_wired`, `save_in_bit_68`), och `sim/test_puck_ui.py` med `test_hdmi_field_negative_control` (`log_always_f`, `screen_always_full`). Testet för listans ordning (`tools/test_run_suite.py::test_quick_without_durations_starts_in_list_order`) är med. Snabbsviten med listan i en färsk kopia, alltså utan egna tider och i listans ordning: 720 gröna på 204 s med tio åt gången, ingen delad byggkatalog (2026-10-18, `01e9946`).
- Flasha (när kortet finns): openFPGALoader behövs, t.ex. `sudo pacman -S openfpgaloader` (Arch), sedan
  `openFPGALoader -b tangnano20k gateware/build/m0_testpattern.fs` (RAM) eller med `-f` (flash).

Bygget läser en fryst kopia av RTL, inkluderingsfiler och stift-/klockvillkor. Bredvid bitströmmen ligger `<toppmodul>.build.json`: Git-revision och smutsig arbetskopia, SHA256 för byggindata och resultat, verktygsversioner, byggval och sista timingresultatet per klocka. Samma suffix används för bitström, loggar och manifest vid `PULL` och `SDRAM_PHASE`.

Kontroll före flashning:

```sh
.venv/bin/python gateware/tools/build_manifest.py verify gateware/build/m0_testpattern.build.json --root .
```

När verktygen ska starta flyttas föregående resultat till `build/previous/`. Vid syntes-, routing-, timing- eller packningsfel saknas bitströmmen på den vanliga flashningssökvägen; loggar och frysta byggindata finns i den arbetsmapp som felmeddelandet anger. Ogiltiga byggval avvisas innan tidigare resultat flyttas. Timingrapporten verifierar inte elektriska marginaler på kortet. `tools/test_build_artifacts.py` provar felvägarna med verktygsstubbar och kontrollerar att en tillfällig källkodsändring inte når kompilatorn; kontrollvarianten som läser levande filer ger annat kompilerat innehåll.

## M0 — första ljuset

Koppla kortets HDMI till en TV/skärm. Förväntat: färgstaplar i en vit 4:3-ram, grå ramper på sidorna, en orange ruta som studsar. LED0 blinkar 1 Hz. S1 (stift 88) = reset.

**DVI eller HDMI.** Alla byggen sänder som standard **DVI** (`rtl/tmds_link.v`, `HDMI = 0`): ren TMDS utan dataöar, RGB i fullt omfång utan att säga det. En skärm som följer CEA-861 strikt kan då ta bilden för begränsat omfång och krossa svärtan (navets `research/GOGGLES_OCH_XR_2026-10-12.md`, regel 4). Med `HDMI=1 gateware/build.sh <topp>` (filnamnet får `_hdmi`) sänds HDMI: förambel och skyddsband före varje aktiv rad, och efter varje vsync en dataö med en AVI-infoframe: RGB, 16:9, omfånget (nedan), VIC 4 för 720p60 och VIC 19 medan `LOW` med PAL-källa ger 720p50 (`hz50` från `fb_backend.v`). Bilden går 10 klockor senare än i DVI-läget. Simulerat mot en avkodare i `sim/test_hdmi.py` (videon, förambler, skyddsband, en dataö per bild, paritet, kontrollsumma, omfång, VIC); negativa kontroller: fel VIC, fel kontrollsumma, fel paritetspolynom, inget skyddsband. Tabellerna (TERC4, skyddsband, paketets bitordning, BCH) är skrivna ur HDMI 1.4 och CEA-861 i både RTL och avkodare, så ett fel i läsningen av specifikationen kan finnas i båda; ingen riktig skärm har sett HDMI-läget. Mät rampen med DVI och HDMI på bänken innan standard ändras (`docs/MATPROTOKOLL.md` i navet, blad 16).

**Omfånget i HDMI-läget: `FULL` eller `LTD`** (sedan 2026-10-18, Core #23, granskning 2 HD-1). `FULL` är standard och samma som förut: pixlarna sänds som de kommer ur `ycbcr2rgb.v`, 0–255, och infoframen säger fullt omfång (Q1:Q0 = 10b). `LTD` skalar varje färgkomponent till 16–235 och säger begränsat omfång (01b): ut = 16 + avrundat x·219/255, i `tmds_link.v` räknat som v = x·219 + 128, q = (v + (v >> 8)) >> 8, ut = 16 + q (0 → 16, 128 → 126, 255 → 235; en multiplikator per komponent). För 720p är begränsat omfång standard för RGB, och enligt CTA-861 får källan säga något annat bara till en skärm som anger QS i sin EDID; en skärm utan QS kan alltså strunta i flaggan och ta `FULL` för begränsat, med krossad svärta som följd. Med `LTD` stämmer bilden för en sådan skärm, men en skärm som tar allt för fullt omfång visar då gråsvart. Kortet kan inte läsa skärmens EDID (DDC ligger på stift 52/53, konfigurationsstift som inte används), så vilket läge som ger rätt svärta avgörs på bänken med gråskala och EDID per skärm (navets `docs/MATPROTOKOLL.md`, blad 16). Valet görs i M6-menyn (fältet `HDMI`, se M6) och sparas i flashen; M0, M4 och de andra topparna har ingen meny och sänder `FULL`. `tmds_link.v` tar valet via två vippor och byter vid nästa vsync, så en bild och infoframen före den har alltid samma omfång; före första vsync gäller parametern `RGB_FULL`. DVI-läget ändras inte av valet. Simulerat i `sim/test_hdmi.py`: en ramp med alla 256 värden per komponent i båda lägena, med kända värden och omfånget i varje infoframe, ett byte mitt i en bild som slår igenom först i nästa, och DVI med valet växlande; negativa kontroller: 220 i stället för 219, förskjutning 17, utan avrundningsterm, flaggan utan skalning (som före rättningen), skalning utan flagga och ett val som inte hålls till vsync. `sim/test_review_2026_10_14.py::test_hdmi_limited_flag_means_limited_pixels` är ett vanligt test.

Byggt ur `52c2ffe` (2026-10-18; siffror efter routning, krav 75 MHz, inga `ERROR`, manifesten verifierade, alla fyra HDMI-par i alla sex med samma IOB-fuses som i M0 med DVI enligt `tools/tmds_fuses.py`). M0 och M4 knyter `rgb_full` till 1; M0 med `HDMI=1` har 950 LUT4 mot 948 ur `4ad5a68`, så skalningen följer inte med där. I M6 med `HDMI=1` väljs den i menyn:

| Topp | Läge | LUT4 | BSRAM | Lägsta maxfrekvens (MHz) |
|---|---|---:|---:|---|
| `m0_testpattern` seed 0 | DVI | 789 | 0 | 161,16 (pixel) |
| `m0_testpattern` seed 0 | HDMI | 950 | 0 | 211,10 (pixel) |
| `m4_dual_mix` seed 0 | DVI | 5 810 | 29 | 115,06 (pixel) |
| `m4_dual_mix` seed 0 | HDMI | 5 993 | 29 | 123,00 (`sd_clk`; pixel 142,45) |
| `m6_puck_proto` seed 2 | DVI | 13 190 | 29 | 103,80 (27 MHz-domänen; pixel 133,67) |
| `m6_puck_proto` seed 2 | HDMI | 13 544 | 29 | 103,80 (`sd_clk`; pixel 115,38) |

Äldre bygge, ur `4ad5a68` (siffror efter routning, krav 75 MHz, HDMI-paren i alla sex som i M0 med DVI):

| Topp | Läge | LUT4 | DFF | Pixelklocka (MHz) |
|---|---|---:|---:|---:|
| `m0_testpattern` seed 0 | DVI | 788 | 173 | 152,39 |
| `m0_testpattern` seed 0 | HDMI | 948 | 397 | 125,82 |
| `m4_dual_mix` seed 0 | DVI | 8 266 | 4 523 | 147,36 |
| `m4_dual_mix` seed 0 | HDMI | 8 430 | 4 827 | 126,21 |
| `m6_puck_proto` seed 2 | DVI | 12 736 | 6 209 | 129,90 |
| `m6_puck_proto` seed 2 | HDMI | 13 024 | 6 514 | 110,24 |

Övriga klockor i M4/M6 oförändrade i stort (alla över 100 MHz utom M6:s 27 MHz-domän, 123,02 respektive 124,61).

## M1 — koppla in Moneagle

**Innan något kopplas:** öppna Moneagle, bekräfta TVP5150AM1 och mät **TVP-stift 10 (IO_DVDD)**. Kopplingen nedan förutsätter 3,3 V. Vid 1,8 V behövs nivåomvandlare.

| TVP5150AM1 (TQFP-32) | Signal | Tang Nano 20K | Stiftlist |
|---|---|---|---|
| 9 | SCLK 27 MHz | PIN77 (GCLKT_1, klockingång) | J6-5 |
| 18 | YOUT0 | PIN27 | J6-8 |
| 17 | YOUT1 | PIN28 | J6-9 |
| 16 | YOUT2 | PIN26 | J6-11 |
| 15 | YOUT3 | PIN29 | J6-12 |
| 14 | YOUT4 | PIN30 | J6-13 |
| 13 | YOUT5 | PIN31 | J6-14 |
| 12 | YOUT6 | PIN73 | J6-1 |
| 11 | YOUT7 | PIN74 | J6-2 |
| 19 | DGND | GND | J6-20 |

Källor: TVP-stift ur TI SLES209E; kortstift ur Sipeeds schema v3921 sida 2 (`research/raw/reva/headers_crop.png`); klockstiftens funktion ur apiculas chipdb (GW2AR-18C, QFN88). **Rättat 2026-10-02:** SCLK låg tidigare på PIN25, som inte är en klockingång (GCLKT_4 är PIN35 och används av HDMI). Klockingångar på stiftlisterna: PIN77 (J6-5, GCLKT_1), PIN80 (J5-4, GCLKT_0), PIN76/PIN79 (komplementstift). TVP:n lägger ut data så att mottagaren ska sampla på stigande flank (Linux-drivrutinen `tvp5150.c`: `V4L2_MBUS_PCLK_SAMPLE_RISING`; SLES209E: utfördröjning 3–8 ns, hålltid 2 ns) — det gör vår logik. Tunn lackad tråd, så kort som möjligt, gärna 47–100 Ω i serie nära TVP:n, gemensam jord. Moneagle och Tang Nano matas var för sig men delar jord.

Lysdioder (tänd = sant): LED0 hjärtslag, LED1 rader kommer in, LED2 fält 1 sett, LED3 synkord har rättats, LED4 trasiga synkord sett.

**Felsökning:** inga rader (LED1 släckt) men SCLK finns → Moneagles SoC har troligen ställt TVP:n på separata synksignaler i stället för inbäddad BT.656 (register 0Dh). Använd då **M1s** nedan. Bilden kan ha rivningar (ingen genlock); det löses i M2 med SDRAM.

## M1s — samma sak med separata synksignaler (HSYNC/VSYNC/AVID)

`top/m1s_moneagle_view_sync.v` → `build/m1s_moneagle_view_sync.fs` (1 054 LUT, 5 %; 44/46 BSRAM; pixelklocka 114,2 MHz, TVP-domän 190,6 MHz mot krav 75). Mottagare: `rtl/tvp_sync_rx.v`.

Samma 10 trådar som M1, plus tre:

| TVP5150AM1 | Signal | Tang Nano 20K | Stiftlist |
|---|---|---|---|
| 25 | HSYNC | PIN75 | J6-3 |
| 24 | VSYNC/PALI | PIN85 | J6-4 |
| 26 | AVID | PIN25 | J6-10 |

Den ställer in sig själv: polaritet på HSYNC/VSYNC/AVID mäts över ~39 ms (synkpulser är minoritetsnivån, AVID majoriteten; bara tydliga majoriteter byter beslut), och vilken byte som är luma avgörs per fält (luma varierar mer än kroma). FID (stift 23) behövs inte — båda fälten skrivs till samma bildminne. Simulerad med normala och inverterade polariteter och båda bytefaserna (`sim/test_m1s_input.py`).

Lysdioder (tänd = sant): LED0 hjärtslag, LED1 AVID-rader kommer in, LED2 VSYNC aktiv hög, LED3 AVID aktiv hög, LED4 luma på udda byte (Cb Y Cr Y), LED5 HSYNC aktiv hög.

Om VSYNC-stiftet är omställt till PALI (PAL-radindikator) kommer LED1 lysa men bilden rulla; då behövs en variant som räknar rader från AVID-pauser i stället — säg till.

Yosys-varningar om `brams_map.v` ("Range select out of bounds") är ofarliga: de gäller oanvända bitar i Gowins minnesmall när minnet är 8 bitar brett.

## M2 — så fungerar det

Samma 10 trådar som M1 (inbäddad BT.656-synk). Kedja och klockdomäner:

```
TVP 27 MHz:  bt656_rx -> word_packer (Cb Y Cr Y = 1 ord = 2 pixlar) -> async_fifo
SDRAM 64,8 MHz:  fb_sdram: skrivare (8-ords burstar) + radhämtare + arbiter -> sdram_burst -> inbyggt SDRAM
                 4 fältbuffertar; väljer vid varje bildstart vilket fält som visas; skriver aldrig i det som visas
Pixel 74,25 MHz: fb_display: begär rader, radmappning (240/243/288 rader) med halv rads förskjutning mellan fälten,
                 förhämtning av nästa källrad till 4-plats radbuffert, YCbCr -> RGB (BT.601), 4:3-fönster
```

- SDRAM-styrningen (`rtl/sdram_burst.v`) bygger på nand2marios styrning, men flyttar burstar om 8 ord i stället för enstaka ord.
  - **Provat på hårdvara uppströms:** NESTang kör samma minne i 64,8 MHz med SDRAM-klockan 225° efter styrklockan, CAS 2, och läser enstaka ord CAS + 1 klockor efter läskommandot. Fasen och läspunkten är desamma här.
  - **Inte provat någonstans:** läsning i burst. Där byts ordet på bussen 2,5–6 ns efter nästa SDRAM-klockflank, medan ett enstaka ord ligger kvar. Läspunkten måste alltså träffa ett fönster på 11,9 ns, och var det ligger beror på kortets fördröjning (klockan ut plus data tillbaka). Med 225° och standardläspunkten läses rätt ord om fördröjningen är 3,3–15,2 ns (`sim/test_sdram.py`). Den är inte mätt, och byggena har inga tidskrav på I/O. I standardbygget placeras läsvipporna fritt (i M2-bygget 2026-10-06 13–39 rutor från sina stift), så fördröjningen skiljer mellan dataledningar och mellan byggen; med `IOREG=1` ligger de 32 DQ-vipporna i I/O-cellerna ("I/O-register i I/O-cellerna"), men inte DQ-utgångarna eller SDRAM-klockan. M4 och M6 kör ett självtest av läspunkten i sitt eget bygge (under M4, "SDRAM-självtestet").
  - Kör därför minnestestet (M2a nedan) före M2 och M4.
- T_RCD/T_RP/T_RC är 2/2/6 klockor, som NESTang anger. Databladet för EM638325-6 kräver 18 ns för de två första, alltså 2 klockor. Till 2026-10-05 stod här 180° och 1/1/4, vilket ingen uppströms kör.
- Läspunkten är `RD_SAMPLE` i `rtl/sdram_burst.v` (alla toppmoduler) eller parametern med samma namn i `rtl/fb_backend.v`. Fel läspunkt ger en bild som är förskjuten 2 pixlar eller trasig i 8-pixelsblock. Sedan 2026-10-21 tar en ren vippa (`dq_in`, ingen klockenable, ingen reset) stiften varje klocka, och läsningen flyttar ordet till `rdata` en klocka senare: läsögonblicket vid stiften är detsamma, `rdata_valid` kommer en klocka senare än förut.
- Bandbredd (simulerat): bilden behöver ca 21 MB/s in och ca 21 MB/s ut. Styrningen läser 130 MB/s (16 klockor per burst) och skriver 80 MB/s genom `fb_sdram`. En rad hämtas på högst 11,7 µs; en utrad är 22,2 µs.
- Fälten visas ett i taget med radupprepning (bob): ingen kamskada vid snabba FPV-rörelser. Det nedre fältet ritas en halv källrad lägre. Latens och övrigt beteende står i avsnittet "Bildvägen efter mixern".
- Lysdioder (tänd = sant): LED0 hjärtslag, LED1 BT.656-rader kommer in, LED2 SDRAM initierat, LED3 halvbild visas, LED4 SDRAM-PLL låst, LED5 pixel-PLL låst.
- SDRAM-stiftens placering verifierad i place & route (55 signaler på IOL/IOR-platserna).

**M2s:** samma 13 trådar som M1s (M1-kablarna + HSYNC PIN75/J6-3, VSYNC PIN85/J6-4, AVID PIN25/J6-10). Lysdioderna betyder samma som i M2; LED1 = AVID-rader kommer in.

## M2a — minnestest av SDRAM

`top/m2a_memtest.v` → `build/m2a_memtest.fs` (kärna `rtl/memtest_core.v`). Bara Tang-kortet och USB-kabeln behövs.

Testet skriver hela minnet i burstar om 8 ord, läser tillbaka och jämför, först med pseudoslumptal och sedan med adressen som data. Det görs för tre läspunkter i tur och ordning. Varje läspunkt ger en rad på kortets USB-UART (PIN69, 115200 8N1), ungefär fyra rader i sekunden:

```
M rs=5 pass=0012 err=00000000 bits=00000000000000000000000000000000 pos=00000000
```

| Fält | Betyder |
|---|---|
| `rs` | läspunkt: 4, 5 eller 6 klockor efter radaktiveringen. 5 är standard (`RD_SAMPLE`) |
| `pass` | varv, hex. Ett varv är tre rader |
| `err` | felaktiga ord, hex, av 400000 jämförda |
| `bits` | en siffra per dataledning, DQ31 först och DQ0 sist |
| `pos` | en siffra per ord i bursten, ord 0 först |

En siffra i `bits` och `pos` är felräknarens storlek: 0 inga fel, 1 ett, 2 två eller tre, 3 fyra till sju och så vidare (n betyder 2^(n−1) till 2^n − 1), F minst 16 384.

| Raderna visar | Betyder | Gör |
|---|---|---|
| `rs=5` har `err=00000000`, de andra är fulla av fel | läsningen fungerar; `rs=4` läser ordet före och `rs=6` ordet efter | prova fasen ett steg före och efter, se nedan |
| bara `rs=4` eller bara `rs=6` är ren | fördröjningen är kortare eller längre än väntat | byt fas, eller sätt `RD_SAMPLE` till det värdet |
| ingen rad är ren | alla läspunkter hamnar där data byts | byt fas |
| få fel, på enstaka siffror i `bits` | de dataledningarna ligger på fönstrets kant | byt fas |

Annan fas utan att ändra källkod: `SDRAM_PHASE=12 gateware/build.sh m2a_memtest` ger `build/m2a_memtest_phase12.fs`. Talet är sextondelar av en period: 8 = 180°, 10 = 225° (standard), 12 = 270°. Senare fas passar kortare fördröjning. Testet mäter sitt eget bygge. I standardbygget placeras läsvipporna fritt, så resultatet gäller bara det bygget; med `IOREG=1` ligger de i I/O-cellerna i varje topp, men SDRAM-klockans och DQ-utgångarnas vägar placeras fortfarande fritt. Välj därför en fas där `rs=5` är ren även ett steg (0,96 ns) åt vardera hållet, och för in den som `PSDA_SEL` i `rtl/clocks_sdram.v`. M4 och M6 visar med självtestet om läspunkten fungerar i deras bygge (under M4).

Håll S2 intryckt för att prova testet självt: då skrivs ett ord fel med flit, och en fungerande läspunkt ska visa `err=00000001`, sista siffran i `bits` 1 och sjätte siffran i `pos` 1. S1 startar om. Lysdioder (tänd = sant): LED0 växlar för varje rad, LED1 SDRAM initierat, LED2 standardläspunkten hade fel i sin senaste rad.

Simulerat i `sim/test_memtest.py`, där UART:en avkodas bit för bit, mot `sim/sdram_model.v`. Modellen har tiderna ur Etrons datablad för EM638325-6 (tAC 6 ns, tOH 2,5 ns). Att det inbyggda minnet beter sig som den kretsen är ett antagande, liksom modellens kortfördröjning på 3 + 3 ns.

| Klockan ut + data tillbaka | Fas | Ren rad |
|---|---|---|
| 3 + 3 ns (antagandet) | 225° | `rs=5` |
| 0 | 225° | ingen |
| 0 | 180° | `rs=4` |
| 1 + 1 ns | 225° | ingen |
| 1 + 1 ns | 270° | `rs=5` |
| 3 + 17 ns | 225° | `rs=6` |

Vilken rad som blir ren på ett riktigt kort vet ingen förrän testet har körts där.

## `model/` — facit

`model/bt656.py` är referensmodellen; `model/make_vectors.py` skriver `vectors/`. Se docstrings och `model/test_bt656.py`.

## M4 — två egna mottagare/dekodrar med mixer

`top/m4_dual_mix.v` → `build/m4_dual_mix.fs`. Två TVP5150-moduler, var och en matad med CVBS från en egen 5,8 GHz-mottagare på samma kanal. FPGA:n startar dekodrarna via I2C och startar om en dekoder som har återställts (`rtl/tvp_ctrl.v`); mixern väljer per rad den renaste kanalen eller blandar.

Mixerns regler (`rtl/line_mixer.v`; i sin helhet i `model/line_mixer_ref.py`):
- Två rader paras om de har samma radnummer och kommer inom 15,8 µs från varandra. Av ett par visas den renare raden (minst HF-energi), med hysteres, eller en blandning när de är ungefär lika rena. En dålig rad (trasigt synkord, fel längd, dekoder utan bekräftat lås, tvingad från menyn) förlorar mot en bra. En rad där inte alla 360 ord kom i följd (till exempel sen SAV med rätt radlängd) lagras inte alls, så ringens gamla ord kan inte visas; den räknas som dålig, och den andra kanalens rad med samma nummer får fylla luckan (granskningen 2026-10-06, F1; `sim/test_mixer.py::test_incomplete_line_is_not_stored`).
- RSSI-varning (M6, `ext_weak`, sedan 2026-10-13): av två bra rader i ett par förlorar raden från en svag mottagare mot en från en mottagare som inte är svag, utan blandning, och den andra mottagaren blir aktuell. Svaga rader räknas också som dåliga för kanalens hälsa (de åtta senaste raderna), men själva raden är inte dålig: den visas när den är ensam eller den bättre kopian och lämnas aldrig ute för att den är svag. `ext_bad` används inte för det, eftersom två svaga mottagare då skulle lämna bilden ute rad för rad. M4 knyter `ext_weak` till 0. Simulerat: `sim/test_mixer.py::test_weak_rssi_moves_the_mixer_before_the_picture_breaks_up` (B under varningen trots att A är renare, ingen rad utelämnad, A igen efteråt; RTL lika med modellen), negativa kontroller utan regeln i `line_mixer.v` och utan flaggan i `mix_chan.v`. Sedan 2026-10-14 tar en svag mottagare utan dåliga rader ändå över från en mottagare vars åtta senaste rader alla var dåliga (hälsan räknad på dåliga rader för sig, `dead`/`self_ok` i `mix_chan.v`). Förut kunde den aldrig bli frisk, och två mottagare ur takt stannade på den trasiga: 69 av A:s 72 dåliga rader visades och ingen av B:s (granskningen 2026-10-14, RS-1; `::test_weak_receiver_takes_over_from_a_broken_one`, negativ kontroll utan regeln).
- En rad som skulle visas men saknar frisk kopia (båda raderna i ett par är dåliga, eller en ensam rad är dålig) skrivs inte, om inte raden som visades före den i samma utfält också saknade frisk kopia. Fältminnet ersätter då raden med raden ovanför, eller med förra fältets rad om det är fältets första rad, och med en svart rad om inte heller den finns. Av flera sådana rader i följd lämnas bara den första ute: brus är bättre än stillbild, och mixern kan inte veta att en följd börjar när den avgör första raden. Allt annat (aktuell kanal, hälsa, tystnadsräknare, utfältets antagning) avgörs som om raden visades; den synliga fältgränsen hålls väntande tills en rad skickas. Beslutet har `use` 00. En utelämnad sista rad i ett fält ersätts inte: för fältminnet blir fältet en rad kortare, och bilden skalas från en rad färre medan fältet är ett av de två senaste (vid NTSC 242 i stället för 243 under två fält, om det träffar det kortare fältet). Simulerat: `sim/test_mixer.py::test_lines_bad_on_both_are_left_out`, `::test_line_bad_on_both_at_a_channel_change`, egenskapen `lone_lines_bad_on_both_are_left_out` i `model/test_line_mixer_ref.py` och `sim/test_fb.py::test_lines_the_mixer_leaves_out_are_covered`.
- En rad utan partner avgörs 15,8 µs efter att den kom. Den visas om den kommer från den aktuella kanalen, eller som lucktätning när kanalerna går i takt och den andra kanalen inte levererade något intill den.
- Utan parade rader byter mixern kanal när den aktuella kanalens åtta senaste rader är dåliga och den andras åtta bra, eller när den aktuella har varit tyst i 8 av den andras rader (i takt) eller 40 (ur takt, längre än en vertikalsläckning). Ingen tidsgräns i klocktid ingår i besluten.
- Raderna lämnar mixern i stigande ordning inom ett fält. Utströmmens syntetiska F-bit markerar en synlig fältgräns (ägarens val 2026-10-08 för Core #18), inte dekoderns F. En antagen fältgräns hålls väntande medan rader utelämnas och växlar taggen på nästa skickade rad; flera helt utelämnade fält ger en enda växling. Fältminnet och ringskrivaren ser ett nytt fält på F-byte eller lägre radnummer, och vilket fält som är det nedre avgörs på ankomsttid. Om ett par börjar ett nytt fält avgörs på en kanal som har en rad i utfältet: har den aktuella kanalen ingen (den andra bar fältet), på partnern. Till 2026-10-07 avgjordes det bara på den aktuella kanalen, och när en mottagare kom tillbaka efter ett tyst fält medan den andra saknade lås visades inget fält alls så länge den återkomna var renast (hittat med `sim/test_fuzz_chain.py`; `sim/test_mixer.py::test_returning_channel_starts_the_next_field`). Förut (till 2026-10-08) låstes F från fältets första rad, och ett utfält som började över den senast skickade raden med samma F (en mottagare tar över ur takt längre ner i fältet, vanligt med F = 1) syntes inte för fältminnet, som slog ihop det med fältet före (Core #18, `sim/test_mixer.py::test_new_output_field_is_seen_downstream`, tidigare xfail).

Till 2026-10-05 räknade mixern en kanal som död efter 1,0 ms utan rader, vilket är kortare än en vertikalsläckning, och ensamma rader visades utan att deras kvalitet prövades (granskningen 2026-10-05, M-1 till M-5). Planens avsnitt "M4-implementering" i navets `docs/GATEWARE_PLAN.md` beskriver den äldre mixern.

| Signal | Dekoder A | Dekoder B |
|---|---|---|
| SCLK | PIN77 (J6-5, GCLKT_1) | PIN80 (J5-4, GCLKT_0) |
| YOUT0–7 | PIN27, 28, 26, 29, 30, 31, 73, 74 (J6-8, 9, 11, 12, 13, 14, 1, 2) | PIN76, 42, 41, 48, 49, 86, 79, 72 (J5-3, 5, 6, 10, 12, 13, 14, 17) |
| I2C SDA | PIN85 (J6-4) | PIN51 (J5-9) |
| I2C SCL | PIN75 (J6-3), gemensam | |
| RESETB | PIN18 (J6-18, lysdiod 3), gemensam — den röda modulen saknar reset-stift: löd en tråd till TVP stift 8 | |
| RX5808 SPI CLK / DATA / SEL | PIN71 (J5-18) / PIN19 (J6-17, lysdiod 4) / PIN20 (J6-16, lysdiod 5), till båda mottagarna | |
| Jord | J6-20 / J5-2, J5-15 | |

Två likadana moduler svarar på samma I2C-adress (B8h), därför egen SDA per dekoder. Kontrollera modulernas matning och IO-nivå (3,3 V) innan inkoppling. Stift 52–56 (konfigurationsstift) används inte.

**Flerbyteskrivning och TI:s firmware-patch.** `i2c_master.v` skriver registeradressen och sedan upp till 256 databyte i samma transaktion; dekoderns registerpekare räknar upp mellan dem. Nästa byte begärs med `wreq` och ska ligga på `wdata` inom 32 × `DIV` klockor. En flerbyteskrivning avslutas med STOP direkt efter första byte som inte kvitteras. Simulerat mot slavmodellen (`sim/test_i2c_master.py`), inte provat mot en TVP5150AM1. Dekoderns init-lista är oförändrad och patchen används inte. För att använda den krävs:
- patchdata och laddningsordning från TI. Datan är TI:s och ligger inte i repot; licensen avgör om den kan ligga där eller måste läsas från flash;
- ett laddsteg i `tvp_ctrl.v` som matar `wreq` ur block-RAM eller flash, i den ordning TI anger relativt reset och init-listan, och som görs om när en återställd dekoder startas om;
- en kontroll av att patchen är laddad, som M3-proben kan visa;
- tid: vid 99 kHz tar varje byte 91 µs, alltså ungefär 0,1 s per kilobyte och dekoder;
- prov på kortet med och utan patch.

**Dekoderns init-lista** (`rtl/tvp_ctrl.v`, båda dekodrarna, i den här ordningen): 00h = 00h (ingång AIP1A), 04h = FCh (SECAM, NTSC 4.43, PAL-N och PAL-M maskade ur autoswitchen), 0Dh = 47h (8 bit BT.656, inbäddad synk), 28h = `VIDEO_STD` (standard 00h), 02h = `selected_mode`, och sist 03h = 0Dh (utgångarna på; läses tillbaka vid varje pollning). Vid reset får `selected_mode` värdet från `OP_MODE`, som är 30h (TV). M6:s meny kan begära TV eller VCR för båda dekodrarna. Värdena är ur SLES209E (3.21.3, 3.21.5, 3.21.32).
- **28h = 00h, autoswitch**, uttryckligen skrivet fast det är standardvärdet, så att båda dekodrarna är inställda lika efter varje återstart. Dekoderunderlaget i navet (avsnitt 2) föreslår att låsa NTSC eller PAL, så att två dekodrar i brus inte kan välja olika standard. Pucken tar kameror med båda standarderna (PAL ger 288 rader i `BUF` och 720p50 i `LOW`), och en låst standard skulle ta bort den andra. Därför gäller autoswitch, begränsad av 04h till (M) NTSC och (B, G, H, I) PAL. Att dekodrarna kan välja olika i brus kvarstår som risk.
- **02h — TV/VCR-läge.** TV, 30h (bit 5:4 = 11), är standard vid reset; 20h väljer VCR (bit 5:4 = 10), medan 01 är reserverat. M6:s filterfält begär samma läge för båda dekodrarna. TV behåller kamfiltret; VCR stänger av det och slår på färgfällan. Vilket läge som ger bäst bild eller lås vid svag signal är inte mätt. Båda ska jämföras med den avsedda kameran och signalen på bänken. M4 behåller sitt `OP_MODE`-parametergränssnitt; menyvalet finns i M6.

Simulerat i `sim/test_tvp_ctrl.py`: init-listans registerordning, två dekodrars TV/VCR-värden, senaste menyval, kvittens för en äldre pågående överföring samt NACK och omförsök efter parad pollning. Negativa kontroller kör verkliga felvarianter av styrenheten och granskar den upplösta I²C-bussens stiftspår. Inte provat mot en riktig TVP5150AM1.

M4 ställer själv båda mottagarna på F4 5800 MHz (`rtl/rx5808_tune.v`, samma stift som M3 och M6): 0,5 s efter start och sedan varannan sekund så länge ingen dekoder är låst. Testat mot en modell av regeln i `sim/test_rx5808_tune.py`.

RESETB låg på PIN25 (J6-10) till 2026-10-05. Stift 25–42 (bank 4 och 5) bär HDMI-paren, och en vanlig utgång där ändrar hur Apicula packar klockparet: se [BRINGUP.md](BRINGUP.md) avsnitt 5. Stiften till lysdiod 3–5 används därför som stiftlistestift (J6-18, J6-17, J6-16), och toppmodulerna M3, M4 och M6 har bara tre lysdioder. `tools/test_tmds_bank_outputs.py` vaktar att ingen toppmodul med HDMI har en vanlig utgång eller in/utgång på stift 25–42, och `tools/tmds_fuses.py` jämför färdiga bitströmmars HDMI-par mot M0. Kör testet efter varje Apicula-uppgradering, som `tools/test_lvds_bank_inputs.py`.

**Dekoderstatus i mixern** (`rtl/dec_bad.v`, M4 och M6, sedan 2026-10-21): alla rader från en dekoder är dåliga (`ext_bad`) om inte dess senaste pollrunda var hel och läste H- och V-lås. Okänd status räknas alltså som dålig: före första rundan, efter en runda med NACK och efter en återinitiering. Förut var bara en giltig status utan lås dålig, och en frilöpande dekoder, vars rader kommer i takt och kan vara platta, kunde vinna paren just medan statusen var okänd (navets `docs/design/2026-10-21/LOGIKGRANSKNING.md`, F4). En ensam dekoder visas ändå, eftersom dåliga rader i följd visas. Statusen läses oftare: pausen mellan pollrundorna är 2 ms i stället för 20 (`TVP_POLL_MS`), så 88h läses ungefär var 5:e ms per dekoder i stället för var 26:e (simulerat med OLED:n och RSSI-läsningen på samma buss). Simulerat: `sim/test_dec_lock.py` (tvp_ctrl, två dekodermodeller, `dec_bad.v` och mixern; A en riktig bild, B platt i takt; B låst, sedan olåst med en runda med NACK emellan): inget beslut använder B en pollrunda plus två rader efter låsförlusten; negativ kontroll: den gamla regeln använder B i det fönstret. `sim/test_rssi_adc.py::test_faster_decoder_polls_leave_the_bus_to_the_others`: med två svarande dekodrar och 2 ms paus läses 88h var 5,4 ms, RSSI-rundorna är oförändrade, inga krockar, och OLED:n får lika många bilder som med 20 ms (5); negativ kontroll: utan paus svälter OLED:n (1 bild). Med 1 ms paus fick den 4, därför 2 ms. Hur platt en frilöpande TVP5150AM1 är har bänken inte mätt. Med `DIGIN=1` gäller regeln bara dekoder A: kanal B:s rader är dåliga medan `cvbs_capture` saknar lås (`mixer2.v` `b_lock`), och hjärtslaget och RX5808-avstämningen räknar B:s lås i stället för TVP B:s status (uppgift 69, sedan 2026-10-26).

Lysdioder (tänd = sant): LED0 hjärtslag, 2 Hz när båda dekodrarna svarar på I2C och rapporterar H- och V-lås, 1 Hz när en gör det, 4 Hz när ingen gör det (sedan 2026-10-21, navets LOGIKGRANSKNING F2: förut 1 Hz bara med båda, så en bänk med en modul såg aldrig låset; `sim/test_top_pins.py::test_m4_one_decoder_locked_led0_at_1hz`). LED1 rader från A, LED2 rader från B, utom de första 3 sekunderna (nedan). Testat i simulering av hela toppmodulen (`sim/test_top_pins.py`).

**SDRAM-självtestet** (`rtl/sdram_selftest.v`, i `fb_backend.v` med `SELFTEST = 1` i M4 och M6, sedan 2026-10-21). Efter SDRAM-starten och före fältminnet skrivs två skurar om 8 ord (gående ettor i varje byte, adressmönster) till buffert 3, rad 1023, som inget fält når (bank 3, rad 2046), och läses tillbaka med läspunkt 4, 5 och 6. Inom en skur skiljer sig varje ord från grannarna, så en läspunkt en klocka för tidigt eller sent faller, och högst en läspunkt klarar sig. Testet tar under 300 SDRAM-klockor; fältminnet hålls i reset så länge. Det visar alltså i varje bygge av M4 och M6 det som M2a-svepet visar i sitt eget.

| Läspunkt som läste båda skurarna rätt | M4, lysdiod 1 / 2 de första 3 s | M6, sista tecknet i loggraden |
|---|---|---|
| 5 (standard) | tänd / släckt | `2` |
| 4 eller 6 | släckt / tänd | `1` eller `4` |
| ingen | tänd / tänd | `0` |
| testet har inte körts | (hjärtslag och rader som vanligt) | `-` |

Simulerat mot `sim/sdram_model.v` i `sim/test_sdram.py::test_sdram_selftest` med fördröjningarna i M2a-tabellen ovan: 3 + 3 ns vid 225° ger läspunkt 5, 3 + 17 ns läspunkt 6, 0 ns vid 180° läspunkt 4, 1 + 1 ns vid 270° läspunkt 5; negativa kontroller: en tur och retur 0,1 ns under läsfönstret och 1 + 1 ns vid 225° ger ingen. I toppen (`sim/test_top_pins.py`) ger modellen läspunkt 5 i M4 och M6 och lysdiod 1 tänd i fönstret; negativ kontroll: utan modell på stiften lyser båda. Inte kört på kortet.

## M5 alt. C — Moneagle → 1080p60 → LT8618SX → XR-glasögon

> **Ingår inte i det här repot:** toppmodulen `m5c_moneagle_1080p.v`, `lt8618_ctrl.v`, `lt8618_rom.vh`, `model/lt8618_seq.py` och deras test. LT8618SX-sekvensen är härledd ur en leverantörsdrivrutin vars källfil är märkt konfidentiell, så den publiceras inte förrän ursprunget är utrett. BT.1120-utgången (`bt1120_tx.v`, `sim/test_m5c.py`) ingår.

`top/m5c_moneagle_1080p.v` → `build/m5c_moneagle_1080p.fs`. Samma Moneagle-avtappning som M2 (SCLK J6-5 + YOUT0–7), men utgången är 1080p60 som 16-bitars BT.1120 till en LT8618SX (HDMI-sändare), eftersom XR-glasögonen vill ha 1080p60 och FPGA:ns egna serieutgångar inte räcker till det. Halvbilden (720×240) fyller ett 1440×1080-fönster (x 240–1679: varje pixel ×2 i sidled, raderna Bresenham-mappade); svarta kanter.

| Signal | Tang Nano 20K | LT8618SX |
|---|---|---|
| Pixelklocka 148,5 MHz | PIN76 (J5-3) | DCLK |
| Y0–7 | PIN80, 42, 41, 56, 54, 51, 48, 55 (J5-4…J5-11) | D8–D15 |
| C0–7 (Cb/Cr växelvis) | PIN49, 86, 79, 72, 71, 53, 52 (J5-12…J5-20) + PIN25 (J6-10) | D16–D23 |

**Varning (2026-10-04):** PIN52/53 är SSPI-konfigurationsstift och HDMI-DDC på Tang-kortet. M5C behöver ny stiftplan innan den provas.
| I2C SCL / SDA | PIN75 (J6-3) / PIN85 (J6-4) | SCL / SDA |
| Reset | — (inget stift kvar) | RC-reset: 10 k till 3,3 V + 1 µF till jord |

Alla 28 lediga stift används. 148,5 MHz över stiftlistetrådar är på gränsen — korta trådar, gärna jord emellan; detta steg är främst till för att verifiera glasögonen och LT8618SX-sekvensen innan rev A.

FPGA:n kör LT8618SX-sekvensen efter uppstart (anteckningen `LT8618SX_INIT.md` är inte publicerad, se rutan ovan). Osäkert och därför lätt att ändra: I2C-adressen (`lt8618_ctrl` parameter `DEV`, antagen 39h = 72h i 8-bitsform), klockflanken (`CLK_INVERT` i toppen, eller LT-register 82:4F) och om LT:n behöver radnummer/CRC efter EAV (finns inte). Lysdioder: LED0 hjärtslag, LED1 BT.656-rader, LED2 SDRAM klart, LED3 halvbild visas, LED4 LT8618SX-sekvensen klar, LED5 LT8618SX-fel (inget I2C-svar eller TX-PLL olåst).

Var hittar man en LT8618SX att koppla till? Ingen färdig breakout är verifierad än (se `design/REV_A_KONCEPT.md` i OpenVRX-Puck). Det här bygget är förberett för den dagen — eller för rev A, där samma gateware används.

## M6 — puckprototyp steg 1 (M4 + meny, RX5808, OLED)

> Koppling, uppstartsordning och felsökning steg för steg: [BRINGUP.md](BRINGUP.md). Ändrat 2026-10-04: SPI DATA och SEL flyttade från PIN53/52 (konfigurationsstift och HDMI-DDC på kortet) till lysdiodsstiften 19/20. Ändrat 2026-10-05: RESETB flyttad från PIN25 till lysdiodsstift 18 (se M4). Lysdioderna i M6 är tre, samma som i M4: LED0 hjärtslag (2 Hz när båda dekodrarna är låsta, 1 Hz när en är det, annars 4 Hz), LED1 rader från A, LED2 rader från B. M6 visar SDRAM-självtestet i loggen, inte på lysdioderna.

`top/m6_puck_proto.v` → `build/m6_puck_proto.fs`. Allt från M4 plus:

| Signal | Tang Nano 20K | Ansluts till |
|---|---|---|
| RX5808 SPI CLK | PIN71 (J5-18) | båda modulernas "CH3" |
| RX5808 SPI DATA | PIN19 (J6-17, lysdiod 4) | båda modulernas "CH1" |
| RX5808 SEL | PIN20 (J6-16, lysdiod 5) | båda modulernas "CH2" |
| OLED SSD1306 128×32 (I2C 3Ch) | SCL PIN75 (J6-3), SDA PIN85 (J6-4) | samma buss som dekoder A; OLED-modulen matas med 3,3 V |
| RSSI-ADC ADS1115 (I2C 48h) | samma SCL/SDA | på Puck rev A-kortet: AIN0 mottagare A, AIN1 mottagare B (Puck `design/rev_a/README.md`, avsnitt RSSI) |
| SPI-flash på kortet (XT25F64F) | CS PIN60, CLK PIN59, DI PIN61, DO PIN62, WP# PIN57 | kortets egen flash, efter konfigurationen; ingen extern koppling |
| ▼-knappen (nästa post, nästa sida) | S1 (PIN88) | kortets knapp — **inte längre reset** |
| ▲-knappen (ändra, meny, kalibrering) | S2 (PIN87) | kortets knapp |

RX5808-modulerna måste ha "SPI-moden" (annars styrs de av sina kanalstift). Deras videoutgång går till TVP-modulernas videoingångar. På bänken får de 5 V från en egen matning med gemensam jord ([BRINGUP.md](BRINGUP.md) avsnitt 1); rev A-kortet har inga mottagare (Puck `design/REV_A_KONCEPT.md`).

S1 och S2 sitter på FPGA:ns MODE0 och MODE1. Håll ingen av dem intryckt när kortet får ström, annars laddas bitströmmen inte från flash ([BRINGUP.md](BRINGUP.md) avsnitt 5).

**Flygvyn** (startläge; sedan 2026-10-19, navets `docs/UI_FLYGVY_2026-10-19.md` med renderade bilder). Rad 1 är dubbelhög (10 tecken, `ssd1306_text.v` `text_big`), rad 3 och 4 enkelhöga med 21 tecken:
```
F4 5800  @

A:LOCK  75 B:NOSIG --
MIX BUF TV      SAVED
```
Rad 1: band och kanal, MHz, `!` för kanal utanför 5725–5875 MHz, hänglås (`@` i teckensnittet) när kanalspärren `HOLD` är på. Rad 3: dekoderstatus per mottagare (`LOCK`, `NOSIG`, `----` = svarar inte på I2C) och kalibrerad RSSI (` --` okalibrerad, `  ?` ingen avläsning). Rad 4: mixläge, latensläge, filter och sparstatusen från `flash_store.v` (`dirty`, `stored`, `err`, `ready`): `SAVED` när flashen har en post med just de här inställningarna, `UNSAVED` när något är ändrat (posten skrivs 3 s efter sista ändringen och läses tillbaka innan texten byter), `SAVE ERR` när en skrivning inte lästes tillbaka rätt, `DEFAULTS` när flashen saknar post och inget är ändrat, tomt tills startavläsningen är klar. Knapparna har inga namn; skärmen visar dem som pilar (teckensnittets `^` och `v`): ▼ är S1, ▲ är S2 (ägaren 2026-10-20). I flygvyn öppnar ▲ menyn och ▼ bläddrar till informationssidorna (mätare → RSSI → flygvy); ingen knapp i flygvyn ändrar kanalen.

**Menyn**: en post per skärm, posten och värdet dubbelhögt på rad 1, rad 3 vad värdet betyder, rad 4 vad knapparna gör (`^ CHANGE  v NEXT ITEM`). ▼ går till nästa post och efter den sista tillbaka till flygvyn; ▲ ändrar posten. Efter 15 s utan knapptryck (`MENU_MS`) går menyn tillbaka till flygvyn av sig själv, utom under en skanning. Posterna i ordning: `BAND`, `CH` (rad 3: kanal, MHz, `SE OK` eller `!SE`), `MODE` MIX/A/B, `LAT` BUF/LOW (videoväg, se nedan), `FILT` TV/VCR (rad 3 `DECODER MODE REQUEST`: en begäran till dekodrarna, inte en återläsning), `HDMI` FULL/LTD (omfånget i HDMI-bygget, se "Omfånget i HDMI-läget" under M0; i DVI-bygget, standard, står `HDMI N/A` och `DVI BUILD: NO EFFECT`, och ▲ gör inget: toppen ger menyn `HDMI_BUILD`), `SCAN` (nedan) och `HOLD` OFF/ON. `HOLD` ON gör `BAND`, `CH` och `SCAN` döva (rad 4 säger `HOLD ON`) och visar hänglåset i flygvyn; spärren sparas inte och är av efter start. Filtervalet (register 02h i båda dekodrarna) återställs till TV vid reset; det är oberoende av MIX/A/B och BUF/LOW. Band- och kanalbyte programmerar om båda mottagarna direkt. Kanalen skrivs också 0,5 s efter start och sedan varannan sekund så länge ingen dekoder är låst (`rtl/rx5808_tune.v`). MIX låter mixern välja; A eller B tvingar en mottagare. Start: F4 5800 MHz, MIX, BUF, `TV`, `HDMI FULL`, `HOLD OFF`. Före 2026-10-19 var allt en sida med fyra rader, `>` före valt fält och OK som flyttade markeringen genom åtta fält (`>BAND F   CH 4  5800` …); ägaren fann den oläslig på en 0,91-tums skärm (tecknen är 0,9 × 1,2 mm). Skärmraderna fylls med blanktecken; avslutande blanktecken är utelämnade i exemplen.

**Avstämning av dekoderläget:** styrenheten tar emot senaste menyvalet och jämför det med senast kvitterat värde per dekoder. Efter båda startinitieringslistorna sker en första avstämning före pollningen. Därefter sker den vid den avslutande gränsen efter båda dekodrarnas pollförsök: vid normala svar efter båda kompletta 88h/89h/03h-tripletterna. Ett NACK avslutar pollförsöket utan att räknas som en hel frisk runda. Varje avstämning försöker skriva till varje dekoder högst en gång. Ett påbörjat I²C-skrivvärde och dess SDA-linje hålls fasta till transaktionens slut. En kvittens för ett äldre val registrerar värdet som faktiskt skrevs och lämnar ett nyare val väntande. Vid NACK behålls tidigare kvitterat värde; pollningen fortsätter och ett nytt försök kommer vid en senare avstämning. Lägestransaktionen ändrar inte F/register 15h, `round_ok`, `status_valid`, `dev_err`, statuspublicering eller låsförlustvärdet; dessa uppdateras fortfarande av vanliga poll- och återinitieringsvägar.

**Mätarsidan ("snö-mätare")**: ▼ i flygvyn. ▼ igen ger RSSI-sidan, sedan flygvyn; ▲ öppnar menyn.
```
 METER   F4  5800
A  12345 ########
B   2345 ######
 USE A 40 B 34 M 25
```
Talen är medel-HF-energin per bildrad (summan |Y[n]−Y[n−1]|, samma mått som mixern väljer på) över 1 024 rader (≈ 65 ms) per mottagare. Stapeln är logaritmisk: ett block per fördubbling över 32. `  ----` betyder att inga rader kommer från den mottagaren. USE = andel av de senaste 1 024 mixerbesluten som visade A, B eller en blandning. Talen räknas om i `snow_stats.v` (mixerns klockdomän) och visas via en sekventiell decimalomvandlare (`bin2bcd.v`).

Används för egenstörningsmätningen i `design/PUCK_2027_KONCEPT.md` i OpenVRX-Puck ("Inbyggt mätinstrument"): stillastående kamera, VTX på fast avstånd, jämför värdena med HDMI på/av, kanal F4 mot andra kanaler, mottagarna på olika avstånd och med/utan skärmburk. Måttet beror också på bildinnehållet, så bara jämförelser med samma motiv betyder något.

**OSD i videon** (`osd_overlay.v`): samma tecken som OLED:n i en storlek (den dubbelhöga raden blir rad 1, rad 2 tom), 3× förstorade, vita på en halvmörk platta längst ned i 4:3-fönstret (x 176, y 576 i 720p). Syns i 5 s efter varje knapptryck och hela tiden i menyn och på informationssidorna, så att menyn går att läsa i bilden, utan att se på pucken. Pixelexakt testad (`sim/test_osd.py`). I M6-toppen har spegelns räknare reset sedan 2026-10-21 (förut startade de som X i simuleringen, så OSD-texten skrevs aldrig där; på kortet startar de på 0); `sim/test_top_pins.py::test_m6_pins` kontrollerar att OSD-minnet håller menytexten, med en negativ kontroll utan reset.

**Mätlogg över USB** (`uart_tx.v`, PIN69 → kortets BL616 USB-UART, 115200 8N1): en rad per mätfönster (≈ 15/s), och en gång i sekunden när inget fönster kommer (sedan 2026-10-21; utan rader från någon dekoder står snö och brus som `------`), 89 byte inklusive CR LF:
```
S 012345 002345 000017 000000 040 034 025 F4 5800 MIX T F - -- 12000 04567 075 003 -W 2
```
snö A, snö B, brus A, brus B (`------` = inga rader), % av mixerbesluten från A / B / blandning, kanal, MHz, mixläge, filter (`T` = TV, `V` = VCR), HDMI-omfånget (`F` = FULL, `L` = LTD, menyvalet; står också i DVI-bygget, som inte använder det), `!` om mixern sedan start har tappat en rad för att dess radplatser var fulla (annars `-`), och sist ett tecken per dekoder (A, B) för tiden sedan förra raden: `L` om någon hel pollrunda läste "lost lock" (88h bit 4), `-` om rundorna inte gjorde det, `?` om ingen hel runda kom (dekodern saknas eller hittades återställd). Därefter RSSI A och B (rå kod, `-----` utan avläsning), kalibrerat värde A och B (`---` okalibrerat) och ett tecken per mottagare: `W` svag (mixern undviker den), `L` låg men inte svag, `-` ingetdera, `?` ingen avläsning. Sist SDRAM-självtestet: `-` inte kört än, annars en siffra 0–7 vars bit 0, 1, 2 betyder att läspunkt 4, 5, 6 läste testskurarna rätt (under M4, "SDRAM-självtestet"). Bitströmmar före 2026-10-21 skickar raden utan självtestet (87 byte), före 2026-10-18 utan HDMI-tecknet (85 byte), före 2026-10-13 utan RSSI-fälten (62 byte); äldre skickar den utan filtertokenen (60 byte), utan filtertokenen och låsfältet (57 byte) eller utan brusvärdena (43 byte); `snowlog.py` läser även dessa äldre former, och kolumnerna de saknar blir tomma. En 87-byterad som tappat HDMI-tecknet på vägen har tre blanktecken efter filtret och räknas som skadad. För nya rader valideras den separata T/V-tokenen och skadade rader räknas som damaged. Filtertecknet visar menyvalet som begärts, inte en återläsning av dekoderns 02h-register. En pågående överföring eller ett NACK kan därför lämna en dekoder i tidigare läge tills avstämningen lyckas.

**Kommandon från datorn** (byggvalet `DEVCMD=1`, sedan 2026-10-23, uppgift 58; standard av tills ägaren beslutat, navets `docs/NATTPASS_2026-10-23.md` B4). `DEVCMD=1 gateware/build.sh m6_puck_proto` ger `build/m6_puck_proto_devcmd.fs`: en UART-mottagare (`uart_rx.v`) på stift 70, där kortets BL616 skickar det datorn skriver på samma serieport som loggen, i loggens takt. Varje kommando är en byte och sätter ett värde, så en upprepning ändrar inget:

| Byte | Gör |
|---|---|
| `B` / `L` | latensläge BUF / LOW |
| `T` / `V` | filter TV / VCR (en begäran till båda dekodrarna, som menyn) |
| `m` / `a` / `b` | mixläge MIX / tvinga A / tvinga B |
| `H` / `h` | `HOLD` på / av |
| `+` / `-` | kanal upp / ner genom alla 48, band för band med omslag; skriver mottagarna direkt; döv under `HOLD` och skanning, som menyn |
| `O` / `o` / `*` | OSD alltid på / alltid av / som knapparna bestämmer (efter reset) |
| `?` | en statusrad efter den loggrad som skickas |
| `D` / `F` | fältdumpen ur dekoder A / ur fältminnet (uppgift 59) |

Andra byte ignoreras och räknas inte. En inställning som ändras så sparas i flashen som en menyändring. Loggraden får 12 byte till före CR LF (101 byte): latensläget, `HOLD` (`H`/`-`) och OSD (`A` knapparna, `O` på, `-` av) i en token, och sist senast mottagna kommando och antalet mottagna kommandon, två hexsiffror vardera (räknaren slår runt vid 256), så att varje kommando syns i nästa rad:
```
S 012345 002345 000017 000000 040 034 025 F4 5800 MIX T F - -- 12000 04567 075 003 -W 2 LOW HA 4C07
```
Statusraden (52 byte) har per dekoder adressen den svarar på (`5C`/`5D`, `NA` inget svar, `--` uppstarten inte klar), 89h och 88h ur senaste hela pollrundan (`----` ogiltig), 03h som senast läst (`--` inte läst än) och antalet gånger den hittats återställd; sedan SDRAM-självtestet, bygget (`H` HDMI, `D` DVI), adressen som provas först och UART-takten:
```
Q A 5D 100E 0D 00 B NA ---- -- 03 T 2 D 5C 0115200
```
`tvp_ctrl.v` har för det fått utgångarna `misc0`/`misc1`/`misc_ok` (03h ur senaste hela rundan); inget annat i styrningen är ändrat. Utan byggvalet finns varken porten eller mottagaren, och loggraden är 89 byte som förut. `tools/m6ctl.py L` skickar ett kommando och väntar på raden som visar det (eko och räknare ett steg upp), `tools/m6ctl.py '?'` skriver statusraden tolkad; `snowlog.py` läser 101-byteraden (kolumnerna `lat`, `hold`, `osd`, `cmd`, `cmd_count`). Simulerat mot `model/m6_cmd_ref.py` (`sim/test_m6_cmd.py`: varje kommando en gång, och två byte som inte är kommandon, med en loggrad mellan varje par; raderna, statusraden och modulens utgångar mot modellen, kanalsteg över bandgränsen åt båda hållen, `+` under `HOLD`). Negativa kontroller: `DEVCMD = 0` med samma byte (89-byterader, ingenting ändras) och sex kopior av `puck_ui.v` där ett kommando saknar verkan (LOW, filterbegäran, mottagarskrivningen vid `+`, statusraden, räknaren, OSD-tvånget). `tools/test_m6ctl.py` provar kvittot mot en låtsaskort på en pty, med två negativa kontroller. Inte provat på kortet.

**Fältdumpen** (`field_dump.v`, i `DEVCMD=1`-byggen sedan 2026-10-23, uppgift 59). `D` skickar ett fält ur dekoder A:s ordström före mixern (det `chan_capture.v` lämnar, i dekoderns klocka: det dekodern levererar), `F` ett fält ur mixerns utström som fältminnet tar emot den (i SDRAM-klockan: det som skrivs in i fältminnet, inte återläst ur SDRAM:en). Båda har samma ordformat, `{fält, rad, index, Y1 Cr Y0 Cb}` med 360 ord per rad. Rad för rad, 0 till 319: styrenheten ber uttagets radinfångare om rad n, infångaren skriver nästa förekomst av raden, alla 360 orden i ordning från index 0, till ett block-RAM (ett per uttag, alltså två BSRAM till), och raden skickas. En rad som bryts av kastas och nästa förekomst väntas in. Efter första raden som kommer tas bara rader med samma fältbit, så en sammanflätad källa ger ett fält. En rad som inte kommer inom 45 ms skickas som saknad. Bilden tas alltså över många fält, ungefär en rad per fältperiod: exakt per rad, en ögonblicksbild bara av en stillastående källa. Under dumpen väntar loggraderna; den rad som håller på att skickas får gå klart först (även sista byten), och efter dumpen fortsätter loggen och visar kommandot.

Ram, talen med mest signifikant byte först: `A5 5A`, typ (`D`/`F`), radnummer (2), flaggor (bit 0 radens fältbit, bit 1 saknad, bit 2 slut, bit 3 fältmatchning på), längd (2; 1 440 eller 0), raden som dekodern skickade byten (`Cb Y0 Cr Y1 …`), CRC-16/CCITT-FALSE (2) över typ till sista databyten. Efter rad 319 kommer en slutram. `tools/fielddump.py D --out a` skickar kommandot, tar emot till slutramen, kontrollerar varje ram och skriver `a.bin`, `a_y.png` (luma, 720 × rader), `a_rgb.png` (BT.601) och `a.json` (rader, saknade, CRC-fel, fältbit); `--from a.bin` avkodar igen. Vid 115 200 baud tar en rad 125 ms att skicka, ett NTSC-fält cirka 35 s; byggvalet `UART_BAUD=921600` (log, kommandon och dump; delaren 29 ger 931 034 baud, +1,0 %) kortar det till cirka 8 s. Om kortets BL616 tar 921 600 är inte provat.

Simulerat (`sim/test_field_dump.py`): två syntetiska ordströmmar med egna klockor, uttag 0 med två fält med olika innehåll och en rad som aldrig kommer, uttag 1 med en rad som bryts av vartannat fält; byten på stiftet lika med `model/field_dump_ref.py` byte för byte, `fielddump.py` bygger upp båda fälten exakt. I M6-toppen (`sim/tb_top_pins.v` med `DEVCMD`): `D` på stift 70 mitt i en loggrad, raden går klart, tre ramar (två saknade rader, slutramen; videon stoppad) hela på stift 69, sedan loggen med ekot. Negativa kontroller: en ändrad databyte och en ändrad CRC-byte fälls av CRC:n, en kopia utan fältmatchning fäller bytejämförelsen. Två fel hittades av testen innan de kom in: dumpen släppte stiftet innan slutramens sista byte var ute, och loggsidan sade ledig när radens sista byte (LF) just lämnats till sändaren. Inte provat på kortet.

**88h bit 4** betyder enligt SLES209E 3.21.49 att låset har tappats sedan status 1 lästes senast. Dekodern nollställer biten själv när 88h läses, och `tvp_ctrl.v` läser 88h i varje pollrunda (i M4 och M6 sedan 2026-10-21 ungefär var 5:e ms per dekoder, förut ungefär var 26:e ms). En loggrad omfattar flera rundor, därför samlas biten över alla rundor sedan förra raden. Utöver läsningen nollställs biten inte, och mixern använder den inte: det ska avgöras på riktig signal om den säger något som H- och V-låset inte redan säger. Simulerat mot slavmodellen, som nollställer biten vid läsning som databladet anger (`sim/test_tvp_ctrl.py::test_lost_lock_flag`, `sim/test_puck_ui.py`).

**Brus** (`noise_stats.v`) är antalet lumasampel utanför 16–235 under de senaste 1 024 raderna från mottagaren (en rad har 720). BT.656 tillåter 1–254, men en dekoder håller bildens luma inom 16–235, så det som hamnar utanför är brusklick och störd synk. Till skillnad från snövärdet beror det inte på hur detaljrik bilden är. Det räknas på orden som lämnar kanalens FIFO, innan mixern väljer, och mixern använder det inte. Simulerat mot `luma_outside()` i `model/bt656.py` (`sim/test_noise_stats.py`); om det skiljer brus från bildinnehåll på riktig signal är inte provat. Det visas bara i loggen, inte på OLED:n.

På datorn (Windows: `COM5` i stället för `/dev/ttyUSB1`; den vägen är inte provad mot en riktig port):
```
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_pa --seconds 30 --out emi.csv
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_av --seconds 30 --out emi.csv
python gateware/tools/snowlog.py --summary emi.csv
```
(BL616 visar två serieportar; UART:en är oftast den andra.) Sammanfattningen visar medianen per etikett, alltså en mätserie per testvillkor. CSV:n har kolumnerna `time, label, snow_a, snow_b, noise_a, noise_b, use_a, use_b, use_mix, channel, mhz, mode, filter, hdmi, dropped, lost_a, lost_b, rssi_a, rssi_b, rssi_pct_a, rssi_pct_b, rssi_state_a, rssi_state_b, sdram, lat, hold, osd, cmd, cmd_count` (de fem sista bara med `DEVCMD=1`; `hdmi`: F, L eller tomt; `lost_*`: 1, 0 eller tomt för `?`; `rssi_state_*`: W, L, - eller tomt), och sammanfattningen räknar rader med tappat lås per dekoder; `snowlog.py` vägrar lägga till rader i en fil med andra kolumner, alltså också i en fil skriven före kolumnen `hdmi` (2026-10-18).

**Kanalskanning** (`chan_scan.v`, sedan 2026-10-13): ▼ till posten `SCAN` i menyn, ▲ startar. Mottagarna stegas genom alla 48 kanaler i tabellordning (A1 … L8). På varje kanal väntar skanningen 30 ms och sedan två brusfönster per mottagare (1 024 rader vardera; det första kan ännu innehålla rader från förra kanalen). En mottagare räknas om dess andra fönster kom inom 200 ms och dess dekoder är låst när kanalen avgörs. Kanalens poäng är det lägre brusvärdet av de mottagare som räknas, och lägst poäng vinner; vid lika poäng behålls startkanalen, annars den tidigare kanalen (två rena sändare ger båda 0, och pilotens egen kanal ska inte förlora mot en lägre tabellpost: granskning 2, Core #22). RSSI används inte som avgörande ännu; det är nästa steg när bänken visat hur RSSI och brus hänger ihop. Hittas en kanal slutar menyn i flygvyn med den nya kanalen. Låser ingen kanal blir startkanalen kvar och skärmen visar `SCAN NONE` / `NO LOCKED CHANNEL` till nästa knapptryck. Medan skanningen pågår står `SCANNING`, kanalen som provas och `ANY BUTTON ABORTS`; varje knapp avbryter skanningen och ställer tillbaka startkanalen utan att göra något annat, och SCAN-skärmen står kvar som den var (före 2026-10-19 visade den `NONE` även efter ett avbrott). Det tar 100–160 ms per kanal, 5–8 s för alla. RSSI används inte; skanningen fungerar utan ADS1115. Simulerat mot `model/chan_scan_ref.py` (`sim/test_chan_scan.py`: poängen räknas ut ur testbänkens händelser, inte ur RTL:en), negativa kontroller med första fönstret, högsta bruset och utan lås; i menyn `sim/test_puck_ui.py` (start, kanalordning, avbrott). Vilken kanal den väljer med riktiga sändare är inte provat.

**Sparade inställningar** (`flash_store.v`, sedan 2026-10-13): band, kanal, mixläge, latensläge, filter, HDMI-omfång och RSSI-kalibreringen sparas i kortets SPI-flash (XTX XT25F64F på FPGA:ns MSPI-stift 59–62 och WP# på 57, enligt Sipeeds schema för rev 3923) och läses vid start, inom cirka 10 ms, före första kanalskrivningen. Säger flashen fortfarande upptagen 1 s efter att en radering eller programmering började (ingen flash, flash i viloläge, MISO hålls hög av sin pull-up), ges skrivningen upp: `err` sätts och WP# släpps (sedan 2026-10-21, LOGIKGRANSKNING F9; `sim/test_flash_store.py::test_flash_that_does_not_answer`, negativ kontroll utan tidsgräns). Bygget ger M6 `gowin_pack --mspi_as_gpio` så att stiften blir vanliga I/O efter konfigurationen. Två 4 KB-sektorer högst upp (7FE000h och 7FF000h, långt över bitströmmen, som slutar under cirka E0000h) håller 512 poster om 16 byte: A5h, löpnummer, inställningarna, antalet nollbitar i de 13 byten före (Z), FFh och CRC-8. En post godtas bara om allt det stämmer och band och läge är sådana menyn kan ställa. HDMI-omfånget (2026-10-18) tog en av nollbitarna efter filtret i posten, så en post från en äldre bitström laddas som `FULL` (`sim/test_flash_store.py::test_hdmi_bit_is_saved_and_old_records_read_full`; i M6-toppen, från flashen till menyn och `tmds_link.v`, med negativa kontroller: `sim/test_m6_settings.py`). Z fångar varje fel åt ett håll, alltså en radering eller programmering som ett strömavbrott stoppade halvvägs; med bara `A5` och CRC godtogs en aldrig skriven post i upp till en fjärdedel av de avbrutna raderingarna i en enkel bitmodell, och nästa sparande raderade då sektorn med den riktiga posten (granskningen 2026-10-14, FL-1; `sim/test_flash_store.py::test_interrupted_erase_loads_only_written_records`). Nya poster läggs efter den senaste; en sektor raderas först när den andra är full, alltså en gång per 256 sparanden. Vid start används den giltiga posten med nyaste löpnumret. En post skrivs bara när inställningarna har ändrats och sedan legat stilla i 3 s, så en skanning eller en kalibrering ger en skrivning när den är klar, inte en per steg. Varje skrivning läses tillbaka. Flygvyn visar läget (`dirty`: inställningarna skiljer sig från nyaste posten, från ändringen tills återläsningen är klar; `stored`: flashen har en post, laddad vid start eller skriven sedan dess; `err`; `ready`): `SAVED`, `UNSAVED`, `SAVE ERR`, `DEFAULTS` (sedan 2026-10-19; `sim/test_flash_store.py::test_save_status_follows_the_record` med tre negativa kontroller). WP# drivs högt bara från skrivaktiveringen till slutet av programmering eller radering: en annan konstruktion på samma kort som höll WP# högt hela tiden störde programmeringen av flashen över USB. Kommandona (03h, 06h, 05h, 02h, 20h) är de som openFPGALoader använder för att programmera just den här flashen; XTX:s datablad gick inte att läsa, och tiderna (0,4 ms per sida, 65 ms per sektor) kommer från en distributörs sammanfattning. Simulerat mot `model/flash_store_ref.py` med en flashmodell (`sim/test_flash_store.py`: tom flash, snabba ändringar, ingen ändring, full sektor med skräp i den andra, trasig nyaste post, löpnumret förbi FFFFh, omstart på resultatet; hela avbilden byte för byte), negativa kontroller utan CRC-kontroll, utan radering, utan väntan och utan WP#. Inte provat på kortet: att skrivningen fungerar, och att programmering av bitströmmen över USB lämnar de två sektorerna kvar. Enligt openFPGALoaders källkod raderar den bara det område den skriver, avrundat uppåt till 4 eller 64 KB, och bitströmmen slutar långt under 7FE000h. Hur sektorerna läses och raderas, och vad M6 gör med tom eller skadad flash: [BRINGUP.md](BRINGUP.md) avsnitt 2.3.

Byggt ur `0958a52`, seed 2, standardval (siffror efter routning, inga `ERROR`, manifestet säger `mspi` 1): M6 med skanning och sparade inställningar 15 505 LUT4 (14 233 med bara RSSI), 25 BSRAM; `clocks.clk_27` 132,28 MHz, pixelklocka 123,15 MHz, `sd_clk` 104,58 MHz, A 248,69 MHz, B 204,33 MHz. Alla klockor över kravet 75 MHz. En första version höll en raderingsflagga per post (512 bitar) och kostade 16 992 LUT4.

**RSSI** (`rssi_adc.v`, sedan 2026-10-13): Tang Nano 20K saknar ADC, så Puck rev A-kortet har en ADS1115 på dekoder A:s buss (adress 48h, AIN0 mottagare A, AIN1 mottagare B; ägarens beslut 7 i navets `docs/BESLUT_2026-10-12.md`). Båda kanalerna läses en gång per fältperiod (16,7 ms): konfiguration C3C3h/D3C3h (±4,096 V, enkelomvandling, 475 SPS), 2,6 ms väntan, sedan omvandlingsregistret i två byte. Tre mastrar delar SCL och SDA_A: RSSI-läsaren höjer sin hold bara mellan OLED:ens byte och går först, OLED:n väntar på den och på `tvp_ctrl`, `tvp_ctrl` väntar på båda. Utan ADC svarar ingen på 48h: ingen avläsning och ingen varning.

Inga två RX5808 har samma RSSI-omfång, så värdet är oanvändbart okalibrerat. RSSI-sidan (▼ två gånger i flygvyn):
```
 RSSI    F4  5800
A 12000  75
B  4567   3  LOW WEAK
^ CAL OFF   A OK B OK
```
Rå ADC-kod (`-----` utan avläsning), kalibrerat värde 0–100 (`---` okalibrerat; teckensnittet saknar %-tecken), `LOW` när värdet legat under 20 % i tre avläsningar i följd, `WEAK` när mottagaren dessutom varnar: den andra är kalibrerad, har en avläsning, är inte låg och ligger minst 10 procentenheter högre (`MARGIN_PCT`; utan marginalen avgjorde en eller två punkter nära golvet varje par, granskning 2, Core #21). Då föredrar mixern den andra mottagaren (se M4). Kalibrering: ▲ på RSSI-sidan slår på; flytta sändaren nära och långt bort eller stäng av den, ▲ stänger av. Varje mottagare räknas som kalibrerad om dess spann är minst 400 koder (50 mV). Att lämna sidan avslutar en kalibrering. Kalibreringen sparas med de andra inställningarna i kortets flash (se "Sparade inställningar"). Trösklarna (20 %, 3 avläsningar, 400 koder) är parametrar i `rssi_adc.v` och sätts på bänken. Simulerat mot `model/rssi_ref.py` med en ADS1115-modell skriven ur TI SBAS444E (`sim/test_rssi_adc.py`: 28 avläsningsrundor med kalibrering, varning, båda låga, ingen ADC, exakt 20 %, för litet spann, laddade gränser, negativ och för hög spänning; ingen klocka med två aktiva mastrar). Negativa kontroller: avläsning före omvandlingens slut, varning utan hänsyn till den andra mottagaren, ingen väntan på de andra mastrarna, N = 1. Inget av detta är prövat mot en riktig ADS1115 eller mottagare.

Byggt ur `9023ab1`, seed 2, standardval (siffror efter routning, inga `ERROR`): M6 14 233 LUT4 (12 827 före RSSI), 25 BSRAM; `clocks.clk_27` 104,52 MHz, pixelklocka 139,43 MHz, `sd_clk` 105,39 MHz, A 298,42 MHz, B 211,33 MHz. Alla klockor över kravet 75 MHz.

## Bildvägen efter mixern: `BUF` och `LOW`

Två lägen, valbara i menyn medan det kör (`LOW=1 gateware/build.sh m4_dual_mix` bygger M4 i `LOW`, fil `m4_dual_mix_low.fs`; rådet 2026-10-21 vill ha första bilden där, eftersom SDRAM-läsningens fönster ännu följer bygget).

**`BUF`** (`rtl/fb_sdram.v`): fälten skrivs till fyra buffertar i SDRAM, och utgången går i fast 720p60.
- Vilken buffert en bild visar bestäms i SDRAM-domänen, där skrivaren finns, vid bildens första radbegäran. Skrivaren får aldrig bufferten som visas, dess reserv eller den nyss publicerade. (Förut skickade visningen sitt val över klockdomänsgränsen, och en källa snabbare än utgången kunde få bufferten som visades.)
- En bild visar fältet som håller på att skrivas om skrivaren ligger minst 4 rader före (44 för fält över 270 rader, som en 60 Hz-utgång läser fortare än de kommer). Annars visas senaste hela fält. `RT_EN = 0` ger bara hela fält.
- En bit per rad och buffert säger att raden är lagrad i sin helhet. En rad som saknas ersätts av raden ovanför (högst två i följd) och därefter av samma rad i fältet före. Finns ingen rad ovanför i bilden och ingen lagrad rad i fältet före (en saknad första rad i det första fältet), skrivs en svart rad i radbufferten utan att SDRAM läses (granskningen 2026-10-06, F3; `sim/test_fb.py::test_missing_first_line_is_black`). Det riktade BUF-testet verifierar denna ersättning; det täcker inte alla bytesfaser från LOW (se OVN-F1 nedan).
- Bilden skalas efter det mindre av de två senaste fältens radantal när de skiljer högst 2 rader (243/244, 287/288). Ett avklippt fält ändrar inte skalan.

**`LOW`**: utan bildbuffert. Mixerns rader skrivs direkt till en ringbuffert på 16 rader i FPGA:ns block-RAM, och 720p-utgången låses till ingångens fält (`genlock_timing.v`). Varje utbild startar när rad 1 i ett nytt fält har kommit, och raderna läses medan de kommer in. Fältet ringskrivaren gick med i (vid lägesbytet eller starten) startar ingen bild. En bild har video bara när den startades av en trigger från det här `LOW`-passet (`genlock_timing.v` säger om bilden startades av en trigger eller frigick); bilder som frigår, väntar ut triggern eller ligger närmast ett lägesbyte är grå. Det var Core #17: förut visades video så fort någon trigger kommit, även i bilder som läste ringplatser skrivaren inte nått (`sim/test_fb.py::test_low_after_switch_shows_whole_fields`).

| | `BUF` | `LOW` |
|---|---|---|
| Översta radens ålder när den visas, NTSC | 0,3–17 ms. Räknat ur radtiderna; `sim/test_fb.py` visar vinsten på ett fält i en nedskalad bild. Med `RT_EN = 0`: 17–33 ms | ca 0,1 ms överst i bilden, ca 0,8 ms nederst |
| Utgång vid NTSC | 720p60,00, ett fält visas två gånger var 17:e sekund | 720p 59,94 Hz (bilder om 750/751 rader) |
| Utgång vid PAL | 720p60 (var 5:e fält upprepas, ryckigt) | 720p50 (CEA-861-radlängd 1980) |
| Ingen signal | grå ruta | grå ruta, utgången frigår |
| Rad som saknas | raden ovanför, därefter förra fältets rad | det som fanns i ringens plats 16 rader tidigare |
| Falsk fältstart, brus på ingången | påverkar inte utgångens timing | en tidig trigger ignoreras; `JUMP_AFTER` tidiga i följd ger ett klipp med full vsync. `HOLD` spärrar nya klipp. Bara klippet och den direkt följande återhämtningsbilden får vara kortare än `V_TOTAL−1`; båda kör en full synkpuls |

Tiderna räknas från att raden är klar i FPGA:n. Dekoderns egen fördröjning (dess kamfilter arbetar över flera rader) och skärmens kommer till.

**Den varierande raden (`WAIT_BEFORE_VSYNC`, standard 0).** I `LOW` är bilderna 750 eller 751 rader vid NTSC, och väntan på triggern ligger på sista raden i bakre släckningen. Avståndet från vsync till första bildraden ändras därför mellan bilderna. Med `WAIT_BEFORE_VSYNC = 1` (`genlock_timing.v`, genom `fb_backend.v`) ligger väntan i stället på sista raden i främre släckningen. Den naturliga bilden hoppar då över första front-porch-raden i stället för första back-porch-raden, sista front-porch-raden upprepas tills triggern kommer, och därefter går hela synken och hela back porch. Avståndet från vsync till bild blir `V_SYNC + V_BP` rader i varje bild, och ett klipp behöver ingen återhämtningsbild. Placeringen kräver `V_FP ≥ 2`; 720p har 5.

Standard är 0. Med 1 kommer första bildraden `V_SYNC + V_BP` rader efter triggern i stället för på nästa rad, 25 rader eller 0,56 ms vid 720p. Varje rad visas då 0,56 ms senare än i tabellen ovan: ca 0,7 ms överst och ca 1,4 ms nederst i bilden. Ringens 16 rader rymmer ungefär 1,0 ms vid NTSC, så nedre delen av bilden skulle läsa platser som redan skrivits över. Att prova placeringen på en skärm kräver alltså en större ring först; det är inte gjort. Simulerat på liten geometri (48 rader, `V_FP` 2): de fyra låglatenstesterna i `sim/test_fb.py` går med båda placeringarna, och `::test_low_latency_frames_are_equally_long` mäter avståndet vsync till bild i de låsta bilderna: alltid 10 rader med 1, och 10, 10, 11, 12, 11, … med 0. Formellt bevisat för båda ("Formella bevis" nedan).

Standardläget är samma logik som före parametern: en ekvivalenskontroll i yosys (`equiv_make`, `equiv_induct`) visar `genlock_timing.v` med standardvärdena lika med versionen i `9164d12`, och samma kontroll med `WAIT_BEFORE_VSYNC = 1` skiljer sig. Byggt ur `f78fe82` med standardval (siffror efter routning, alla klockor över 75 MHz, inga `ERROR`):

| Topp | LUT4 | BSRAM | Pixelklocka (MHz) | `sd_clk` (MHz) |
|---|---:|---:|---:|---:|
| `m4_dual_mix` seed 0 | 8 283 | 25 | 120,95 | 110,10 |
| `m6_puck_proto` seed 2 | 12 827 | 25 | 121,30 | 104,08 |

Mot bygget ur `4ad5a68` är det 17 respektive 91 LUT4 fler. Logiken är densamma, så skillnaden kommer från syntesens mappning när källan ändras.

**Interpolation i höjdled (`VINTERP`, standard av).** Med `VINTERP=1 gateware/build.sh <topp>` visar varje utrad i `BUF` en blandning av de två källrader som omger dess läge, i stället för närmaste rad: vikten i åttondelar avrundas ur samma räknare som väljer raden, och blandningen är `(a·(8−w) + b·w)/8` per sampel (`rtl/vblend.v`). Andra raden läses ur en kopia av radbuffertens fyra platser, och förhämtningen ligger en källrad längre fram; det räcker med en begäran per utrad så länge bilden skalas upp minst två gånger (288 till 720 är 2,5). `LOW` behåller närmaste rad, eftersom nästa källrad inte behöver ha kommit. Vid 240 till 720 blir vikterna 7, 2, 5 i det övre fältet och 1, 3, 6 i det undre (utgångsunderlaget i navet, avsnitt 4). Simulerat: `sim/test_fb.py::test_vinterp_blends_two_source_lines` (andra raden, vikt, båda orden och den blandade pixeln mot `model/fb_ref.py`), `sim/test_vblend.py` (blandningen mot modellen); negativa kontroller med vikten låst till 0, utan förhämtning av andra raden och med omkastade vikter. Formellt bevisat sedan 2026-10-17 (`formal/run.sh`, `fb_linebuf_slots_vinterp`): båda läsportarna läser den rad de visar, begärd innan utraden började, i bilder med högst `V_ACTIVE / 2` källrader. Över det får utrad 0 i det övre fältet vikt från 450 källrader i 720p och läser då rad 1 innan den är begärd ([formal/README.md](formal/README.md), punkt 7). Att andra radens plats är skriven innan den läses kontrolleras i simuleringen (`sim/margin_checks.vh`, post `B`). Om bilden blir bättre på en riktig skärm är inte provat; standard är av tills kortet säger annat.

Kostnad, byggt ur `fc267a8` (standardval i övrigt, siffror efter routning, krav 75 MHz för alla klockor, HDMI-paren som M0):

| Topp | `VINTERP` | LUT4 | DFF | BSRAM | Pixelklocka (MHz) | Övriga klockor (MHz) |
|---|---:|---:|---:|---:|---:|---|
| `m4_dual_mix` seed 0 | 0 | 8 354 | 4 523 | 25 | 112,38 | `sd_clk` 128,40; `clocks.clk_27` 213,22; A 250,38; B 229,99 |
| `m4_dual_mix` seed 0 | 1 | 8 827 | 4 545 | 29 | 121,55 | `sd_clk` 95,79; `clocks.clk_27` 223,76; A 237,59; B 282,09 |
| `m6_puck_proto` seed 2 | 0 | 12 788 | 6 209 | 25 | 123,06 | `sd_clk` 107,79; `clocks.clk_27` 122,96; A 350,75; B 178,73 |
| `m6_puck_proto` seed 2 | 1 | 13 392 | 6 231 | 29 | 126,04 | `sd_clk` 145,24; `clocks.clk_27` 106,19; A 252,46; B 250,13 |

`VINTERP=1` kostar alltså cirka 470–600 LUT4 och 4 BSRAM; Fmax-skillnaderna ligger inom placeringens spridning mellan byggen.

**Fälten ligger en halv rad isär.** Fälten i en sammanflätad bild kommer omväxlande en radtid längre och en radtid kortare isär (263/262 rader i NTSC). `field_phase.v` avgör på ankomsttiden vilket fält som är det nedre, inte på F-biten: en TVP5150AM1 håller F på 1 när den tar signalen för icke sammanflätad. `fb_display.v` ritar det nedre fältet en halv källrad lägre (`BOB = 0` stänger av det). I `LOW` fördröjs dessutom bildstarten för det tidiga fältet med halva skillnaden, så att utbilderna blir lika långa; utan det växlar de med tre rader (`LL_EQ = 0`).

**Varför `LOW` fungerar:** utgången skannar varje källrad långsammare (3 × 22,2 µs) än ingången levererar den (63,6 µs). Läsaren kan alltså aldrig gå om skrivaren, och skrivaren ligger högst cirka 13 rader före (därav 16 platser). Upplösningen är densamma i båda lägena, så läget går att byta medan det kör. Vid byte mellan PAL och NTSC i `LOW` ändras bildfrekvensen, och skärmen synkar om (1–2 s).

**Risk att prova på hårdvara:** en del skärmar gillar inte att antalet rader per bild växlar (750/751), och vad en skärm gör med den korta bilden vid omlåsning är inte känt. CVBS2HDMI kör samma knep (524/525 rader) utan problem på vanliga skärmar. XR-glasögon tar enligt navets anteckningar inte emot 720p alls; `LOW` är för skärmar och goggles som gör det. Testat i simulering: `sim/test_m2.py::m2_low_latency` (låsning, bildperiod = fältperiod, pixlar mot modell) och `sim/test_fb.py` (lika långa bilder, fält utan rad 1, falsk fältstart, källa som flyttar sig).

**Lägesbyte under drift är simulerat** (`sim/test_fb.py::test_mode_switch_buf_low_buf`: fem fält `BUF`, sex `LOW`, sju `BUF`). Efter första bilden efter varje byte finns inga X/Z på RGB, DE, HSYNC eller VSYNC, och SDRAM-modellen rapporterar inga protokollfel. Varje komplett bild har exakt en full vsync-puls. Bildlängden är `V_TOTAL−1..V_TOTAL+8` rader under stabilisering och därefter `V_TOTAL−1..V_TOTAL+1`; enbart ett avsiktligt klipp och dess direkt följande återhämtningsbild får underskrida `V_TOTAL−1`. Återhämtningsbilden måste nå minst `V_ACTIVE+V_FP+V_SYNC+1` rader. Det finns inget generellt undantag vid lägesbyte för saknad eller extra synkpuls. `BUF` → `LOW`: fältet som skrivaren gick med i startar ingen bild; därefter visas hela fält när en trigger från `LOW` kommer. I detta tests bytesfas, `LOW` → `BUF`: publicerade fält glöms medan `LOW` är aktivt och fältet skrivaren gick med i släpps utan publicering, så första hela publicerade fältet visas. Testet rättade att `fb_display.v` behöll ett gammalt `have_pub` och att `fb_sdram.v` publicerade det halva fältet vid start/byte. `test_mode_switch_checks_catch_faults` behåller negativa kontroller för fel ordtagg, X på RGB och extra vsync. Den äldre 2026-10-07 kampanjen såg bildblandning efter `BUF` → `LOW` i 14 av 18 frön; detta är pre-fix-historik kring Core #17, inte en aktuell xfail. Fable rapporterade #17/#18 stängda på `e113cf6`; C1:s frysta svit har inga xfails.

## Apicula-fällor (från otanl/CVBS2HDMI, kontrollerade 2026-10-04)

- **Signerade jämförelser** har felkompilerats av Apicula (seed-beroende). `tmds_encoder.v` och `ycbcr2rgb.v` är omskrivna utan signerad aritmetik och bitexakt kontrollerade mot de gamla versionerna (alla 16,7 miljoner YCbCr-värden, plus en lång slumpsekvens genom TMDS-kodaren). Ingen annan modul använder `signed`.
- **Insignaler i samma I/O-bank som HDMI** (bank 5: stift 26–31, där dekoder A:s buss ligger) packades i en nyare Apicula som LVDS-mottagare. **Vår Apicula 0.32 gör inte det.** `tools/test_lvds_bank_inputs.py` bygger två små designer, med och utan LVDS-utgång i banken, och kräver att insignalernas IOB-fuses är identiska. En riktig LVDS-mottagare som negativ kontroll visar att testet ser skillnaden. Kör testet efter varje Apicula-uppgradering. Om det fallerar: packa via en omslagare som CVBS2HDMI:s `scripts/gowin_pack_io.py` (MIT).
- Inga `DRIVE=`/`BANK_VCCIO=` på LVDS25-stift (gäller redan våra cst-filer).
- **Vanliga utgångar i HDMI-parens banker** (stift 25–42) ändrar hur Apicula packar klockparet. `tools/test_tmds_bank_outputs.py` vaktar cst-filerna, och `tools/tmds_fuses.py` jämför färdiga bitströmmar mot M0. Kör testet efter varje Apicula-uppgradering.

## M3 — uppstartsprob

Byggvalet `TVP_ADDR=5D` (sedan 2026-10-21) låter M3, M4 och M6 tala med dekodrar som har I2C-adressen 5D i stället för 5C (YOUT7:s nivå vid start; den röda modulen CP803A svarar på 5D, rev A drar 5C). Utan valet provas 5C först. Sedan 2026-10-21 provar `tvp_ctrl.v` den andra adressen själv när den första inte svarar (`SEARCH`, med egen SDA per dekoder som i M3, M4 och M6), låser den som svarar per dekoder till nästa reset, och M3 visar den i fältet `i2c` (`5C`/`5D`). Simulerat i `sim/test_tvp_ctrl.py` (`test_address_search_*`, `test_address_kept_after_reinit`, `test_late_decoder_found_at_5d`, `test_shared_bus_has_no_search`; negativ kontroll: sökningen av ger `dev_err` mot slaven på 5D) och `sim/test_probe.py` (dekoder B på 5D). På en delad SDA (två dekodrar på 5C och 5D) söker styrenheten inte: den andra adressen är den andra dekoderns.

`top/m3_probe.v`, samma stift som M4/M6. Visar en gång i sekunden, per dekoder: SCLK-frekvens, vilka databitar som växlar, radlängder, rader och fält per sekund, synkfel, I2C-svar, statusregister och hur många gånger dekodern har hittats återställd och startats om. Lysdioder: LED0 hjärtslag 1 Hz, LED1 SCLK från A, LED2 SCLK från B. Pull-test med `PULL=UP` eller `PULL=DOWN gateware/build.sh m3_probe` (bit 0–6; bit 7 är dekoderns adresstrapp och får ingen pull, `tools/test_build_pull.py`). Allt om koppling och tolkning finns i [BRINGUP.md](BRINGUP.md).

## Formella bevis

`formal/run.sh` tar flera minuter och ingår i testsviten via `tools/test_formal.py`; C1-kandidatens frysta körning tog 572,163 s och gav 7 `PROVEN`-bevis samt 14 `CONTROL OK` i negativa kontroller. Sedan `WAIT_BEFORE_VSYNC` (2026-10-13) var det 8 `PROVEN` och 16 `CONTROL OK`, sedan `RD_REG` i `async_fifo.v` (2026-10-14) 10 och 17, och sedan radbuffertbeviset för `VINTERP = 1` (2026-10-17) är det 11 och 19. Bevisen använder k-induktion i yosys utan extern lösare:

| Modul | Bevisat | Negativ kontroll |
|---|---|---|
| `async_fifo.v` (djup 4 och 8, `RD_REG` 0 och 1) | med två fria klockor och fria in-signaler: ingen överflödning eller underflödning, varje sidas bild av den andra pekaren är konservativ, Gray-pekarna stämmer och rör sig ett steg i taget, och ett ord kommer ut oförändrat; med `RD_REG = 1` håller läsregistret ordet vid läspekaren så fort första synksteget sett det skrivet | en FIFO som aldrig är full flödar över; en som aldrig är tom flödar under; ett läsregister som laddas från nuvarande pekare i stället för nästa visar det poppade ordet igen |
| `genlock_timing.v` | med fria `lock`, `trig`, `h_alt` och `rst` på liten geometri: räknarna håller sig inom gränserna, varje bild slutar inom `V_TOTAL+MAX_WAIT`, exakt en vsyncpuls registreras per bild med exakt `V_SYNC` synkrader. Normala bilder är minst `V_TOTAL−1`; bara avsiktligt klipp och direkt följande återhämtningsbild får vara kortare, och återhämtningen är minst `V_SYNC_END+1` rader. `HOLD` gäller mellan klipp. Med `WAIT_BEFORE_VSYNC = 1` (två front-porch-rader) samma egenskaper, och dessutom slutar varje låst bild med hela sin back porch efter synken och ingen återhämtningsbild förekommer | borttagen väntegräns, två överhoppade porch-rader i en normalbild, borttagen `HOLD`, tappad sync i klippet och återhämtningsflagga som fastnar; med `WAIT_BEFORE_VSYNC = 1`: den naturliga bilden hoppar över en back-porch-rad, väntan slutar på andra synkraden |
| `cdc_sync.v` `toggle_rx` (radbegäran, publicering, lågfördröjningstrigger i `fb_backend.v`) | två fria klockor, högst 3 flanker av den ena mellan två av den andra (27–108 MHz mot 74,25 MHz), ett sampel mitt i en ändring får bli vilket värde som helst: med vändning högst var 16:e sändarklocka och data som hålls 16 klockor tappas eller dubbleras ingen händelse, varje händelse tas emot inom 4 mottagarflanker, och mottagen data är den skickade | flanken tagen direkt från andra domänen ger fel data; vändning var 8:e klocka tappar en händelse; data som ändras efter 2 klockor kommer fram fel |
| `cdc_sync.v` `toggle_tx` (lågfördröjningstriggerns sändarsida) | en klocka, fria begäranden: vändningar minst 16 klockor isär, data hålls från vändning till vändning, varje begäran skickas inom 16 klockor med den senaste datan; det är sändarvillkoren i raden ovan | en sändare som vänder direkt på varje begäran bryter avståndet |
| `cdc_sync.v` `sync2` (`ll_mode`) | lägesbiten ändras bara på den egna klockans flank och är rätt från tredje flanken efter ett byte; domänerna är bara oense under de tre flankerna | utan `sync2` ändras biten mellan flankerna; efter två flanker är den inte säkert inställd |
| `fb_display.v` (radbuffertens platser) | med den riktiga tidsbasen: en rad som begärs under en aktiv utrad hamnar på en plats som inte läses under resten av raden. Med `VINTERP = 1` (12 aktiva rader, bilder med högst `V_ACTIVE/2` källrader): båda läsportarna läser den rad de visar, och den begärdes innan utraden började; port B när vikten inte är 0 | begäran till platsen som läses faller; med `VINTERP = 1` faller andra raden begärd en utrad för sent och port B som läser platsen efter sin egen |

Periodisk källförflyttning och fasgränsen provas separat i `sim/test_genlock.py`, inte formellt: senast vid den andra följande nominella triggern ligger bildstart högst en H-linje efter.

Egenskaperna står i modulerna inom `ifdef FORMAL` eller i harneskarna i `formal/`. Vad som inte är bevisat om klockdomänsövergångarna, och varför, står i [formal/README.md](formal/README.md): bland annat att två synksteg räcker mot metastabilitet, att SDRAM-sidan hinner skriva en rad, lågfördröjningsringen. Att `frame_low`/`ll_low` hinner fram före rad 0 och att en radbuffertplats är skriven innan den läses (med `VINTERP` även andra läsportens, sedan 2026-10-17) kontrolleras sedan 2026-10-12 i varje körning av `sim/test_fb.py` och `sim/test_fuzz_chain.py` (`sim/margin_checks.vh`, minst en pixelklockas marginal, negativa kontroller med sen skrivare och sena signaler); simulerat, inte bevisat. Hela sviten därefter: 695 test gröna. Radantalet som följer lågfördröjningstriggern kunde ändras på vägen till pixeldomänen när ett fält var mycket kort; det hålls nu av `toggle_tx` (`sim/test_ll_payload.py`).

## Bygget av M6

Till 2026-10-07 gick 27 MHz-domänens kritiska väg från menyns band och kanal genom kanaltabellen i `puck_ui.v` till RX5808:s skiftregister, och siffrorna för MHz räknades med division ur samma tabellutgång. Domänen nådde 98,5 MHz efter routning i bygget av 62a69be, 90 MHz i a6640b0 och 65 MHz i f13581c; skillnaden var placering. Nu är tabelluppslaget ett register (`chan`), och MHz-siffrorna ligger som en egen tabell per kanal (konstanta divisioner som försvinner i syntesen) i samma registersteg. SPI-skrivningen vid kanalbyte startar två klockor senare än förut.

Historisk seedtabell från bygget ur `a5b934f` (`SEED=n gateware/build.sh m6_puck_proto`), efter routning:

| Seed | 27 MHz-domän | SDRAM | Pixel | Dekoder A / B | Kritisk väg i 27 MHz-domänen |
|---|---|---|---|---|---|
| 0 | 109 MHz | 99 MHz | 127 MHz | 147 / 125 MHz | mätarsidans text till OLED-tecknet |
| 1 | 116 MHz | 94 MHz | 117 MHz | 108 / 116 MHz | mätarsidans text till OSD-tecknet |
| 2 | 127 MHz | 99 MHz | 123 MHz | 135 / 122 MHz | mätarsidans text till OSD-tecknet |
| 3 | 115 MHz | 106 MHz | 128 MHz | 156 / 117 MHz | mätarsidans text till OSD-tecknet |

Alla fyra seeds routade i den historiska körningen med 12 600 LUT och 25 BSRAM. Vid den körningen krävdes 54 MHz för 27 MHz-domänen och 75 MHz för övriga. Bygget ur `330cc9a` (med mixerns regel för dubbeldåliga rader och låsflaggan i loggen) gav seed 2 med 123 MHz i 27 MHz-domänen. Dessa värden är seedhistorik, inte C1-mätvärden.

- **Seed.** Den historiska tabellen ovan gäller `a5b934f`; den ska inte användas för att förutsäga varje seed på senare källor. På C1-källan `3aed0b7` misslyckades seed 2 under global routning med `Can't route the clocks.clk_27 net`, medan seed 3 routade vid 75 MHz. Orsaken står nedan och är åtgärdad 2026-10-12. `boards/m6_puck_proto.seed` är fortfarande 2. `build.sh` tar `SEED=<n>` och rapporterar klockroutningsfel.

### Klockroutningen, 2026-10-12

**Orsak.** Nätet som föll är kortets 27 MHz-klocka (stift 4), som i nextpnr heter `clocks.clk_27` och matar båda PLL:erna och 27 MHz-domänen. Det får alltid en BUFG. Till 2026-10-12 hade även dekodrarnas SCLK (`tvpa_sclk`, `tvpb_sclk`) `CLOCK_LOC ... BUFG` i M3, M4 och M6, alltså tre BUFG-celler. nextpnr 0.11.1 routar buffrade nät före alla andra klockor, dekoderklockorna först, och bara över det dedikerade globala nätet. Det finns ingen reservväg: når ett buffrat nät ingen mottagare stoppar bygget. Vilken BUFG-plats varje cell får väljer placeraren, och det beror på seed. På C1-källan med seed 2 fick kortklockan X0Y27/BUFG0 och dekoder A X28Y0/BUFG1; från X0Y27/CLK0 nådde ingen mottagare (PLL-ingångarna, 27 MHz-logiken) via globala ledningar som dekoderklockorna inte redan tagit. Byggen som routade hade andra kombinationer. Att det är dekoderklockornas ledningar är härlett ur nextpnr:s ordning och ur försöket nedan, inte utläst ur routningen.

**Åtgärd.** SCLK-stiften är dedikerade klockingångar (stift 77 GCLKT_1, stift 80 GCLKT_0) och når det globala nätet utan buffert. Utan BUFG-flaggan routar nextpnr dem som klockkällor, med segmentroutning som reserv i stället för fel. Flaggan är borttagen i `boards/m3_probe.cst`, `m4_dual_mix.cst` och `m6_puck_proto.cst`. Negativ kontroll: C1-nätlistan med seed 2 faller i den globala routningen med flaggan kvar och routar alla klocknät utan den; dekoderklockorna går då "using global resources only". Att i stället ta bort kortklockans flagga hjälper inte, eftersom nextpnr lägger in bufferten för det nätet ändå.

**Byggt** ur Core `94a2b32` (alla klockor krav 75 MHz, siffror efter routning, inga `ERROR` i loggarna). Kortklockans BUFG hamnar nu på X0Y27/BUFG0 med seed 0, 1 och 3, platsen som föll förut, och routar:

| Topp | Seed | LUT4 | BSRAM | Maxfrekvens efter routning (MHz) |
|---|---:|---:|---:|---|
| `m6_puck_proto` | 0 | 12 804 | 25 | `mix.b_clk` 129,05; `mix.a_clk` 151,79; `clocks.clk_27` 116,33; `sd_clk` 110,60; `clk_pixel` 124,86 |
| `m6_puck_proto` | 1 | 12 804 | 25 | `mix.b_clk` 132,12; `mix.a_clk` 149,75; `clocks.clk_27` 133,92; `sd_clk` 96,14; `clk_pixel` 119,62 |
| `m6_puck_proto` | 2 | 12 804 | 25 | `mix.b_clk` 122,87; `mix.a_clk` 144,26; `clocks.clk_27` 125,68; `sd_clk` 110,00; `clk_pixel` 131,49 |
| `m6_puck_proto` | 3 | 12 804 | 25 | `mix.b_clk` 118,06; `mix.a_clk` 124,13; `clocks.clk_27` 133,87; `sd_clk` 100,54; `clk_pixel` 132,28 |
| `m4_dual_mix` | 0 | 8 302 | 25 | `mix.b_clk` 157,58; `mix.a_clk` 142,21; `clocks.clk_27` 232,88; `sd_clk` 89,69; `clk_pixel` 106,77 |
| `m3_probe` | 0 | 2 561 | 0 | `pb.clk` 179,63; `pa.clk` 147,36; `conv.clk` 196,66 |
| `m0_testpattern` | 0 | 794 | 0 | `clocks.clk_27` 359,84; `clk_pixel` 149,37 (oförändrad, referens för HDMI-paren) |

`tools/tmds_fuses.py`: alla fyra HDMI-par i M4 (seed 0) och M6 (seed 3) som i M0. På `main` före ändringen (`5314ed1`) routade M6 också med seed 0–3; felet syntes alltså inte på den källan, men risken fanns kvar.

Iakttagelse: med seed 1 och 3 (och seed 3 före ändringen) når `sd_clk_shift`, SDRAM-klockan ut till stiftet, inte stiftet över dedikerad routning och går via vanliga ledningar. Det ger inget fel, men fördröjningen till SDRAM-klockstiftet beror då på placeringen; det är vad minnestestet `m2a_memtest` mäter på kortet.

### M6 med HDMI och VINTERP, 2026-10-14

**Orsak.** `HDMI=1 VINTERP=1 gateware/build.sh m6_puck_proto` stannade i placeringen: nextpnr 0.11.1 gav upp med "Unable to find legal placement for all cells, design is probably at utilisation limit" (Codex på `bf05ac0` efter 57 min, Opus på `072dbde` efter 2 382 s). Placeraren ger det felet när den slutliga legaliseringen har flyttat celler fler än åtta gånger antalet celler. Ingen celltyp är över sin egen kapacitet i nextpnr:s tabell (LUT4 16 220 av 20 736, ALU 4 604 av 15 552, DFF 7 700 av 15 552, RAM16SDP4 282 av 648, BSRAM 29 av 46). Det som tar slut är LUT-platserna, som flera celltyper delar: en ALU tar en LUT-plats, en RAM16SDP4 tar en hel CFU (8 LUT-platser och dess 6 vippor), och en vippa bredvid en LUT måste ta sin data från just den LUT:en. Varje vippa som matas av något annat (en vippa, ett RAM, en MUX) tar därför en egen plats, där nextpnr efter placeringen lägger en genomgångs-LUT. Räknat ur syntesens nätlista för `072dbde`:

| M6 | LUT ur syntesen | ALU med kedjeändar | RAM16SDP4 × 8 | Vippor utan egen LUT | Summa av 20 736 |
|---|---:|---:|---:|---:|---:|
| standard | 9 057 | 4 192 | 2 256 | 2 725 | 18 230 (87,9 %) |
| `VINTERP=1` | 9 226 | 4 554 | 2 256 | 2 720 | 18 756 (90,5 %) |
| `HDMI=1` | 9 200 | 4 238 | 2 256 | 3 013 | 18 707 (90,2 %) |
| båda | 9 360 | 4 604 | 2 256 | 3 008 | 19 228 (92,7 %) |

`HDMI=1` lägger till 288 vippor utan egen LUT (fördröjningslinjen på 10 klockor i `tmds_link.v`), `VINTERP=1` 362 ALU. 224 av de 282 RAM16SDP4 var mixerns två ingångs-FIFO:er (128 × 53 bitar vardera med asynkron läsning, alltså bara LUT-RAM möjligt): 1 792 LUT-platser. nextpnr:s DFF-tal räknar 6 vippor per RAM16SDP4, därav 7 700 mot syntesens 6 083.

**Åtgärd.** `async_fifo.v` har `RD_REG`: med 1 laddas ordet vid läspekarens nästa värde i ett register vid varje läsklocka, så att minnet kan ligga i block-RAM. `rd_data` är då detsamma som förut vid varje klocka medan FIFO:n inte är tom (formellt bevisat för båda lägena; `sim/test_async_fifo.py`). `mixer2.v` använder det för `fifo_a` och `fifo_b`: två BSRAM vardera i stället för 112 RAM16SDP4 vardera. Alla M4- och M6-byggen får därmed 4 BSRAM fler och 224 RAM16SDP4 färre. Andra vägar som planen nämnde behövdes inte: mätarsidans text är kvar i HDMI-bygget, och I/O-registren i I/O-cellerna är kvar (felet gällde inte IOLOGIC). Efter placeringen upptar M6 med båda valen 17 137 av 20 736 LUT-platser (82,6 %: 8 653 LUT ur syntesen, 3 418 genomgångs-LUT, 4 602 ALU, 58 RAM16SDP4) och M6 med standardval 16 245 (78,3 %).

**Byggt** ur `2c64672` (siffror efter routning, krav 75 MHz för alla klockor, inga `ERROR`, HDMI-paren i alla fyra som i M0):

| Topp | Val | Seed | LUT4 | DFF | BSRAM | Lägsta klocka (MHz) | Tid |
|---|---|---:|---:|---:|---:|---|---:|
| `m6_puck_proto` | standard | 2 | 13 113 | 6 029 | 29 | `clocks.clk_27` 112,07 | 676 s |
| `m6_puck_proto` | `HDMI=1 VINTERP=1` | 2 | 13 719 | 6 356 | 33 | `sd_clk` 99,00 | 730 s |
| `m4_dual_mix` | standard | 0 | 5 831 | 3 179 | 29 | `sd_clk` 129,17 | 237 s |
| `m4_dual_mix` | `HDMI=1 VINTERP=1` | 0 | 6 427 | 3 505 | 33 | `clk_pixel` 116,33 | 243 s |
| `m0_testpattern` | standard | 0 | 789 | | 0 | `clk_pixel` 152,35 | 36 s |

Mot `bf05ac0` är det 2 392 LUT4 färre i M6 och 2 414 färre i M4; M6:s 27 MHz-domän ligger på 112,07 MHz mot 132,28 (placeringen, inte logiken i den domänen).

**Byggt igen** ur `c852cb9` (2026-10-18, efter uppgift 33–35 och omfånget `FULL`/`LTD` i `tmds_link.v`; samma byggindata som `52c2ffe`), i en ren klon: siffror efter routning, krav 75 MHz för alla klockor, inga `ERROR`, manifestet verifierat mot källorna (`tools/build_manifest.py verify --root`, `dirty` false), alla fyra HDMI-par med samma IOB-fuses som i M0 med DVI ur samma klon (`tools/tmds_fuses.py m0_testpattern m6_puck_proto_vinterp_hdmi`):

| Topp | Val | Seed | LUT4 | DFF | BSRAM | Klockor (MHz) | Tid |
|---|---|---:|---:|---:|---:|---|---:|
| `m6_puck_proto` | `HDMI=1 VINTERP=1` | 2 | 13 997 | 6 467 | 33 | `sd_clk` 115,41; `clk_pixel` 119,86; `clocks.clk_27` 116,60; `mix.a_clk` 242,72; `mix.b_clk` 195,66 | 604 s |

Mot `2c64672` är det 278 LUT4 fler (det som kommit in sedan dess, bland annat granskningens rättningar i `8a71a0a` och skalningen till 16–235); mot M6 med bara `HDMI=1` ur `52c2ffe` lägger `VINTERP=1` till 453 LUT4 och 4 BSRAM.

Vilka byggval som är byggda tillsammans:

| | standard | `VINTERP=1` | `HDMI=1` | båda |
|---|---|---|---|---|
| M4 | `52c2ffe` | `bf05ac0` (Codex) | `52c2ffe` | `2c64672`; före ändringen också `bf05ac0` (Codex) |
| M6 | `52c2ffe` | `bf05ac0` (Codex) | `52c2ffe` | `c852cb9`, `2c64672`; föll på `bf05ac0` och `072dbde` |

`VINTERP=1` ensamt är inte ombyggt efter FIFO-ändringen, som bara tar bort LUT-RAM.

## Störningskampanjen C3 avslutad, 2026-10-12

Alla 260 frön i C3:s kampanj är körda: 257 gröna med originalstimulus, tre (1345, 1434, 1444) gröna först med fyra rena fält efter originalet (`--recovery-fields 4`), inget oförklarat fel. De 60 som återstod gav ett RTL-fel i `fb_sdram.v` (raden skrivaren går in i mitt i räknades som lagrad), rättat i Core `0da655d`. Rundorna, siffrorna och vilka källor de kördes på står i [sim/FUZZ_2026-10-07.md](sim/FUZZ_2026-10-07.md). Hela sviten på grenen: 691 test gröna, ingen delad byggkatalog.

Byggt efter rättningen ur `0da655d` (IOREG enligt standard, siffror efter routning, inga `ERROR`, manifesten verifierade, HDMI-paren i M2, M2s, M4 och M6 som i M0):

| Topp | Seed | LUT4 | BSRAM | Maxfrekvens efter routning (MHz) |
|---|---:|---:|---:|---|
| `m2_moneagle_color` | 0 | 3 474 | 17 | `sd_clk` 125,79; `clk_pixel` 120,89; `clocks.clk_27` 439,37; `core.tvp_clk` 271,96 |
| `m2s_moneagle_color_sync` | 0 | 3 653 | 17 | `sd_clk` 111,66; `clk_pixel` 112,85; `clocks.clk_27` 453,31; `core.tvp_clk` 232,34 |
| `m4_dual_mix` | 0 | 8 330 | 25 | `mix.b_clk` 222,72; `mix.a_clk` 221,09; `clocks.clk_27` 230,04; `sd_clk` 107,70; `clk_pixel` 109,59 |
| `m6_puck_proto` | 2 | 12 812 | 25 | `mix.b_clk` 306,94; `mix.a_clk` 247,83; `clocks.clk_27` 132,38; `sd_clk` 108,18; `clk_pixel` 116,99 |
| `m0_testpattern` | 0 | 793 | 0 | `clocks.clk_27` 335,80; `clk_pixel` 145,99 (referens) |

## I/O-register i I/O-cellerna

**`IOREG=1` sedan uppgift 49 (2026-10-21): bara rena ingångsvippor.** Standard är fortfarande 0. `IOREG=1` ger nextpnr `--vopt ireg_in_iob --vopt ioreg_in_iob` (ingångsvippor vid in- respektive dubbelriktade stift; `ireg_in_iob` ensamt lämnar SDRAM:ens DQ utanför, som bygget ur `82f9c1d` visade: en enda vippa i cellerna), inte längre `oreg_in_iob`, och bygget faller om `tools/iob_regs.py --strict` hittar en vippa med CE, SET eller RESET i en cell (`tools/test_build_artifacts.py`). För det är vipporna vid stiften rena (bara CLK, D, Q): DQ-infångningen `dq_in` i `rtl/sdram_burst.v`, dekoderdata `a_in`/`b_in` i `rtl/mixer2.v` (var det redan) och `miso_q` i `rtl/flash_store.v`. Läsögonblicket vid stiften är detsamma som förut (`sim/test_sdram.py`, `sim/test_memtest.py` och `sim/test_flash_store.py` oförändrade). Syftet är beslut 2:s: läsfönstret och dekoderinfångningen blir desamma i varje topp, så att M2a-svepet gäller också M4 och M6. Om registren i cellerna beter sig på kortet avgör M2a-svepet med `m2a_memtest_ioreg1.fs` (inte kört).

Byggt ur `669b2ed`, krav 75 MHz, manifesten verifierade mot källorna (`dirty` false):

| Topp | Seed | `IOREG` | Vippor i I/O-celler (`iob_regs.py`) | LUT4 | Lägsta maxfrekvens efter routning |
|---|---:|:-:|---|---:|---|
| `m2a_memtest` | 0 | 1 | 33: 32 DQ, knappen; ingen med CE/SET/RESET | 2 351 | `sd_clk` 93,80 MHz |
| `m4_dual_mix` | 0 | 1 | 49: 32 DQ, 16 YOUT, SCL; ingen med CE/SET/RESET | 5 981 | `sd_clk` 122,88 MHz |
| `m6_puck_proto` | 2 | 1 | 52: 32 DQ, 16 YOUT, SCL, flashens MISO, två knappar; ingen med CE/SET/RESET | 14 182 | `sd_clk` 102,71 MHz |
| `m2a_memtest` | 0 | 0 | 0 | 2 351 | `sd_clk` 86,73 MHz |
| `m4_dual_mix` | 0 | 0 | 0 | 5 981 | `mix.a_clk` 127,29 MHz |
| `m6_puck_proto` | 2 | 0 | 0 | 14 182 | `sd_clk` 98,47 MHz |

Negativ kontroll: samma commit med `rtl/sdram_burst.v` från `f626a6f` (DQ-registret med klockenable) och `IOREG=1` vägras: 32 DQ-vippor med CE i cellerna. Före ändringen i `flash_store.v` hade M6 med `IOREG=1` en vippa med CE i cellerna (MISO). I `m4_dual_mix_ioreg1` routades SDRAM-klockan (`sd_clk_shift`) utan den dedikerade vägen (en varning från nextpnr, inget fel); i de andra fem inte. Byggena är inte provade på kortet.

**Av som standard sedan 2026-10-21, för alla toppar.** På kortet (Tang Nano 20K rev 3923, hemmabänken 2026-10-20 och bänken på jobbet 2026-10-21) kom M2a:s UART-rapport ut som 82-byterader i rätt takt men med förvrängda bitar, och en fast UART-rad byggd med `IOREG=1` (`m2u_uart64`, grenen `bench/uart-check`) förvrängdes likadant medan samma rad utan flaggan lästes 39 av 39 gånger. Med flaggan hade nextpnr lagt UART:ens `txd`-vippa (klockenable och synkron set) i I/O-cellen som `IOLOGICO` med `CE` och `SET`, och i M2a dessutom 48 SDRAM-register med `CE`, `SET` eller `RESET` (adress, kommandon, de 32 DQ-ingångarna). Slutsatsen: ett register i I/O-cellen med CE/SET/RESET beter sig inte som i simuleringen med Apicula 0.32 / nextpnr 0.11.1; vilken av signalerna som faller är inte utrett. Utan flaggan gav M2a `rs=5 err=00000000` varv efter varv vid fas 9, 10 och 11 (navets `docs/bench/`, uppgift 47). `IOREG=1` finns kvar som uttryckligt val för experiment (suffix `_ioreg1`, manifestet bokför `options.ioreg`), och `build.sh` skriver efter routningen hur många register som ligger i I/O-celler (`tools/iob_regs.py`; med `--strict` räknar verktyget upp dem med CE/SET/RESET och ger felkod). Beslut 2:s syfte, en SDRAM-timing som inte beror på placeringen, kräver att registren vid paden görs till rena vippor i RTL (fånga varje klocka, kvalificera i nästa steg); det är gjort i uppgift 49 (ovan).

Texten nedan beskriver läget 2026-10-12 till 2026-10-21, då flaggan var standard för M2, M2s, M2a, M4 och M6.

Från 2026-10-12 (ägarens beslut, navets `docs/BESLUT_2026-10-12.md` punkt 2) byggde `build.sh` M2, M2s, M2a, M4 och M6 med `--vopt ireg_in_iob --vopt oreg_in_iob --vopt ioreg_in_iob`: nextpnr lägger in- och utregistren i I/O-cellerna, så SDRAM-gränssnittets timing beror inte på var placeraren lägger dem, och minnestestet på kortet gäller också bildbyggena. M0, M1, M1s och M3 byggdes som förut. Manifestet bokför valet (`options.ioreg`). Ingen RTL är ändrad.

**Byggt, inte uppmätt.** Ur Core `dc307bc`, alla klockor krav 75 MHz, siffror efter routning, inga `ERROR` i loggarna, manifesten verifierade mot källorna:

| Topp | Seed | LUT4 | DFF | BSRAM | Register i I/O-cell (in + ut) | Maxfrekvens efter routning (MHz) |
|---|---:|---:|---:|---:|---|---|
| `m2_moneagle_color` | 0 | 3 466 | 1 965 | 17 | 40 + 16 | `sd_clk` 120,28; `clk_pixel` 107,02; `clocks.clk_27` 439,37; `core.tvp_clk` 221,04 |
| `m2s_moneagle_color_sync` | 0 | 3 677 | 2 057 | 17 | 42 + 16 | `sd_clk` 115,69; `clk_pixel` 115,57; `clocks.clk_27` 453,31; `core.tvp_clk` 204,58 |
| `m2a_memtest` | 0 | 2 393 | 886 | 0 | 33 + 17 | `sd_clk` 92,68 |
| `m4_dual_mix` | 0 | 8 302 | 4 512 | 25 | 49 + 20 | `mix.b_clk` 260,76; `mix.a_clk` 228,21; `clocks.clk_27` 211,64; `sd_clk` 104,18; `clk_pixel` 116,54 |
| `m6_puck_proto` | 2 | 12 804 | 6 198 | 25 | 51 + 21 | `mix.b_clk` 199,68; `mix.a_clk` 284,50; `clocks.clk_27` 124,84; `sd_clk` 118,98; `clk_pixel` 123,93 |
| `m0_testpattern` | 0 | 794 | 173 | 0 | 0 | `clocks.clk_27` 359,84; `clk_pixel` 149,37 (referens, utan flaggan) |

Registren i I/O-cellerna är räknade som `IOLOGICI`/`IOLOGICO` i `.pnr.json`, samma antal som i experimentet 2026-10-06. LUT4 är oförändrat mot byggena utan flaggan (M4 8 302, M6 12 804 i avsnittet ovan). `tools/tmds_fuses.py`: alla fyra HDMI-par i M2, M2s, M4 och M6 som i M0. Hela sviten: 664 test gröna på grenen, 689 på `main` ae993f8 efter sammanslagningen med körarens resume-kontroll (`tools/test_run_suite.py`), ingen delad byggkatalog.

Vad som inte hamnar i cellerna (utrett i experimentet på M2a): skrivdata och utgångsaktivering för de 32 DQ-stiften, DQM, `cs_n`, `cke` och SDRAM-klockan. Yosys slår ihop de 32 utgångsaktiveringsregistren till ett, och ett register som driver 32 stift kan inte ligga i en cell; varför `dq_out` inte läggs där är inte utrett. Läsningen, där fönstret är 11,9 ns, är den del som flyttas: alla 32 DQ-ingångsregister ligger i cellerna. nextpnrs Fmax räknar bara register till register; fördröjningen mot stiften är inte begränsad, så tabellen visar inte om SDRAM-tiderna blev bättre. Det avgör minnestestet på kortet.
- **Klockkrav.** M6 har ingen egen `boards/m6_puck_proto.sdc` sedan 2026-10-08, så `clocks.clk_27` har samma 75 MHz-krav som övriga klockor. Seed 0–3 klarar det efter routning ("Klockroutningen, 2026-10-12" nedan). `build.sh` läser fortfarande en `boards/<top>.sdc` om en sådan finns.

## Verifiering 2026-10-08

Nattens körjournal, byggmanifest och baslinje finns i navets
`docs/overnight/2026-10-07/`. R02 ändrar fuzzkampanjens återupptagning:
varje runda sparar inställningar och käll-/simulatorhashar. Ändrade indata
kräver nytt rundnamn; äldre JSONL får sammanfattas men inte återupptas.
`narrow` använder samma geometri/densitet/fältantal som körningen och
kan få nytt namn med `--round`. Håll gemensamt flock även vid användning
av kampanjens eget rundlås.

Mixerns återkomsttest täcker nu både A och B, med den gamla domarregeln
som negativ kontroll. En separat diagnostik för Core #18 kontrollerar
modellens fältstarter mot F/radnummer i den utström som matchat RTL.
Fables rapport om #17/#18 på `e113cf6` och de 490/543 passen från tidigare C3-paket är historik; den accepterade displaycheckerns 566-testresultat står i avsnittet ovan. Modell- och bänkfel är oväntade.
Regeln för mixerns F-bit ändrades 2026-10-08 (#18), och #17 rättades samma dag.

Seed 126 gav samma store/read-checksummefel och X/Z på `e113cf6`-RTL med separat strikt checker och på ren C1-main `629806f`. C3-källan `8d7b0e9` passerar samma frö med 216 kontrollerade rader; kontrollen avvisar också den verkliga felvarianten som skriver till fel ringplats. `fb_display` använder reservvärdet `V_ACTIVE / 3`: fysisk 720-radersgeometri behåller 240. Aldrig initialiserade LOW-platser ger svart, medan äldre data i initialiserade platser behålls enligt ringens regel. Det styrker den testade körningen; den nya kampanjen återstår och alla LOW→BUF-faser är inte därmed verifierade. F-bit, triggerstyrd videogrind och regeln att fältet skrivaren gick med i inte publiceras är oförändrade.

Checksumkontrollen gäller åter varje SDRAM-läsning, även utan efterföljande
bildbeslut. För liten visningstäckning är ett benchfel även vid lägesbyte.
Generatorns kameraförsprång kan förklara kameraålder men undantar inte
fältminnets egen åldersinvariant. De övriga åldersklassificeringarna i
Opus nattpaket finns kvar; kampanjtabellens äldre gröna siffror kommer
från tidigare kontrollversioner.


## Prefixbevarande recovery-verktyg, 2026-10-12

`model/fuzz_recovery.py::append_camera_fields(scenario, fields=4)` returnerar en ny
kameraström med rena fält efter originalet. Originalbytes, styrtider och byteklockor
behålls; fortsättningen synkroniserar kanalernas ankomstfas efter blankning och
följer interlaced/progressiv F-konvention. `generate()` och kampanjkommandonas standardvärde
använder originalstimulus. Recovery är ett eget kontrakt som behöver
nytt rundnamn och ny evidens före kampanjstart.

Fokuserad modell-/resume-verifiering gav **68 pass på 23,65 s**, varav 25 nya
tester för verktyget. Nio fall täcker skalad/full geometri, NTSC/PAL och båda
kamerakonventionerna. A/B-bytes matchar de tre tidigare accepterade native-proven
1345, 1400 och full-PAL1601; skadat prefix och avklippt fortsättningsfält avvisas
av samma oracle. Kampanjens verkliga källmanifest tar med verktyget och avvisar
ett manifest från den gamla källan utan att ändra evidensen. Detta är helper-
och modelltester, ingen ny helsvit, FPGA-routning eller hårdvarumätning.


## Opt-in recovery i kampanjköraren, 2026-10-12

`sim/fuzz_campaign.py` tar `--recovery-fields N` för `run` och `narrow`.
Standardvärdet är 0; ett positivt heltal lägger rena fält efter originalet genom
modellverktyget ovan. Manifestets schema 2 binder antalet och typen av
fortsättning tillsammans med källor och övriga inställningar. Ändrat antal eller
källa kräver ett nytt rundnamn. Budgetuppskattningen tar med de tillagda fälten,
och recovery-körningar behåller sina råfiler även vid PASS.

**75 fokuserade tester passerade på 43,43 s.** Native-prover genom den verkliga
worker-/seed-vägen på fryst `7754112` gav 360 rader på 215,8 s för skalat frö 1345
(densitet 2,5, tio originalfält och fyra recovery-fält), och 6 480 rader på 1 954,0 s
för frö 1601 med full PAL-geometri (densitet 1, åtta originalfält och fyra
recovery-fält, tvingad `pal`/`mode_switch`). Kamera-/CTL-, mixer-,
minnes- och bildspåren är byte-identiska med tidigare accepterade motsvarande
prover. Kompilering, vvp och drain passerar utan fynd, known, edges eller notes.
Root verifierade 160 källhashar och 24 råfiler, återläste modeller/invarianter och
avvisade fel bildord/källrad i nybilden i båda fallen. Kraven på 144/720 rader,
3000 s timeout, checkerpredikat och RTL är oförändrade.

Detta accepterar dessa två opt-in-prover och parameter-/resume-kontrollerna.
Det är ingen ny 260-frökampanj, helsvit eller FPGA-routning; gamlaFAIL-kvitton
och C2:s tidigare källa med 604 pass och dess byggen bevaras. Ingen FPGA-hårdvara är verifierad.
