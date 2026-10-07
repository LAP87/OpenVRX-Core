# Gateware (Tang Nano 20K, Verilog)

> Del av [OpenVRX](https://github.com/LAP87/OpenVRX). Sökvägar som `../research/` och `../design/` syftar på den ursprungliga samlade mappen: forskning finns nu i OpenVRX-navet, kortdesignen i OpenVRX-Puck.

Plan: `docs/GATEWARE_PLAN.md` i navet (OpenVRX). Licens: CERN-OHL-S-2.0, se `LICENSE` i repots rot.

## Status 2026-10-05

| Milstolpe | Toppmodul | Byggd | Verifierad |
|---|---|---|---|
| M0 — testbild 720p60 på kortets HDMI | `top/m0_testpattern.v` | ✔ `build/m0_testpattern.fs` (793 LUT, 3 %; pixel 146 MHz mot 74,25) | Simulering av TMDS och tidsbas |
| M1 — Moneagles TVP5150AM1 → HDMI (luma, 360×240, 720p60), inbäddad BT.656-synk | `top/m1_moneagle_view.v` | ✔ `build/m1_moneagle_view.fs` (809 LUT, 44/46 BSRAM) | Hela ingångsvägen mot facit |
| M1s — samma, separata synksignaler (HSYNC/VSYNC/AVID) | `top/m1s_moneagle_view_sync.v` | ✔ `build/m1s_moneagle_view_sync.fs` (1 054 LUT, 44/46 BSRAM) | Båda polariteter och bytefaser |
| **M2 — full upplösning i färg via SDRAM, fältminne med fyra buffertar** | `top/m2_moneagle_color.v` (kärna `rtl/m2_core.v`) | ✔ `build/m2_moneagle_color.fs` (3 692 LUT 17 %, 17 BSRAM, 2 PLL; SDRAM 108 MHz mot 64,8) | Tre klockdomäner + SDRAM-modell med databladets tider: SDRAM-innehåll och RGB-pixlar mot modell, inga protokollfel i minnesmodellen |
| M2s — som M2 men separata synksignaler | `top/m2s_moneagle_color_sync.v` (`m2_core` med `DISCRETE_SYNC=1`) | ✔ `build/m2s_moneagle_color_sync.fs` (3 876 LUT 18 %, 17 BSRAM) | Mottagaren testad i M1s; kombinationen bara syntes/PnR |
| **M2a — minnestest av SDRAM** (ingen bild; en rad per läspunkt över USB) | `top/m2a_memtest.v` (kärna `rtl/memtest_core.v`) | ✔ `build/m2a_memtest.fs` (2 396 LUT 11 %, 0 BSRAM, 1 PLL; SDRAM 83 MHz mot 64,8) | UART-raderna avkodade mot SDRAM-modellen: rätt läspunkt pekas ut för sex kombinationer av kortfördröjning och klockfas (`sim/test_memtest.py`) |
| **M3 — uppstartsprob** för M4/M6-kopplingen (ingen bild; en rad per dekoder och sekund över USB) | `top/m3_probe.v` | ✔ `build/m3_probe.fs` (2 542 LUT 12 %, 0 BSRAM; 27 MHz-domän 177 MHz, dekoderklockorna 122 och 142 MHz) | Rapportraderna mot en frisk och en felkopplad dekoder, lysdioderna och RX5808-skrivningen på stiften (`sim/test_probe.py`) |
| **M4 — två egna TVP5150-moduler + radvis mixer** | `top/m4_dual_mix.v` | ✔ `build/m4_dual_mix.fs` (8 462 LUT 40 %, 25 BSRAM; SDRAM 117 MHz, pixel 119 MHz) | Mixern mot facit, beslut för beslut och ord för ord, på fält med riktig släcklucka (16 test, `sim/test_mixer.py`); fältminnet och visningen mot facit (`sim/test_fb.py`); I2C mot slavmodeller; RESETB, lysdioder och RX5808-skrivning på toppmodulens stift (`sim/test_top_pins.py`) |
| **M5 alt. C — Moneagle → 1080p60 BT.1120 → LT8618SX** (ingår inte, se M5-avsnittet) | `top/m5c_moneagle_1080p.v` | byggd 2026-10-04 ur källor som inte ingår här; går inte att bygga ur det här repot (3 565 LUT 17 %, 16 BSRAM; pixel 206 MHz mot 148,5) | BT.1120-strömmen avkodad som av en mottagare över en hel bild; LT8618SX-sekvensen mot sidindelad I2C-modell |
| **M6 — puckprototyp steg 1** (M4 + RX5808-styrning + OLED-meny + OSD i videon + mätlogg) | `top/m6_puck_proto.v` | ✔ `build/m6_puck_proto.fs` (12 499 LUT 60 %, 25 BSRAM; SDRAM 105 MHz, pixel 115 MHz, 27 MHz-domän 65 MHz mot 54; seed 2, se "Bygget av M6") | Meny, SPI, OLED, snö-mätare, brusmått, OSD och UART-logg mot modeller (`sim/test_puck_ui.py`, `sim/test_snow_stats.py`, `sim/test_noise_stats.py`); toppmodulens stift som i M4 (`sim/test_top_pins.py`); M4-delen som ovan |

**Inget är provat på riktig hårdvara** — kortet är inte köpt ännu. Siffrorna (LUT, BSRAM och varje klockas Fmax) är nextpnrs resultat efter routning, det sista "Max frequency"-blocket i `build/<top>.pnr.log`, inte uppskattningen efter placering. M0, M2, M2s, M3, M4 och M6 är ombyggda 2026-10-07 ur commit f13581c med `build.sh` (frysta indata, manifest i `build/<top>.build.json`); M1, M1s och M2a 2026-10-06 ur 62a69be, och deras RTL är oförändrad sedan dess. Kravet är 75 MHz på alla klockor utom M6:s 27 MHz-domän (54 MHz, `boards/m6_puck_proto.sdc`); alla klockor klarade sitt krav. I byggena har alla fyra HDMI-par i M4 och M6 samma IOB-fuses som i M0 (`tools/tmds_fuses.py`).

Hela testsviten: `.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools` (332 test). Kör ett tungt jobb i taget, enligt navets `AGENTS.md`.

## Moduler (`rtl/`)

| Modul | Vad | Test |
|---|---|---|
| `bt656_rx.v` | BT.656-mottagare + mått per rad (synkord med felrättning, radlängd, HF-energi). Radnummer räknas från vertikalsläckningen (två synkord i följd med V = 1), inte från F-biten | `sim/test_bt656_rx.py`: bitexakt mot `model/bt656.py` |
| `luma_writer.v` | Varannan lumasampel → bildminnesadress (360 kolumner × 240 rader) | `sim/test_m1_input.py`: varje skrivning mot modellen |
| `dual_clock_ram.v` | Bildminne, skriv på TVP-klockan, läs på pixelklockan (BSRAM) | via M1-bygget |
| `tmds_encoder.v` | DVI TMDS 8b/10b (utan signerade jämförelser, se nedan) | `sim/test_video.py`: 4 200 symboler mot Python-implementation av DVI-specen |
| `video_timing.v` | 720p60-tidsbas (CEA-861) | `sim/test_video.py` |
| `dvi_tx_gowin.v`, `clocks_720p.v` | OSER10 + TLVDS, rPLL 27→371,25 MHz, /5 → 74,25 MHz | via bygge (primitiver enligt apicula-exemplet) |
| `tvp_sync_rx.v` | Mottagare för separata synksignaler (HSYNC/VSYNC/AVID), självinställande polaritet och bytefas | `sim/test_m1s_input.py` |
| `word_packer.v`, `async_fifo.v`, `sdram_burst.v`, `ycbcr2rgb.v`, `clocks_sdram.v` | Ord om två pixlar, klockdomänsbyte, SDRAM-styrning (burstar om 8 ord), BT.601 till RGB utan signerad aritmetik | `sim/test_sdram.py`, `sim/test_m2.py` |
| `fb_sdram.v`, `fb_display.v`, `field_phase.v` | Fältminne i SDRAM med fyra buffertar: väljer vid varje bildstart vilket fält som visas, håller reda på vilka rader som är lagrade och täcker de som saknas; radmappning med halv rads förskjutning mellan fälten; vilket fält som är det nedre avgörs på ankomsttid | `sim/test_fb.py` mot `model/fb_ref.py` (varje beslut, varje läst rad), `model/test_fb_ref.py` |
| `fb_backend.v`, `cdc_sync.v` | Fältminne + visning som en modul (ord in, RGB ut); delas av M2 och M4. **Låglatensläge** (`ll_mode`): förbi SDRAM, ringbuffert på 16 rader, utgången låst till ingångens fält. Klockdomänsövergångarna (toggle-handskakningar och synkade nivåer) ligger i `cdc_sync.v` | `sim/test_m2.py` (båda lägena); övergångarna formellt bevisade, se "Formella bevis" |
| `genlock_timing.v` | Tidsbas som `video_timing.v`, men kan låsas till ingångens fält (låglatensläget); 720p50-rad för PAL. En enstaka tidig trigger kortar inte bilden | `sim/test_m2.py::m2_low_latency`, `sim/test_fb.py`, formellt bevis |
| `m2_core.v` | M2: en TVP (BT.656 eller separata synkar) → `fb_backend` | `sim/test_m2.py` |
| `chan_capture.v`, `mix_chan.v`, `line_mixer.v`, `mixer2.v` | M4: två TVP-kanaler → radvis mixer → ordström. Reglerna står under M4 nedan | `sim/test_mixer.py` mot `model/line_mixer_ref.py`; regeln för parade rader mot Python-prototypen och fem egenskaper på slumpade radföljder i `model/test_line_mixer_ref.py` |
| `bt1120_tx.v`, `clocks_1080p.v`, `lt8618_ctrl.v` (+ genererad `lt8618_rom.vh`) | M5: 16-bitars BT.1120 med inbäddad synk, 148,5 MHz-PLL, LT8618SX-uppstart via I2C | `sim/test_bt1120.py`, `sim/test_m5c.py` (hela 1080p-kedjan avkodad som en mottagare), `sim/test_lt8618.py` |
| `rx5808_spi.v`, `rx5808_tune.v`, `vtx_channels.vh` (genererad), `ssd1306_text.v`, `font5x7.vh` (genererad), `puck_ui.v`, `snow_stats.v`, `bin2bcd.v`, `osd_overlay.v`, `uart_tx.v` | Puck: RX5808-kanalstyrning (SPI) och när kanalen skrivs (0,5 s efter start, vid kanalbyte, varannan sekund utan lås), 48 kanaler med svensk-bandflagga, OLED-text 4×21 tecken utan bildbuffert, meny med två knappar, delad I2C-buss med `tvp_ctrl` (hold/active) | `sim/test_puck_ui.py`: SPI-ord bit för bit mot `model/vtx_channels.py`, skärmbilden (huvud- och mätarsida) avläst ur pixlarna via teckensnittet, inga busskollisioner; `sim/test_rx5808_tune.py`: skrivtidpunkterna mot en modell av regeln; `sim/test_snow_stats.py`, `sim/test_osd.py`; UART-loggen och OSD-visningen i `sim/test_puck_ui.py`; `tools/test_snowlog.py` |
| `noise_stats.v` | Brusmått per mottagare: lumasampel utanför 16–235 per rad och summerat över 1 024 rader, räknat på orden ur kanalens FIFO i mixerns klockdomän. Mixern läser det inte; det går till M6-loggen | `sim/test_noise_stats.py`: varje rad och varje fönster mot `luma_outside()` i `model/bt656.py` på vektorn `ntsc_spikes` (injicerade spikar, gränsvärdena 15/16/235/236, krominans utanför intervallet); negativa kontroller: intervallet 15–236 och räkning av krominans ger andra tal |
| `i2c_master.v`, `tvp_ctrl.v` | I2C; uppstart av egna TVP5150AM1 (reset, 00h/04h/0Dh/03h; 04h maskar SECAM ur autoswitchen), pollning av status 88h/89h, och ny uppstart av en dekoder som har återställts (03h läses tillbaka vid varje pollning, räknare per dekoder). En pollrunda gäller bara hel: ett NACK på någon av de tre läsningarna, eller en återställd dekoder, gör statusen ogiltig tills nästa hela runda (granskningen 2026-10-06, F2). `i2c_master.v` kan skriva upp till 256 databyte efter registeradressen i en transaktion (`wextra`, `wreq`); `tvp_ctrl.v` och `ssd1306_text.v` skriver en byte i taget. Om en slav håller SCL låg längre än 10 ms ger mastern upp: den släpper båda linjerna och avslutar med `nack` och `stuck` | `sim/test_tvp_ctrl.py` mot I2C-slavmodeller (två adresser, delad adress med separata SDA, saknad dekoder, återställd dekoder, dekoder som inte tar emot skrivningar, SDA kortsluten låg, dekoder som kommer in sent); `sim/test_i2c_master.py`: skrivningar om 1, 2, 8 och 256 byte, NACK mitt i och på första databyten, frånvarande adress, återläsning, allt mot `model/i2c_ref.py` (bussen bit för bit, lagrade register); SCL som hålls låg kort (som vanligt) och för gott (mastern ger upp efter `STRETCH_MAX` klockor, nästa transaktion fungerar); negativa kontroller: slav utan autoinkrement, master som inte avbryter efter NACK, master utan tidsgräns |

## Verktyg (allt i projektmappen, inget på systemet)

- `.venv/` (uv): yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, apycula (gowin_pack), cocotb, pytest.
- `.tools/iverilog/` — Icarus Verilog 12 byggd från källkod.
- Bygg: `gateware/build.sh <toppmodul>` → `gateware/build/<toppmodul>.fs`.
- Simulera: `.venv/bin/python -m pytest -q gateware/sim gateware/model`.
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
  - **Inte provat någonstans:** läsning i burst. Där byts ordet på bussen 2,5–6 ns efter nästa SDRAM-klockflank, medan ett enstaka ord ligger kvar. Läspunkten måste alltså träffa ett fönster på 11,9 ns, och var det ligger beror på kortets fördröjning (klockan ut plus data tillbaka). Med 225° och standardläspunkten läses rätt ord om fördröjningen är 3,3–15,2 ns (`sim/test_sdram.py`). Den är inte mätt, och byggena har inga tidskrav på I/O: i M2-bygget placerades läsvipporna 13–39 rutor från sina stift, så den skiljer mellan dataledningar och mellan byggen.
  - Kör därför minnestestet (M2a nedan) före M2 och M4.
- T_RCD/T_RP/T_RC är 2/2/6 klockor, som NESTang anger. Databladet för EM638325-6 kräver 18 ns för de två första, alltså 2 klockor. Till 2026-10-05 stod här 180° och 1/1/4, vilket ingen uppströms kör.
- Läspunkten är `RD_SAMPLE` i `rtl/sdram_burst.v` (alla toppmoduler) eller parametern med samma namn i `rtl/fb_backend.v`. Fel läspunkt ger en bild som är förskjuten 2 pixlar eller trasig i 8-pixelsblock.
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

Annan fas utan att ändra källkod: `SDRAM_PHASE=12 gateware/build.sh m2a_memtest` ger `build/m2a_memtest_phase12.fs`. Talet är sextondelar av en period: 8 = 180°, 10 = 225° (standard), 12 = 270°. Senare fas passar kortare fördröjning. Testet mäter sitt eget bygge, och i M4 och M6 hamnar läsvipporna på andra platser. Välj därför en fas där `rs=5` är ren även ett steg (0,96 ns) åt vardera hållet, och för in den som `PSDA_SEL` i `rtl/clocks_sdram.v`.

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
- Två rader paras om de har samma radnummer och kommer inom 15,8 µs från varandra. Av ett par visas den renare raden (minst HF-energi), med hysteres, eller en blandning när de är ungefär lika rena. En dålig rad (trasigt synkord, fel längd, olåst dekoder, tvingad från menyn) förlorar mot en bra. En rad där inte alla 360 ord kom i följd (till exempel sen SAV med rätt radlängd) lagras inte alls, så ringens gamla ord kan inte visas; den räknas som dålig, och den andra kanalens rad med samma nummer får fylla luckan (granskningen 2026-10-06, F1; `sim/test_mixer.py::test_incomplete_line_is_not_stored`).
- En rad utan partner avgörs 15,8 µs efter att den kom. Den visas om den kommer från den aktuella kanalen, eller som lucktätning när kanalerna går i takt och den andra kanalen inte levererade något intill den.
- Utan parade rader byter mixern kanal när den aktuella kanalens åtta senaste rader är dåliga och den andras åtta bra, eller när den aktuella har varit tyst i 8 av den andras rader (i takt) eller 40 (ur takt, längre än en vertikalsläckning). Ingen tidsgräns i klocktid ingår i besluten.
- Raderna lämnar mixern i stigande ordning inom ett fält, och utströmmens F-bit låses vid fältets första rad.

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

M4 ställer själv båda mottagarna på F4 5800 MHz (`rtl/rx5808_tune.v`, samma stift som M3 och M6): 0,5 s efter start och sedan varannan sekund så länge ingen dekoder är låst. Testat mot en modell av regeln i `sim/test_rx5808_tune.py`.

RESETB låg på PIN25 (J6-10) till 2026-10-05. Stift 25–42 (bank 4 och 5) bär HDMI-paren, och en vanlig utgång där ändrar hur Apicula packar klockparet: se [BRINGUP.md](BRINGUP.md) avsnitt 5. Stiften till lysdiod 3–5 används därför som stiftlistestift (J6-18, J6-17, J6-16), och toppmodulerna M3, M4 och M6 har bara tre lysdioder. `tools/test_tmds_bank_outputs.py` vaktar att ingen toppmodul med HDMI har en vanlig utgång eller in/utgång på stift 25–42, och `tools/tmds_fuses.py` jämför färdiga bitströmmars HDMI-par mot M0. Kör testet efter varje Apicula-uppgradering, som `tools/test_lvds_bank_inputs.py`.

Lysdioder (tänd = sant): LED0 hjärtslag, 1 Hz när båda dekodrarna svarar på I2C och rapporterar H- och V-lås, annars 4 Hz. LED1 rader från A, LED2 rader från B. Testat i simulering av hela toppmodulen (`sim/test_top_pins.py`).

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

> Koppling, uppstartsordning och felsökning steg för steg: [BRINGUP.md](BRINGUP.md). Ändrat 2026-10-04: SPI DATA och SEL flyttade från PIN53/52 (konfigurationsstift och HDMI-DDC på kortet) till lysdiodsstiften 19/20. Ändrat 2026-10-05: RESETB flyttad från PIN25 till lysdiodsstift 18 (se M4). Lysdioderna i M6 är tre, samma som i M4: LED0 hjärtslag (1 Hz när båda dekodrarna är låsta, annars 4 Hz), LED1 rader från A, LED2 rader från B.

`top/m6_puck_proto.v` → `build/m6_puck_proto.fs`. Allt från M4 plus:

| Signal | Tang Nano 20K | Ansluts till |
|---|---|---|
| RX5808 SPI CLK | PIN71 (J5-18) | båda modulernas "CH3" |
| RX5808 SPI DATA | PIN19 (J6-17, lysdiod 4) | båda modulernas "CH1" |
| RX5808 SEL | PIN20 (J6-16, lysdiod 5) | båda modulernas "CH2" |
| OLED SSD1306 128×32 (I2C 3Ch) | SCL PIN75 (J6-3), SDA PIN85 (J6-4) | samma buss som dekoder A; OLED-modulen matas med 3,3 V |
| OK-knapp | S1 (PIN88) | kortets knapp — **inte längre reset** |
| NEXT-knapp | S2 (PIN87) | kortets knapp |

RX5808-modulerna måste ha "SPI-moden" (annars styrs de av sina kanalstift). Deras videoutgång går till dekoderkortets videoingångar, som också matar dem med 5 V.

S1 och S2 sitter på FPGA:ns MODE0 och MODE1. Håll ingen av dem intryckt när kortet får ström, annars laddas bitströmmen inte från flash ([BRINGUP.md](BRINGUP.md) avsnitt 5).

Skärmen (exakt 21 tecken per rad; `>` visar valt fält):
```
>BAND F   CH 4  5800
 MODE MIX VIEW A  BUF
 A LOCK    B NOSIG
 SE BAND OK
```
OK byter fält (band → kanal → läge → latens → sida), NEXT stegar värdet. `BUF`/`LOW` är videovägen: `BUF` går via SDRAM-bildbufferten, `LOW` är låglatensläget (se nedan). Bandbyte och kanalbyte programmerar om båda mottagarna direkt. Kanalen skrivs också 0,5 s efter start och sedan varannan sekund så länge ingen dekoder är låst (`rtl/rx5808_tune.v`). Läge MIX låter mixern välja; A eller B tvingar en mottagare. Kanaler utanför 5725–5875 MHz visar `!OUTSIDE SE BAND`. Start: F4 5800 MHz.

**Mätarsidan ("snö-mätare")**: OK till femte fältet (markören hamnar på rad 4), NEXT växlar sida.
```
>METER   F4  5800
A  12345 ########
B   2345 ######
 USE A 40 B 34 M 25
```
Talen är medel-HF-energin per bildrad (summan |Y[n]−Y[n−1]|, samma mått som mixern väljer på) över 1 024 rader (≈ 65 ms) per mottagare. Stapeln är logaritmisk: ett block per fördubbling över 32. `  ----` betyder att inga rader kommer från den mottagaren. USE = andel av de senaste 1 024 mixerbesluten som visade A, B eller en blandning. Talen räknas om i `snow_stats.v` (mixerns klockdomän) och visas via en sekventiell decimalomvandlare (`bin2bcd.v`).

Används för egenstörningsmätningen i `design/PUCK_2027_KONCEPT.md` i OpenVRX-Puck ("Inbyggt mätinstrument"): stillastående kamera, VTX på fast avstånd, jämför värdena med HDMI på/av, kanal F4 mot andra kanaler, mottagarna på olika avstånd och med/utan skärmburk. Måttet beror också på bildinnehållet, så bara jämförelser med samma motiv betyder något.

**OSD i videon** (`osd_overlay.v`): samma fyra rader som OLED:n, 3× förstorade, vita på en halvmörk platta längst ned i 4:3-fönstret (x 176, y 576 i 720p). Syns i 5 s efter varje knapptryck och hela tiden på mätarsidan, så att menyn går att läsa i bilden, utan att se på pucken. Pixelexakt testad (`sim/test_osd.py`).

**Mätlogg över USB** (`uart_tx.v`, PIN69 → kortets BL616 USB-UART, 115200 8N1): en rad per mätfönster (≈ 15/s), 57 byte med CR LF:
```
S 012345 002345 000017 000000 040 034 025 F4 5800 MIX -
```
snö A, snö B, brus A, brus B (`------` = inga rader), % av mixerbesluten från A / B / blandning, kanal, MHz, läge, och sist `!` om mixern sedan start har tappat en rad för att dess radplatser var fulla (annars `-`). Äldre bitströmmar skickar raden utan brusvärdena (43 byte); `snowlog.py` läser båda.

**Brus** (`noise_stats.v`) är antalet lumasampel utanför 16–235 under de senaste 1 024 raderna från mottagaren (en rad har 720). BT.656 tillåter 1–254, men en dekoder håller bildens luma inom 16–235, så det som hamnar utanför är brusklick och störd synk. Till skillnad från snövärdet beror det inte på hur detaljrik bilden är. Det räknas på orden som lämnar kanalens FIFO, innan mixern väljer, och mixern använder det inte. Simulerat mot `luma_outside()` i `model/bt656.py` (`sim/test_noise_stats.py`); om det skiljer brus från bildinnehåll på riktig signal är inte provat. Det visas bara i loggen, inte på OLED:n. M6-siffrorna i tabellen ovan gäller bygget med brusmåttet.

På datorn (Windows: `COM5` i stället för `/dev/ttyUSB1`; den vägen är inte provad mot en riktig port):
```
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_pa --seconds 30 --out emi.csv
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_av --seconds 30 --out emi.csv
python gateware/tools/snowlog.py --summary emi.csv
```
(BL616 visar två serieportar; UART:en är oftast den andra.) Sammanfattningen visar medianen per etikett, alltså en mätserie per testvillkor. CSV:n har kolumnerna `time, label, snow_a, snow_b, noise_a, noise_b, use_a, use_b, use_mix, channel, mhz, mode, dropped`; `snowlog.py` vägrar lägga till rader i en fil med andra kolumner.

Ingen RSSI ännu: RX5808:s RSSI är analog och Tang Nano 20K saknar ADC. Det kommer med en extern I2C-ADC eller med GW5A-25:s inbyggda ADC.

## Bildvägen efter mixern: `BUF` och `LOW`

Två lägen, valbara i menyn medan det kör (`LOW_LATENCY=1` i M4 väljer `LOW`).

**`BUF`** (`rtl/fb_sdram.v`): fälten skrivs till fyra buffertar i SDRAM, och utgången går i fast 720p60.
- Vilken buffert en bild visar bestäms i SDRAM-domänen, där skrivaren finns, vid bildens första radbegäran. Skrivaren får aldrig bufferten som visas, dess reserv eller den nyss publicerade. (Förut skickade visningen sitt val över klockdomänsgränsen, och en källa snabbare än utgången kunde få bufferten som visades.)
- En bild visar fältet som håller på att skrivas om skrivaren ligger minst 4 rader före (44 för fält över 270 rader, som en 60 Hz-utgång läser fortare än de kommer). Annars visas senaste hela fält. `RT_EN = 0` ger bara hela fält.
- En bit per rad och buffert säger att raden är lagrad i sin helhet. En rad som saknas ersätts av raden ovanför (högst två i följd) och därefter av samma rad i fältet före. Finns ingen rad ovanför i bilden och ingen lagrad rad i fältet före (en saknad första rad i det första fältet), skrivs en svart rad i radbufferten utan att SDRAM läses (granskningen 2026-10-06, F3; `sim/test_fb.py::test_missing_first_line_is_black`). Visningen får alltså aldrig en halvskriven rad, vad skrivaren än gör.
- Bilden skalas efter det mindre av de två senaste fältens radantal när de skiljer högst 2 rader (243/244, 287/288). Ett avklippt fält ändrar inte skalan.

**`LOW`**: utan bildbuffert. Mixerns rader skrivs direkt till en ringbuffert på 16 rader i FPGA:ns block-RAM, och 720p-utgången låses till ingångens fält (`genlock_timing.v`). Varje utbild startar när rad 1 i ett nytt fält har kommit, och raderna läses medan de kommer in.

| | `BUF` | `LOW` |
|---|---|---|
| Översta radens ålder när den visas, NTSC | 0,3–17 ms. Räknat ur radtiderna; `sim/test_fb.py` visar vinsten på ett fält i en nedskalad bild. Med `RT_EN = 0`: 17–33 ms | ca 0,1 ms överst i bilden, ca 0,8 ms nederst |
| Utgång vid NTSC | 720p60,00, ett fält visas två gånger var 17:e sekund | 720p 59,94 Hz (bilder om 750/751 rader) |
| Utgång vid PAL | 720p60 (var 5:e fält upprepas, ryckigt) | 720p50 (CEA-861-radlängd 1980) |
| Ingen signal | grå ruta | grå ruta, utgången frigår |
| Rad som saknas | raden ovanför, därefter förra fältets rad | det som fanns i ringens plats 16 rader tidigare |
| Falsk fältstart, brus på ingången | påverkar inte utgångens timing | en tidig trigger ignoreras; tre i följd ger en kort bild, sedan ingen fler på 32 bilder |

Tiderna räknas från att raden är klar i FPGA:n. Dekoderns egen fördröjning (dess kamfilter arbetar över flera rader) och skärmens kommer till.

**Fälten ligger en halv rad isär.** Fälten i en sammanflätad bild kommer omväxlande en radtid längre och en radtid kortare isär (263/262 rader i NTSC). `field_phase.v` avgör på ankomsttiden vilket fält som är det nedre, inte på F-biten: en TVP5150AM1 håller F på 1 när den tar signalen för icke sammanflätad. `fb_display.v` ritar det nedre fältet en halv källrad lägre (`BOB = 0` stänger av det). I `LOW` fördröjs dessutom bildstarten för det tidiga fältet med halva skillnaden, så att utbilderna blir lika långa; utan det växlar de med tre rader (`LL_EQ = 0`).

**Varför `LOW` fungerar:** utgången skannar varje källrad långsammare (3 × 22,2 µs) än ingången levererar den (63,6 µs). Läsaren kan alltså aldrig gå om skrivaren, och skrivaren ligger högst cirka 13 rader före (därav 16 platser). Upplösningen är densamma i båda lägena, så läget går att byta medan det kör. Vid byte mellan PAL och NTSC i `LOW` ändras bildfrekvensen, och skärmen synkar om (1–2 s).

**Risk att prova på hårdvara:** en del skärmar gillar inte att antalet rader per bild växlar (750/751), och vad en skärm gör med den korta bilden vid omlåsning är inte känt. CVBS2HDMI kör samma knep (524/525 rader) utan problem på vanliga skärmar. XR-glasögon tar enligt navets anteckningar inte emot 720p alls; `LOW` är för skärmar och goggles som gör det. Testat i simulering: `sim/test_m2.py::m2_low_latency` (låsning, bildperiod = fältperiod, pixlar mot modell) och `sim/test_fb.py` (lika långa bilder, fält utan rad 1, falsk fältstart, källa som flyttar sig).

**Lägesbyte under drift är simulerat** (`sim/test_fb.py::test_mode_switch_buf_low_buf`, `ll_mode` 1 mitt i ett fält och 0 igen sent i ett fält, fem fält `BUF`, sex `LOW`, sju `BUF`). Kontrollerat vid utgången: inget X/Z på r, g, b, de, hsync, vsync efter första bilden efter varje byte; varje bild är mellan V_TOTAL−1 och V_TOTAL+8 rader från vsync till vsync (47–49 från tredje bilden efter ett byte); inga SDRAM-protokollfel. `BUF` → `LOW`: första bilden efter bytet har ingen video (skrivaren går med mitt i fältet, så bildtriggern har inte kommit), sedan visar varje bild ett helt fält, i följd, det senaste. `LOW` → `BUF`: bilderna fram till första publicerade fältet efter bytet har ingen video, sedan är varje rad rätt och varje bild ett fält. Testet hittade ett fel som är rättat i två delar: `fb_display.v` behöll "har ett publicerat fält" från tiden före `LOW`, och `fb_sdram.v` publicerade det halva fält skrivaren gick med i (bara de sista raderna lagrade, ingen reserv att falla tillbaka på). Första bilden visade därför rad 0 ur bufferten som låg där före `LOW` (ett 7 fält gammalt fält) upprepad över de rader skrivaren inte hunnit till. Nu glöms publicerade fält medan `LOW` är aktivt, och fältet skrivaren gick med i släpps utan publicering (samma sak vid start: första hela fältet är det första som visas). Utan vardera delen faller testet (körd en gång för hand med var och en borttagen). Negativ kontroll: `test_mode_switch_checks_catch_faults` (fel som läggs in i testbänken, inte i RTL: fel tagg på ett ord, X på r, extra vsync-puls) måste fångas var och en av sin kontroll.

## Apicula-fällor (från otanl/CVBS2HDMI, kontrollerade 2026-10-04)

- **Signerade jämförelser** har felkompilerats av Apicula (seed-beroende). `tmds_encoder.v` och `ycbcr2rgb.v` är omskrivna utan signerad aritmetik och bitexakt kontrollerade mot de gamla versionerna (alla 16,7 miljoner YCbCr-värden, plus en lång slumpsekvens genom TMDS-kodaren). Ingen annan modul använder `signed`.
- **Insignaler i samma I/O-bank som HDMI** (bank 5: stift 26–31, där dekoder A:s buss ligger) packades i en nyare Apicula som LVDS-mottagare. **Vår Apicula 0.32 gör inte det.** `tools/test_lvds_bank_inputs.py` bygger två små designer, med och utan LVDS-utgång i banken, och kräver att insignalernas IOB-fuses är identiska. En riktig LVDS-mottagare som negativ kontroll visar att testet ser skillnaden. Kör testet efter varje Apicula-uppgradering. Om det fallerar: packa via en omslagare som CVBS2HDMI:s `scripts/gowin_pack_io.py` (MIT).
- Inga `DRIVE=`/`BANK_VCCIO=` på LVDS25-stift (gäller redan våra cst-filer).
- **Vanliga utgångar i HDMI-parens banker** (stift 25–42) ändrar hur Apicula packar klockparet. `tools/test_tmds_bank_outputs.py` vaktar cst-filerna, och `tools/tmds_fuses.py` jämför färdiga bitströmmar mot M0. Kör testet efter varje Apicula-uppgradering.

## M3 — uppstartsprob

`top/m3_probe.v`, samma stift som M4/M6. Visar en gång i sekunden, per dekoder: SCLK-frekvens, vilka databitar som växlar, radlängder, rader och fält per sekund, synkfel, I2C-svar, statusregister och hur många gånger dekodern har hittats återställd och startats om. Lysdioder: LED0 hjärtslag 1 Hz, LED1 SCLK från A, LED2 SCLK från B. Pull-test med `PULL=UP` eller `PULL=DOWN gateware/build.sh m3_probe` (bit 0–6; bit 7 är dekoderns adresstrapp och får ingen pull, `tools/test_build_pull.py`). Allt om koppling och tolkning finns i [BRINGUP.md](BRINGUP.md).

## Formella bevis

`formal/run.sh` (cirka en minut, ingår i testsviten via `tools/test_formal.py`) bevisar med k-induktion i yosys, utan extern lösare:

| Modul | Bevisat | Negativ kontroll |
|---|---|---|
| `async_fifo.v` (djup 4 och 8) | med två fria klockor och fria in-signaler: ingen överflödning eller underflödning, varje sidas bild av den andra pekaren är konservativ, Gray-pekarna stämmer och rör sig ett steg i taget, och ett ord kommer ut oförändrat | en FIFO som aldrig är full flödar över; en som aldrig är tom flödar under |
| `genlock_timing.v` | med fria lock/trig/h_alt: räknarna håller sig inom gränserna, varje bild slutar inom V_TOTAL + MAX_WAIT rader, varje bild som inte är en avsiktlig omlåsning har minst V_TOTAL − 1 rader, och två omlåsningar ligger minst HOLD bildstarter isär | utan väntegränsen kan en bild stå still; med två överhoppade rader blir en bild för kort; utan spärrtiden kan två korta bilder följa på varandra |
| `cdc_sync.v` `toggle_rx` (radbegäran, publicering, lågfördröjningstrigger i `fb_backend.v`) | två fria klockor, högst 3 flanker av den ena mellan två av den andra (27–108 MHz mot 74,25 MHz), ett sampel mitt i en ändring får bli vilket värde som helst: med vändning högst var 16:e sändarklocka och data som hålls 16 klockor tappas eller dubbleras ingen händelse, varje händelse tas emot inom 4 mottagarflanker, och mottagen data är den skickade | flanken tagen direkt från andra domänen ger fel data; vändning var 8:e klocka tappar en händelse; data som ändras efter 2 klockor kommer fram fel |
| `cdc_sync.v` `toggle_tx` (lågfördröjningstriggerns sändarsida) | en klocka, fria begäranden: vändningar minst 16 klockor isär, data hålls från vändning till vändning, varje begäran skickas inom 16 klockor med den senaste datan; det är sändarvillkoren i raden ovan | en sändare som vänder direkt på varje begäran bryter avståndet |
| `cdc_sync.v` `sync2` (`ll_mode`) | lägesbiten ändras bara på den egna klockans flank och är rätt från tredje flanken efter ett byte; domänerna är bara oense under de tre flankerna | utan `sync2` ändras biten mellan flankerna; efter två flanker är den inte säkert inställd |
| `fb_display.v` (radbuffertens platser) | med den riktiga tidsbasen: en rad som begärs under en aktiv utrad hamnar på en plats som inte läses under resten av raden | begäran till platsen som läses faller |

Egenskaperna står i modulerna inom `ifdef FORMAL` eller i harneskarna i `formal/`. Vad som inte är bevisat om klockdomänsövergångarna, och varför, står i [formal/README.md](formal/README.md): bland annat att två synksteg räcker mot metastabilitet, att SDRAM-sidan hinner skriva en rad, lågfördröjningsringen. Radantalet som följer lågfördröjningstriggern kunde ändras på vägen till pixeldomänen när ett fält var mycket kort; det hålls nu av `toggle_tx` (`sim/test_ll_payload.py`).

## Bygget av M6

- **Seed.** Med seed 0 och 1 kan nextpnr inte lägga kortets klocka på det globala klocknätet ("Can't route the clocks.clk_27 net"); med seed 2 och 3 går det. Orsaken är inte utredd, och M4 ur samma träd bygger med seed 0. `boards/m6_puck_proto.seed` håller därför seed 2, och `build.sh` tar `SEED=<n>` och säger till när klockroutningen misslyckas. Efter en ändring i M6 kan ett annat seed behövas.
- **27 MHz-domänen** nådde 98,5 MHz efter routning i bygget av 62a69be, 90 MHz med brusmåttet (a6640b0) och 65 MHz i bygget av f13581c. Den kritiska vägen är i alla tre menyns kanaltabell i `puck_ui.v` fram till RX5808:s skiftregister; skillnaden är placering. Marginalen mot klockans verkliga 27 MHz är fortfarande mer än dubbel, men den minskar. `boards/m6_puck_proto.sdc` begär 54 MHz av den klockan, dubbla dess frekvens; övriga klockor får 75 MHz som i de andra byggena.
