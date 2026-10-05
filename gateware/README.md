# Gateware (Tang Nano 20K, Verilog)

> Del av [OpenVRX](https://github.com/LAP87/OpenVRX). Sökvägar som `../research/` och `../design/` syftar på den ursprungliga samlade mappen: forskning finns nu i OpenVRX-navet, kortdesignen i OpenVRX-Puck.

Plan: `../design/GATEWARE_PLAN.md`. Licens: CERN-OHL-S-2.0, se `LICENSE` i repots rot.

## Status 2026-10-04

| Milstolpe | Toppmodul | Byggd | Verifierad |
|---|---|---|---|
| M0 — testbild 720p60 på kortets HDMI | `top/m0_testpattern.v` | ✔ `build/m0_testpattern.fs` (792 LUT, 3 %; pixel 140 MHz mot 74,25) | Simulering av TMDS och tidsbas |
| M1 — Moneagles TVP5150AM1 → HDMI (luma, 360×240, 720p60), inbäddad BT.656-synk | `top/m1_moneagle_view.v` | ✔ `build/m1_moneagle_view.fs` (822 LUT, 44/46 BSRAM) | Hela ingångsvägen mot facit |
| M1s — samma, separata synksignaler (HSYNC/VSYNC/AVID) | `top/m1s_moneagle_view_sync.v` | ✔ `build/m1s_moneagle_view_sync.fs` (1 052 LUT, 44/46 BSRAM) | Båda polariteter och bytefaser |
| **M2 — full upplösning i färg via SDRAM, trippelbuffert, ingen rivning** | `top/m2_moneagle_color.v` (kärna `rtl/m2_core.v`) | ✔ `build/m2_moneagle_color.fs` (3 154 LUT 15 %, 16 BSRAM, 2 PLL; SDRAM 127 MHz mot 64,8) | Tre klockdomäner + SDRAM-modell: SDRAM-innehåll och RGB-pixlar mot modell |
| M2s — som M2 men separata synksignaler | `top/m2s_moneagle_color_sync.v` (`m2_core` med `DISCRETE_SYNC=1`) | ✔ `build/m2s_moneagle_color_sync.fs` (3 387 LUT 16 %, 4 BSRAM) | Mottagaren testad i M1s; kombinationen bara syntes/PnR |
| **M3 — uppstartsprob** för M4/M6-kopplingen (ingen bild; en rad per dekoder och sekund över USB) | `top/m3_probe.v` | se bygget nedan | Rapportraderna mot en frisk och en felkopplad dekoder (`sim/test_probe.py`) |
| **M4 — två egna TVP5150-moduler + radvis mixer** | `top/m4_dual_mix.v` | ✔ `build/m4_dual_mix.fs` (7 026 LUT 33 %, 24 BSRAM; SDRAM 90 MHz) | Mixern bitexakt mot facit (två klockor, snö, trasig synk, död kanal, olåst dekoder); I2C mot slavmodeller |
| **M5 alt. C — Moneagle → 1080p60 BT.1120 → LT8618SX** (ingår inte, se M5-avsnittet) | `top/m5c_moneagle_1080p.v` | ✔ `build/m5c_moneagle_1080p.fs` (3 565 LUT 17 %, 16 BSRAM; pixel 206 MHz mot 148,5) | BT.1120-strömmen avkodad som av en mottagare över en hel bild; LT8618SX-sekvensen mot sidindelad I2C-modell |
| **M6 — puckprototyp steg 1** (M4 + RX5808-styrning + OLED-meny + OSD i videon + mätlogg) | `top/m6_puck_proto.v` | ✔ `build/m6_puck_proto.fs` (10 341 LUT 49 %, 24 BSRAM; SDRAM 84 MHz, 27 MHz-domän 81 MHz, pixel 131 MHz) | Meny, SPI, OLED, snö-mätare, OSD och UART-logg mot modeller (`sim/test_puck_ui.py`, `sim/test_snow_stats.py`); M4-delen som ovan |

**Inget är provat på riktig hårdvara** — kortet är inte köpt ännu. Siffrorna är från nextpnr efter routning (2026-10-04). BSRAM-ökningen (+12) är låglatenslägets ringbuffert på 16 rader.

Hela simuleringssviten: `.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools` (62 test, ca 8 min).

## Moduler (`rtl/`)

| Modul | Vad | Test |
|---|---|---|
| `bt656_rx.v` | BT.656-mottagare + mått per rad (synkord med felrättning, radlängd, HF-energi) | `sim/test_bt656_rx.py`: bitexakt mot `model/bt656.py` |
| `luma_writer.v` | Varannan lumasampel → bildminnesadress (360 kolumner × 240 rader) | `sim/test_m1_input.py`: varje skrivning mot modellen |
| `dual_clock_ram.v` | Bildminne, skriv på TVP-klockan, läs på pixelklockan (BSRAM) | via M1-bygget |
| `tmds_encoder.v` | DVI TMDS 8b/10b (utan signerade jämförelser, se nedan) | `sim/test_video.py`: 4 200 symboler mot Python-implementation av DVI-specen |
| `video_timing.v` | 720p60-tidsbas (CEA-861) | `sim/test_video.py` |
| `dvi_tx_gowin.v`, `clocks_720p.v` | OSER10 + TLVDS, rPLL 27→371,25 MHz, /5 → 74,25 MHz | via bygge (primitiver enligt apicula-exemplet) |
| `tvp_sync_rx.v` | Mottagare för separata synksignaler (HSYNC/VSYNC/AVID), självinställande polaritet och bytefas | `sim/test_m1s_input.py` |
| `word_packer.v`, `async_fifo.v`, `sdram_burst.v`, `fb_sdram.v`, `fb_display.v`, `ycbcr2rgb.v`, `clocks_sdram.v` | M2:s SDRAM-bildbuffert och visning (`ycbcr2rgb.v` helt utan signerad aritmetik) | `sim/test_sdram.py`, `sim/test_m2.py` |
| `fb_backend.v` | SDRAM-trippelbuffert + visning som en modul (ord in, RGB ut); delas av M2 och M4. **Låglatensläge** (`ll_mode`): förbi SDRAM, ringbuffert på 16 rader, utgången låst till ingångens fält | `sim/test_m2.py` (båda lägena) |
| `genlock_timing.v` | Tidsbas som `video_timing.v`, men kan låsas till ingångens fält (låglatensläget); 720p50-rad för PAL | `sim/test_m2.py::m2_low_latency` |
| `m2_core.v` | M2: en TVP (BT.656 eller separata synkar) → `fb_backend` | `sim/test_m2.py` |
| `chan_capture.v`, `mix_chan.v`, `line_mixer.v`, `mixer2.v` | M4: två TVP-kanaler → radvis mixer (val/blandning med hysteres) → ordström | `sim/test_mixer.py` mot `model/line_mixer_ref.py`; regeln mot Python-prototypen i `model/test_line_mixer_ref.py` |
| `bt1120_tx.v`, `clocks_1080p.v`, `lt8618_ctrl.v` (+ genererad `lt8618_rom.vh`) | M5: 16-bitars BT.1120 med inbäddad synk, 148,5 MHz-PLL, LT8618SX-uppstart via I2C | `sim/test_bt1120.py`, `sim/test_m5c.py` (hela 1080p-kedjan avkodad som en mottagare), `sim/test_lt8618.py` |
| `rx5808_spi.v`, `rx5808_tune.v`, `vtx_channels.vh` (genererad), `ssd1306_text.v`, `font5x7.vh` (genererad), `puck_ui.v`, `snow_stats.v`, `bin2bcd.v`, `osd_overlay.v`, `uart_tx.v` | Puck: RX5808-kanalstyrning (SPI) och när kanalen skrivs (0,5 s efter start, vid kanalbyte, varannan sekund utan lås), 48 kanaler med svensk-bandflagga, OLED-text 4×21 tecken utan bildbuffert, meny med två knappar, delad I2C-buss med `tvp_ctrl` (hold/active) | `sim/test_puck_ui.py`: SPI-ord bit för bit mot `model/vtx_channels.py`, skärmbilden (huvud- och mätarsida) avläst ur pixlarna via teckensnittet, inga busskollisioner; `sim/test_rx5808_tune.py`: skrivtidpunkterna mot en modell av regeln; `sim/test_snow_stats.py`, `sim/test_osd.py`; UART-loggen och OSD-visningen i `sim/test_puck_ui.py`; `tools/test_snowlog.py` |
| `i2c_master.v`, `tvp_ctrl.v` | I2C; uppstart av egna TVP5150AM1 (reset, 00h/04h/0Dh/03h; 04h maskar SECAM ur autoswitchen), pollning av status 88h/89h, och ny uppstart av en dekoder som har återställts (03h läses tillbaka vid varje pollning, räknare per dekoder) | `sim/test_tvp_ctrl.py` mot I2C-slavmodeller (två adresser, delad adress med separata SDA, saknad dekoder, återställd dekoder, dekoder som inte tar emot skrivningar, SDA kortsluten låg, dekoder som kommer in sent) |

## Verktyg (allt i projektmappen, inget på systemet)

- `.venv/` (uv): yowasp-yosys, yowasp-nextpnr-himbaechel-gowin, apycula (gowin_pack), cocotb, pytest.
- `.tools/iverilog/` — Icarus Verilog 12 byggd från källkod.
- Bygg: `gateware/build.sh <toppmodul>` → `gateware/build/<toppmodul>.fs`.
- Simulera: `.venv/bin/python -m pytest -q gateware/sim gateware/model`.
- Flasha (när kortet finns): openFPGALoader behövs, t.ex. `sudo pacman -S openfpgaloader` (Arch), sedan
  `openFPGALoader -b tangnano20k gateware/build/m0_testpattern.fs` (RAM) eller med `-f` (flash).

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

`top/m1s_moneagle_view_sync.v` → `build/m1s_moneagle_view_sync.fs` (1 052 LUT, 5 %; 44/46 BSRAM; pixelklocka 144,8 MHz, TVP-domän 186,5 MHz mot krav 75). Mottagare: `rtl/tvp_sync_rx.v`.

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
                 3 halvbildsbuffertar; publicerar färdig halvbild; skriver aldrig i den som visas
Pixel 74,25 MHz: fb_display: senaste färdiga halvbild per bild, Bresenham radmappning (240/243/288 rader),
                 förhämtning av nästa källrad till 4-plats radbuffert, YCbCr -> RGB (BT.601), 4:3-fönster
```

- SDRAM-styrningen (`rtl/sdram_burst.v`) bygger på nand2mario:s hårdvaruprovade timing (64,8 MHz, CAS 2) men med 32-bitars burstar om 8 ord. Läspunkten är en parameter (`RD_SAMPLE`) om den behöver justeras på riktig hårdvara — symptom: bilden förskjuten 2 pixlar sidledes eller "trasig" i 8-pixelsblock.
- Bandbredd: ca 21 MB/s in + ca 21 MB/s ut mot ca 170 MB/s kapacitet.
- Halvbild visas med radupprepning (bob): ingen kamskada vid snabba FPV-rörelser, ca 1 halvbild (16,7–20 ms) buffertlatens.
- Lysdioder (tänd = sant): LED0 hjärtslag, LED1 BT.656-rader kommer in, LED2 SDRAM initierat, LED3 halvbild visas, LED4 SDRAM-PLL låst, LED5 pixel-PLL låst.
- SDRAM-stiftens placering verifierad i place & route (55 signaler på IOL/IOR-platserna).

**M2s:** samma 13 trådar som M1s (M1-kablarna + HSYNC PIN75/J6-3, VSYNC PIN85/J6-4, AVID PIN25/J6-10). Lysdioderna betyder samma som i M2; LED1 = AVID-rader kommer in.

## `model/` — facit

`model/bt656.py` är referensmodellen; `model/make_vectors.py` skriver `vectors/`. Se docstrings och `model/test_bt656.py`.

## M4 — två egna mottagare/dekodrar med mixer

`top/m4_dual_mix.v` → `build/m4_dual_mix.fs`. Två TVP5150-moduler (se `../bom/GATEWARE_DEVKIT.md` #3), var och en matad med CVBS från en egen 5,8 GHz-mottagare på samma kanal. FPGA:n startar dekodrarna via I2C; mixern väljer per rad den renaste kanalen eller blandar (detaljer och begränsningar: `../design/GATEWARE_PLAN.md`, "M4-implementering").

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

M4 ställer själv båda mottagarna på F4 5800 MHz (`rtl/rx5808_tune.v`, samma stift som M3 och M6): 0,5 s efter start och sedan varannan sekund så länge ingen dekoder är låst. Testat mot en modell av regeln i `sim/test_rx5808_tune.py`.

RESETB låg på PIN25 (J6-10) till 2026-10-05. Stift 25–42 (bank 4 och 5) bär HDMI-paren, och en vanlig utgång där ändrar hur Apicula packar klockparet: se [BRINGUP.md](BRINGUP.md) avsnitt 5. Stiften till lysdiod 3–5 används därför som stiftlistestift (J6-18, J6-17, J6-16), och toppmodulerna M3, M4 och M6 har bara tre lysdioder.

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

FPGA:n kör LT8618SX-sekvensen (`../research/LT8618SX_INIT.md`) efter uppstart. Osäkert och därför lätt att ändra: I2C-adressen (`lt8618_ctrl` parameter `DEV`, antagen 39h = 72h i 8-bitsform), klockflanken (`CLK_INVERT` i toppen, eller LT-register 82:4F) och om LT:n behöver radnummer/CRC efter EAV (finns inte). Lysdioder: LED0 hjärtslag, LED1 BT.656-rader, LED2 SDRAM klart, LED3 halvbild visas, LED4 LT8618SX-sekvensen klar, LED5 LT8618SX-fel (inget I2C-svar eller TX-PLL olåst).

Var hittar man en LT8618SX att koppla till? Ingen färdig breakout är verifierad än (se `../design/REV_A_KONCEPT.md`). Det här bygget är förberett för den dagen — eller för rev A, där samma gateware används.

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

Används för egenstörningsmätningen i `../design/PUCK_2027_KONCEPT.md` ("Inbyggt mätinstrument"): stillastående kamera, VTX på fast avstånd, jämför värdena med HDMI på/av, kanal F4 mot andra kanaler, mottagarna på olika avstånd och med/utan skärmburk. Måttet beror också på bildinnehållet, så bara jämförelser med samma motiv betyder något.

**OSD i videon** (`osd_overlay.v`): samma fyra rader som OLED:n, 3× förstorade, vita på en halvmörk platta längst ned i 4:3-fönstret (x 176, y 576 i 720p). Syns i 5 s efter varje knapptryck och hela tiden på mätarsidan, så att menyn går att använda med XR-glasögonen på. Pixelexakt testad (`sim/test_osd.py`).

**Mätlogg över USB** (`uart_tx.v`, PIN69 → kortets BL616 USB-UART, 115200 8N1): en rad per mätfönster (≈ 15/s):
```
S 012345 002345 040 034 025 F4 5800 MIX
```
snö A, snö B (`------` = inga rader), % av mixerbesluten från A / B / blandning, kanal, MHz, läge. På datorn:
```
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_pa --seconds 30 --out emi.csv
python gateware/tools/snowlog.py /dev/ttyUSB1 --label hdmi_av --seconds 30 --out emi.csv
python gateware/tools/snowlog.py --summary emi.csv
```
(BL616 visar två serieportar; UART:en är oftast den andra.) Sammanfattningen visar medianen per etikett, alltså en mätserie per testvillkor.

Ingen RSSI ännu: RX5808:s RSSI är analog och Tang Nano 20K saknar ADC. Det kommer med en extern I2C-ADC eller med GW5A-25:s inbyggda ADC.

## Låglatensläge (`LOW` i menyn, `LOW_LATENCY=1` i M4)

Utan bildbuffert. Mixerns rader skrivs direkt till en ringbuffert på 16 rader i FPGA:ns block-RAM, och 720p-utgången låses till ingångens fält (`genlock_timing.v`). Varje utbild startar när rad 1 i ett nytt fält har kommit, och raderna läses medan de kommer in.

| | `BUF` (SDRAM-trippelbuffert) | `LOW` (ringbuffert, genlock) |
|---|---|---|
| Fördröjning ingång → HDMI | ett helt fält plus väntan på nästa utbild: ca 17–50 ms, varierande | ca 0,1 ms överst i bilden, ca 0,8 ms nederst, konstant |
| Utgång vid NTSC | 720p60,00 (fält upprepas ibland) | 720p 59,94 Hz (bilder om 750/751 rader) |
| Utgång vid PAL | 720p60 (var 5:e fält upprepas, ryckigt) | 720p50 (CEA-861-radlängd 1980) |
| Ingen signal | grå ruta | grå ruta, utgången frigår |
| Tappad rad | syns inte (hela fält visas) | raden visar vad som fanns i platsen 16 rader tidigare |

**Varför det fungerar:** utgången skannar varje källrad långsammare (3 × 22,2 µs) än ingången levererar den (63,6 µs). Läsaren kan alltså aldrig gå om skrivaren, och skrivaren ligger högst cirka 13 rader före (därav 16 platser). Upplösningen är densamma i båda lägena, så läget går att byta medan det kör. Vid byte mellan PAL och NTSC i `LOW` ändras bildfrekvensen, och skärmen synkar om (1–2 s).

**Risk att prova på hårdvara:** en del skärmar gillar inte att antalet rader per bild växlar (750/751). CVBS2HDMI kör samma knep (524/525 rader) utan problem på vanliga skärmar. Prova på Moneagle-monitorn, XR-glasögonen och en TV innan läget blir standard. Testat i simulering: `sim/test_m2.py::m2_low_latency` (låsning, bildperiod = fältperiod, pixlar mot modell, uppmätt fördröjning).

## Apicula-fällor (från otanl/CVBS2HDMI, kontrollerade 2026-10-04)

- **Signerade jämförelser** har felkompilerats av Apicula (seed-beroende). `tmds_encoder.v` och `ycbcr2rgb.v` är omskrivna utan signerad aritmetik och bitexakt kontrollerade mot de gamla versionerna (alla 16,7 miljoner YCbCr-värden, plus en lång slumpsekvens genom TMDS-kodaren). Ingen annan modul använder `signed`.
- **Insignaler i samma I/O-bank som HDMI** (bank 5: stift 26–31, där dekoder A:s buss ligger) packades i en nyare Apicula som LVDS-mottagare. **Vår Apicula 0.32 gör inte det.** `tools/test_lvds_bank_inputs.py` bygger två små designer, med och utan LVDS-utgång i banken, och kräver att insignalernas IOB-fuses är identiska. En riktig LVDS-mottagare som negativ kontroll visar att testet ser skillnaden. Kör testet efter varje Apicula-uppgradering. Om det fallerar: packa via en omslagare som CVBS2HDMI:s `scripts/gowin_pack_io.py` (MIT).
- Inga `DRIVE=`/`BANK_VCCIO=` på LVDS25-stift (gäller redan våra cst-filer).

## M3 — uppstartsprob

`top/m3_probe.v`, samma stift som M4/M6. Visar en gång i sekunden, per dekoder: SCLK-frekvens, vilka databitar som växlar, radlängder, rader och fält per sekund, synkfel, I2C-svar och statusregister. Lysdioder: LED0 hjärtslag 1 Hz, LED1 SCLK från A, LED2 SCLK från B. Pull-test med `PULL=UP` eller `PULL=DOWN gateware/build.sh m3_probe`. Allt om koppling och tolkning finns i [BRINGUP.md](BRINGUP.md).

## Formella bevis

`formal/run.sh` (cirka 15 s, ingår i testsviten via `tools/test_formal.py`) bevisar med k-induktion i yosys, utan extern lösare:

| Modul | Bevisat | Negativ kontroll |
|---|---|---|
| `async_fifo.v` (djup 4 och 8) | med två fria klockor och fria in-signaler: ingen överflödning eller underflödning, varje sidas bild av den andra pekaren är konservativ, Gray-pekarna stämmer och rör sig ett steg i taget, och ett ord kommer ut oförändrat | en FIFO som aldrig är full flödar över; en som aldrig är tom flödar under |
| `genlock_timing.v` | med fria lock/trig/h_alt: räknarna håller sig inom gränserna, och varje bild slutar inom V_TOTAL + MAX_WAIT rader | utan väntegränsen kan en bild stå still |

Egenskaperna står i modulerna inom `ifdef FORMAL`. Klockdomänshandskakningarna i `fb_backend.v` är inte bevisade än.
