# Gateware (Tang Nano 20K, Verilog)

> Del av [OpenVRX](https://github.com/LAP87/OpenVRX). Forskning och utvecklingsplan finns i navet; kortdesignen finns i [OpenVRX-Puck](https://github.com/LAP87/OpenVRX-Puck).

Plan: [GATEWARE_PLAN.md](https://github.com/LAP87/OpenVRX/blob/main/docs/GATEWARE_PLAN.md). Licens: CERN-OHL-S-2.0, se `LICENSE` i repots rot.

## Status 2026-10-05

| Milstolpe | Toppmodul | Byggd | Verifierad |
|---|---|---|---|
| M0 — testbild 720p60 på kortets HDMI | `top/m0_testpattern.v` | ✔ `build/m0_testpattern.fs` (792 LUT, 3 %; pixel 138,81 MHz mot krav 75) | Simulering av TMDS och tidsbas |
| M1 — Moneagles TVP5150AM1 → HDMI (luma, 360×240, 720p60), inbäddad BT.656-synk | `top/m1_moneagle_view.v` | ✔ `build/m1_moneagle_view.fs` (822 LUT, 44/46 BSRAM) | Hela ingångsvägen mot facit |
| M1s — samma, separata synksignaler (HSYNC/VSYNC/AVID) | `top/m1s_moneagle_view_sync.v` | ✔ `build/m1s_moneagle_view_sync.fs` (1 052 LUT, 44/46 BSRAM) | Båda polariteter och bytefaser |
| **M2 — full upplösning i färg via SDRAM, trippelbuffert** | `top/m2_moneagle_color.v` (kärna `rtl/m2_core.v`) | ✔ `build/m2_moneagle_color.fs` (3 154 LUT 15 %, 16 BSRAM, 2 PLL; SDRAM 127 MHz mot 64,8) | Tre klockdomäner + SDRAM-modell: SDRAM-innehåll och RGB-pixlar mot modell |
| M2s — som M2 men separata synksignaler | `top/m2s_moneagle_color_sync.v` (`m2_core` med `DISCRETE_SYNC=1`) | ✔ `build/m2s_moneagle_color_sync.fs` (3 387 LUT 16 %, 4 BSRAM) | Mottagaren testad i M1s; kombinationen bara syntes/PnR |
| **M3 — uppstartsprob** för M4/M6-kopplingen (ingen bild; en rad per dekoder och sekund över USB) | `top/m3_probe.v` | ✔ `build/m3_probe.fs` (2 379 LUT 11 %; långsammaste domän 129,23 MHz mot krav 75) | Rapportraderna mot en frisk och en felkopplad dekoder (`sim/test_probe.py`) |
| **M4 — två egna TVP5150-moduler + radvis mixer** | `top/m4_dual_mix.v` | ✔ `build/m4_dual_mix.fs` (7 782 LUT 37 %, 24 BSRAM; SDRAM 88,05 MHz mot 64,8, pixel 109,13 MHz mot 74,25) | Mixern bitexakt mot facit (två klockor, snö, trasig synk, död kanal, olåst dekoder); I2C mot slavmodeller |
| **M5 alt. C — 1080p60 via LT8618SX** | Ingår inte i denna checkout | Historiskt privat bygge, inte återskapbart här | BT.1120/backend testas här; LT8618SX-uppstart och XR kräver separat acceptans |
| **M6 — puckprototyp steg 1** (M4 + RX5808-styrning + OLED-meny + OSD i videon + mätlogg) | `top/m6_puck_proto.v` | ✔ `build/m6_puck_proto.fs` (11 000 LUT 53 %, 24 BSRAM; SDRAM 98,73 MHz mot 64,8, pixel 128,12 MHz mot 74,25) | Meny, SPI, OLED, snö-mätare, OSD och UART-logg mot modeller (`sim/test_puck_ui.py`, `sim/test_snow_stats.py`); M4-delen som ovan |

**Inget är provat på riktig hårdvara**. M0/M3/M4/M6 är byggda 2026-10-05; siffrorna är slutresultat efter routning. M4/M6 har klockkrav i `boards/<top>.sdc` (64,8/74,25/27 MHz); M0/M3 använder det konservativa standardkravet 75 MHz. Övriga siffror är äldre byggen från 2026-10-04 och avser tidigare källversioner. BSRAM-ökningen (+12) är låglatenslägets ringbuffert på 16 rader. Intern timing ersätter inte SDRAM-DQ-, kabel- eller skärmprov.

Hela simuleringssviten: `.venv/bin/python -m pytest -q tests/latency mixer gateware/model gateware/sim gateware/tools` (78 test). Kör den och PnR sekventiellt.

## Åtgärdat och kvar att verifiera

2026-10-05: mixern väntar högst 4096 systemcykler på en saknad motpart och
avvisar dåliga, ofullständiga eller redan visade rader på alla vägar. Fältepocher
hindrar sena rader från föregående fält att skapa nya fältstarter. En återkommande
kanal kan återställa epochrelationen vid färska matchande rader. `sim/test_mixer.py`
provar 20–25 blankrader, 2/5/7 raders eftersläpning, tvingat A/B, flera missade
fält och konstant F. `sim/test_mix_chan.py` provar helradsförlust med negativa
kontroller. Hälsotidsgränsen är cirka 4,05 ms vid 64,8 MHz. En rad som fångats
under dekoderfel behåller felstatusen när dekodern återhämtar sig; en ny
felstatus spärrar även redan köade friska rader.

Modellen beskriver radbeslut, inte varje CDC-/emissionscykel. Parningstiden cirka
63,2 µs förutsätter att utgången kan ta emot raden. Två dekodrars verkliga bildfas
och blandningsnytta är inte mätta. SDRAM:s I/O-timing, buffertägarskap mellan
klockdomäner, genlocks minsta bildperiod och TVP/I2C-återhämtning är fortfarande
öppna punkter. `LOW` och `BUF` är utvecklingslägen; de listade testfallen är
inte en acceptans av hela mottagaren eller dess glas-till-glaslatens.

`tools/board_contract.py` kräver direkt RESETB/SPI-funktion på LED3/4/5 i
M3/M4/M6. Pucks schemascript använder samma kontroll och stoppar export mot en
äldre Core utan detta kontrakt. Det är en källkodskontroll; signalintegritet,
modulmatning och faktisk kortrevision måste dessutom kontrolleras på bänken.

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
| `bt1120_tx.v`, `clocks_1080p.v` | 16-bitars BT.1120 med inbäddad synk och 148,5 MHz-PLL. LT8618SX-styrningen och M5-toppen ingår inte. | `sim/test_bt1120.py`, `sim/test_m5c.py` (BT.1120-utmatning från backend, ingen LT8618SX) |
| `rx5808_spi.v`, `vtx_channels.vh` (genererad), `ssd1306_text.v`, `font5x7.vh` (genererad), `puck_ui.v`, `snow_stats.v`, `bin2bcd.v`, `osd_overlay.v`, `uart_tx.v` | Puck: RX5808-kanalstyrning (SPI), 48 kanaler med svensk-bandflagga, OLED-text 4×21 tecken utan bildbuffert, meny med två knappar, delad I2C-buss med `tvp_ctrl` (hold/active) | `sim/test_puck_ui.py`: SPI-ord bit för bit mot `model/vtx_channels.py`, skärmbilden (huvud- och mätarsida) avläst ur pixlarna via teckensnittet, inga busskollisioner; `sim/test_snow_stats.py`, `sim/test_osd.py`; UART-loggen och OSD-visningen i `sim/test_puck_ui.py`; `tools/test_snowlog.py` |
| `i2c_master.v`, `tvp_ctrl.v` | I2C; uppstart av egna TVP5150AM1 (reset, 00h/03h/0Dh) och pollning av status 88h/89h | `sim/test_tvp_ctrl.py` mot I2C-slavmodeller (två adresser, delad adress med separata SDA, saknad dekoder) |

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

**Innan något kopplas:** öppna Moneagle, bekräfta TVP5150AM1 och mät **TVP-stift 10 (IO_DVDD)**. Kopplingen nedan förutsätter 3,3 V. AM1 kräver IO_DVDD 3,0–3,6 V (SLES209E 4.2); vid annan spänning ska chipvariant och modul kontrolleras innan den ansluts.

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

Källor: TVP-stift ur TI SLES209E; kortstift ur [Sipeeds scheman](https://wiki.sipeed.com/hardware/en/tang/tang-nano-20k/nano-20k.html), v3921 sida 2 (stiftpositioner; M3/M4/M6 kräver rev 3923); klockstiftens funktion ur apiculas chipdb (GW2AR-18C, QFN88). **Rättat 2026-10-02:** SCLK låg tidigare på PIN25, som inte är en klockingång (GCLKT_4 är PIN35 och används av HDMI). Klockingångar på stiftlisterna: PIN77 (J6-5, GCLKT_1), PIN80 (J5-4, GCLKT_0), PIN76/PIN79 (komplementstift). TVP:n lägger ut data så att mottagaren ska sampla på stigande flank (Linux-drivrutinen `tvp5150.c`: `V4L2_MBUS_PCLK_SAMPLE_RISING`; SLES209E: utfördröjning 3–8 ns, hålltid 2 ns) — det gör vår logik. Tunn lackad tråd, så kort som möjligt, gärna 47–100 Ω i serie nära TVP:n, gemensam jord. Moneagle och Tang Nano matas var för sig men delar jord.

Lysdioder (tänd = sant): LED0 hjärtslag, LED1 rader kommer in, LED2 fält 1 sett, LED3 synkord har rättats, LED4 trasiga synkord sett.

**Felsökning:** inga rader (LED1 släckt) men SCLK finns → Moneagles SoC har troligen ställt TVP:n på separata synksignaler i stället för inbäddad BT.656 (register 0Dh). Använd då **M1s** nedan. Bilden kan ha rivningar (ingen genlock). M2 använder SDRAM-fältbuffert, men dess buffertägarskap behöver ytterligare verifiering.

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
                 3 halvbildsbuffertar; publicerar färdig halvbild; ägarskap mellan klockdomäner granskas
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

`top/m4_dual_mix.v` → `build/m4_dual_mix.fs`. Två TVP5150AM1-moduler, var och en matad med CVBS från en egen 5,8 GHz-mottagare på samma kanal. FPGA:n startar dekodrarna via I2C; mixern väljer per rad den renaste kanalen eller blandar. Detaljer och begränsningar: [navets gateware-plan](https://github.com/LAP87/OpenVRX/blob/main/docs/GATEWARE_PLAN.md), "M4-implementering", och statusavsnittet ovan.

| Signal | Dekoder A | Dekoder B |
|---|---|---|
| SCLK | PIN77 (J6-5, GCLKT_1) | PIN80 (J5-4, GCLKT_0) |
| YOUT0–7 | PIN27, 28, 26, 29, 30, 31, 73, 74 (J6-8, 9, 11, 12, 13, 14, 1, 2) | PIN76, 42, 41, 48, 49, 86, 79, 72 (J5-3, 5, 6, 10, 12, 13, 14, 17) |
| I2C SDA | PIN85 (J6-4) | PIN51 (J5-9) |
| I2C SCL | PIN75 (J6-3), gemensam | |
| RESETB | PIN18 (J6-18, lysdiod 3), gemensam — den röda modulen saknar reset-stift: löd en tråd till TVP stift 8. Inte PIN25 (HDMI-banken, CEC) | |
| RX5808 SPI | CLK PIN71 (J5-18), DATA PIN19 (J6-17), SEL PIN20 (J6-16), som M3/M6 | |
| Jord | J6-20 / J5-2, J5-15 | |

Två likadana moduler svarar på samma I2C-adress (B8h), därför egen SDA per dekoder. Kontrollera modulernas matning och IO-nivå (3,3 V) innan inkoppling. Stift 52–56 (konfigurationsstift) används inte.

Lysdioder (tänd = sant): LED0 hjärtslag, LED1 dekoder A låst, LED2 dekoder B låst. Lysdiodsstiften 3–5 bär RESETB och RX5808 DATA/SEL. M4 håller båda mottagarna på F4 5800 MHz (`rtl/rx_tune.v`). Koppling och felsökning: [BRINGUP.md](BRINGUP.md).

## M5 alt. C — Moneagle → 1080p60 → LT8618SX → XR-glasögon

> **Ingår inte i det här repot:** toppmodulen `m5c_moneagle_1080p.v`, `lt8618_ctrl.v`, `lt8618_rom.vh`, `model/lt8618_seq.py` och deras test. LT8618SX-sekvensen är härledd ur en leverantörsdrivrutin vars källfil är märkt konfidentiell, så den publiceras inte förrän ursprunget är utrett. BT.1120-utgången (`bt1120_tx.v`, `sim/test_m5c.py`) ingår.

Målet är 1080p60 med ett 1440×1080-fönster för den analoga bilden. `sim/test_m5c.py`
kontrollerar backendens BT.1120-utmatning med förkortad vertikaltiming, utan
HDMI-sändare eller XR-skärm. Ett historiskt privat bygge ger inte stöd för
en viss skärm eller en publicerbar LT8618SX-initsekvens.

Det gamla privata spåret använde PIN52/53, som är SSPI-konfigurationsstift
och HDMI-DDC. Innan detta spår kan provas behövs en ny stiftplan, klarlagt
ursprung för initsekvensen och en verifierad mottagarmodul/skärm.

## M6 — puckprototyp steg 1 (M4 + meny, RX5808, OLED)

> Koppling, uppstartsordning och felsökning steg för steg: [BRINGUP.md](BRINGUP.md). Ändrat 2026-10-04: SPI DATA och SEL flyttade från PIN53/52 (konfigurationsstift och HDMI-DDC på kortet) till lysdiodsstiften 19/20. Ändrat 2026-10-05: RESETB flyttad från PIN25 (HDMI-banken, CEC; Core issue #6) till lysdiodsstift 18 (J6-18). Lysdioderna i M3/M4/M6 är nu tre: LED0 hjärtslag, LED1/LED2 dekoder A/B låst (M3: SCLK A/B).

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
OK byter fält (band → kanal → läge → latens → sida), NEXT stegar värdet. `BUF`/`LOW` är videovägen: `BUF` går via SDRAM-bildbufferten, `LOW` är låglatensläget (se nedan). Bandbyte och kanalbyte programmerar om båda mottagarna direkt. Läge MIX låter mixern välja; A eller B tvingar en mottagare. Kanaler utanför 5725–5875 MHz visar `!OUTSIDE SE BAND`. Start: F4 5800 MHz.

**Mätarsidan ("snö-mätare")**: OK till femte fältet (markören hamnar på rad 4), NEXT växlar sida.
```
>METER   F4  5800
A  12345 ########
B   2345 ######
 USE A 40 B 34 M 25
```
Talen är medel-HF-energin per bildrad (summan |Y[n]−Y[n−1]|, samma mått som mixern väljer på) över 1 024 rader (≈ 65 ms) per mottagare. Stapeln är logaritmisk: ett block per fördubbling över 32. `  ----` betyder att inga rader kommer från den mottagaren. USE = andel av de senaste 1 024 mixerbesluten som visade A, B eller en blandning. Talen räknas om i `snow_stats.v` (mixerns klockdomän) och visas via en sekventiell decimalomvandlare (`bin2bcd.v`).

Används för egenstörningsmätningen i [Pucks koncept](https://github.com/LAP87/OpenVRX-Puck/blob/main/design/PUCK_2027_KONCEPT.md) ("Inbyggt mätinstrument"): stillastående kamera, VTX på fast avstånd, jämför värdena med HDMI på/av, kanal F4 mot andra kanaler, mottagarna på olika avstånd och med/utan skärmburk. Måttet beror också på bildinnehållet, så bara jämförelser med samma motiv betyder något.

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
| Intern fördröjning efter dekoderns radleverans, simulerad | ett helt fält plus väntan på nästa utbild: ca 17–50 ms, varierande | ca 0,1 ms överst i bilden, ca 0,8 ms nederst, konstant |
| Utgång vid NTSC | 720p60,00 (fält upprepas ibland) | 720p 59,94 Hz (bilder om 750/751 rader) |
| Utgång vid PAL | 720p60 (var 5:e fält upprepas, ryckigt) | 720p50 (CEA-861-radlängd 1980) |
| Ingen signal | grå ruta | grå ruta, utgången frigår |
| Tappad rad | syns inte (hela fält visas) | raden visar vad som fanns i platsen 16 rader tidigare |

**Den simulerade modellen:** utgången skannar varje källrad långsammare (3 × 22,2 µs) än ingången levererar den (63,6 µs). Vid dessa simulerade friska perioder går läsaren inte om skrivaren, och skrivaren ligger högst cirka 13 rader före (därav 16 platser). Upplösningen är densamma i båda lägena, så läget går att byta medan det kör. Vid byte mellan PAL och NTSC i `LOW` ändras bildfrekvensen; skärmens återlåsningstid är inte mätt.

**Risk att prova på hårdvara:** en del skärmar gillar inte att antalet rader per bild växlar (750/751). CVBS2HDMI kör samma knep (524/525 rader) utan problem på vanliga skärmar. Prova på HDMI-skärm/TV och den senare valda XR-sinken innan läget blir standard. Moneagle är analog referensmonitor. Testat i simulering: `sim/test_m2.py::m2_low_latency` (låsning, bildperiod = fältperiod, pixlar mot modell, uppmätt fördröjning).

## Apicula-fällor (från otanl/CVBS2HDMI, kontrollerade 2026-10-04)

- **Signerade jämförelser** har felkompilerats av Apicula (seed-beroende). `tmds_encoder.v` och `ycbcr2rgb.v` är omskrivna utan signerad aritmetik och bitexakt kontrollerade mot de gamla versionerna (alla 16,7 miljoner YCbCr-värden, plus en lång slumpsekvens genom TMDS-kodaren). Ingen annan modul använder `signed`.
- **Insignaler i samma I/O-bank som HDMI** (bank 5: stift 26–31, där dekoder A:s buss ligger) packades i en nyare Apicula som LVDS-mottagare. **Vår Apicula 0.32 gör inte det.** `tools/test_lvds_bank_inputs.py` bygger två små designer, med och utan LVDS-utgång i banken, och kräver att insignalernas IOB-fuses är identiska. En riktig LVDS-mottagare som negativ kontroll visar att testet ser skillnaden. Kör testet efter varje Apicula-uppgradering. Om det fallerar: packa via en omslagare som CVBS2HDMI:s `scripts/gowin_pack_io.py` (MIT).
- Inga `DRIVE=`/`BANK_VCCIO=` på LVDS25-stift (gäller redan våra cst-filer).

## M3 — uppstartsprob

`top/m3_probe.v`, samma stift som M4/M6. Visar en gång i sekunden, per dekoder: SCLK-frekvens, vilka databitar som växlar, radlängder, rader och fält per sekund, synkfel, I2C-svar och statusregister. Pull-test med `PULL=UP` eller `PULL=DOWN gateware/build.sh m3_probe`. Allt om koppling och tolkning finns i [BRINGUP.md](BRINGUP.md).

## Formella bevis

`formal/run.sh` (cirka 15 s, ingår i testsviten via `tools/test_formal.py`) bevisar med k-induktion i yosys, utan extern lösare:

| Modul | Bevisat | Negativ kontroll |
|---|---|---|
| `async_fifo.v` (djup 4 och 8) | med två fria klockor och fria in-signaler: ingen överflödning eller underflödning, varje sidas bild av den andra pekaren är konservativ, Gray-pekarna stämmer och rör sig ett steg i taget, och ett ord kommer ut oförändrat | en FIFO som aldrig är full flödar över; en som aldrig är tom flödar under |
| `genlock_timing.v` | med fria lock/trig/h_alt: räknarna håller sig inom gränserna, och varje bild slutar inom V_TOTAL + MAX_WAIT rader | utan väntegränsen kan en bild stå still |

Egenskaperna står i modulerna inom `ifdef FORMAL`. Klockdomänshandskakningarna i `fb_backend.v` är inte bevisade än.
