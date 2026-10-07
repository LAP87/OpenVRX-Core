# Uppstart på bänken: Tang Nano 20K + två TVP5150-moduler + två RX5808

Ordningen är M0 → M3 → M4 → M6. Varje steg bevisar en sak innan nästa läggs på. Allt nedan gäller stiftplanen i `boards/m4_dual_mix.cst` (samma i M3 och M6).

## 0. Innan något kopplas in

**Kortrevision.** Läs revisionen på Tang-kortets undersida (t.ex. "3923"). Stiftplanen förutsätter rev 3923 och **fungerar inte på rev 3921**. Där går stift 75, som är SCL, till BL616-kretsens BOOT-strapp med 10 kΩ till jord (Sipeeds 3921-schema rev 1.22 och 1.30, bladet USB_JTAG: SPI_DIR är samma nät som BL616_BOOT, R22). En pull-up på SCL håller BOOT hög när kortet får ström. BL616 startar då i sitt programmeringsläge, och kortet har varken USB-JTAG eller USB-UART, så inte heller M3-proben kommer i gång. Detta är läst ur schemat, inte provat. På 3921 går dessutom stift 76 och 86 till BL616 (SPI_DAT och SPI_CS). Rev 3850 är inte kontrollerad.

**Knapparna vid start.** S1 och S2 sitter på FPGA:ns MODE0 och MODE1 (stift 88 och 87, Sipeeds schema). Håll ingen av dem intryckt när kortet får ström: då väljs ett annat konfigurationsläge och bitströmmen laddas inte från flash. Inte provat.

**TVP5150-modulernas spänning.** Mät stift 10 (IO_DVDD) på TVP-kretsen när modulen är strömsatt. Visar den 3,3 V går datasignalerna direkt till Tang-kortet. Visar den 1,8 V läser Tang-kortet dem inte säkert, och då behövs nivåomvandlare (TXS0108E, två per modul). Mata modulen enligt dess egen märkning.

**Reset.** Den röda modulen saknar resetstift. Löd en tråd från TVP-kretsens stift 8 (RESETB) till J6-18, eller låt den sitta på modulens egen reset om den har en sådan krets.

## 1. Koppling

**Dekoder A → J6**

| TVP-signal | Tang | | TVP-signal | Tang |
|---|---|---|---|---|
| SCLK | J6-5 (PIN77) | | YOUT4 | J6-13 (PIN30) |
| YOUT0 | J6-8 (PIN27) | | YOUT5 | J6-14 (PIN31) |
| YOUT1 | J6-9 (PIN28) | | YOUT6 | J6-1 (PIN73) |
| YOUT2 | J6-11 (PIN26) | | YOUT7 | J6-2 (PIN74) |
| YOUT3 | J6-12 (PIN29) | | SDA | J6-4 (PIN85) |

**Dekoder B → J5**

| TVP-signal | Tang | | TVP-signal | Tang |
|---|---|---|---|---|
| SCLK | J5-4 (PIN80) | | YOUT4 | J5-12 (PIN49) |
| YOUT0 | J5-3 (PIN76) | | YOUT5 | J5-13 (PIN86) |
| YOUT1 | J5-5 (PIN42) | | YOUT6 | J5-14 (PIN79) |
| YOUT2 | J5-6 (PIN41) | | YOUT7 | J5-17 (PIN72) |
| YOUT3 | J5-10 (PIN48) | | SDA | J5-9 (PIN51) |

**Gemensamt:** SCL till båda modulerna och OLED:n på J6-3 (PIN75). RESETB till båda på J6-18 (PIN18, lysdiod 3). GND till GND (J6-20, J5-2). Pull-up 2,2–4,7 kΩ till 3,3 V på SCL och båda SDA, om modulerna inte redan har det.

J6-10 (PIN25) används inte. En utgång där ligger i samma bank som HDMI-klockparet och ändrar hur Apicula packar det (avsnitt 5).

Båda modulerna svarar på samma I2C-adress, därför har varje modul sin egen SDA.

**RX5808 (båda parallellt, efter SPI-moden; samma koppling i M3, M4 och M6):**

| RX5808 | Tang |
|---|---|
| CH3 (SPI CLK) | J5-18 (PIN71) |
| CH1 (SPI DATA) | J6-17 (PIN19, lysdiod 4) |
| CH2 (SEL) | J6-16 (PIN20, lysdiod 5) |
| 5 V, GND | separat 5 V, gemensam GND |
| Video ut | TVP-modulens videoingång (A respektive B) |

RESETB, DATA och SEL ligger på lysdiodsstift, eftersom alla vanliga stift på stiftlisterna används av dekodrarna. Stift 52/53 är konfigurationsstift och dessutom HDMI-DDC och fungerar inte. Lysdiod 3 blinkar till vid start (resetpulsen, 2 ms). Lysdiod 4 och 5 blinkar till när en kanal skrivs (0,1 ms) och är släckta däremellan.

**Lysdioder** (tre är kvar som lysdioder):

| Bitström | Lysdiod 0 | Lysdiod 1 | Lysdiod 2 |
|---|---|---|---|
| M3 | hjärtslag 1 Hz | SCLK från A | SCLK från B |
| M4, M6 | hjärtslag: 1 Hz när båda dekodrarna är låsta, 4 Hz annars | rader från A | rader från B |

**OLED (M6):** SCL J6-3, SDA J6-4 (samma buss som dekoder A), 3,3 V, GND.

**Sändaren LST-S4:** ställ den på NTSC (blå lysdiod enligt manualen) och band F, kanal 4 (5800 MHz). M3 och M4 ställer mottagarna på F4. M6 ställer dem på menyns kanal, som är F4 vid start.

**När kanalen skrivs** (`rtl/rx5808_tune.v`): 0,5 s efter start, och sedan varannan sekund så länge ingen dekoder är låst. En mottagare som får ström efter FPGA:n, eller tappar den, står på sin startkanal (5865 MHz enligt RTC6715-databladet) och ställs om inom 2 s. Så länge en dekoder är låst skrivs kanalen inte om, eftersom det inte är provat om en omskrivning stör bilden. I M6 skrivs kanalen dessutom direkt vid varje band- eller kanalbyte.

## 2. Stegen

| Steg | Bitström | Kopplat | Klart när |
|---|---|---|---|
| M0 | `m0_testpattern` | bara Tang + HDMI | testbilden syns på skärmen |
| M3 | `m3_probe` | allt ovan utom OLED | proben visar friska rader för båda dekodrarna (nedan) |
| M4 | `m4_dual_mix` | samma | lysdiod 0 går från 4 Hz till 1 Hz (båda dekodrarna låsta); kamerabilden syns på HDMI; byte mellan mottagarna när en antenn tas bort |
| M6 | `m6_puck_proto` | + OLED, knappar | menyn på OLED och OSD, kanalbyte fungerar, mätloggen kommer över USB |

```bash
gateware/build.sh m3_probe
openFPGALoader -b tangnano20k gateware/build/m3_probe.fs
```

Loggen läses från kortets andra USB-serieport (BL616 visar två; UART:en är oftast den andra):

```bash
stty -F /dev/ttyUSB1 115200 raw -echo && cat /dev/ttyUSB1
```

### 2.1 Minnestest före M4

M4 är första steget som använder SDRAM-minnet, och läsningen där är inte provad på hårdvara (README, "M2 — så fungerar det"). Kör därför `m2a_memtest` först. Bara Tang-kortet och USB-kabeln behövs, så det går att göra direkt efter M0.

```bash
gateware/build.sh m2a_memtest
openFPGALoader -b tangnano20k gateware/build/m2a_memtest.fs
```

Raderna kommer på samma serieport som M3-probens. Klart när raden `rs=5` visar `err=00000000` varv efter varv, och `err=00000001` medan S2 hålls intryckt. Visar en annan rad nollorna, eller ingen, står det i README ("M2a — minnestest av SDRAM") hur fasen och läspunkten byts. Bygg sedan M4 med den fas som gav ren rad.

## 3. Vad M3-proben ska visa

En rad per dekoder och sekund. Frisk NTSC:

```
A sclk 27000064 tog FF hi FF len 1716-1716 ln 14565 fld 060 xe 0000 i2c OK st 000E ri 00
```

| Fält | Friskt | Betyder |
|---|---|---|
| `sclk` | 27 000 000 ± några hundra | dekoderns klocka i Hz |
| `tog` | `FF` | vilka av YOUT7..0 som växlat |
| `hi` | `FF` | vilka som någon gång varit 1 |
| `len` | `1716-1716` (PAL `1728-1728`) | kortaste och längsta raden i byte |
| `ln` | ca 14 500 | aktiva rader per sekund |
| `fld` | `060` (PAL `050`) | fältbyten per sekund |
| `xe` | `0000` | synkord med bitfel som inte gick att rätta |
| `i2c` | `OK` | dekodern svarade på den senaste I2C-frågan (`NA`: inget svar, `--`: uppstarten är inte klar) |
| `st` | `000E` eller `100E` (PAL `006E`, `106E`, `206E`, `306E`) | statusregister 89h (två första siffrorna) och 88h (två sista), se nedan. `----`: ingen giltig status, för att senaste pollrundan inte fick svar på alla tre läsningarna (88h, 89h, 03h) eller för att dekodern hittades återställd och inte har lästs hel sedan dess |
| `ri` | `00` | antal gånger dekodern har hittats återställd och startats om (hexadecimalt, stannar på `FF`) |

**Statusregistren** (TI SLES209E avsnitt 3.21.49 och 3.21.50). De två sista siffrorna i `st` är register 88h:

| Bit i 88h | Hex | Betyder |
|---|---|---|
| 1, 2, 3 | `02`, `04`, `08` | H-lås, V-lås, färglås. Alla tre ger `E` som sista siffra |
| 5 | `20` | fältfrekvens: 0 = 60 Hz, 1 = 50 Hz |
| 6 | `40` | färgen växlar radvis (PAL) |
| 0, 4, 7 | `01`, `10`, `80` | får variera på en frisk signal: VCR-läge, lås tappat sedan förra läsningen, toppvitt |

Frisk NTSC läser alltså `0E` och frisk PAL `6E`. De två första siffrorna är register 89h. Bit 6 (`40`) betyder svag signal och ska vara 0. Bit 4 (`10`) följer fältet och bit 5 (`20`) är PAL-växeln, så `00` och `10` är lika friska, för PAL också `20` och `30`. `sim/tvp_status.py` har samma tabell som kod, och `sim/test_probe.py` kontrollerar exemplet ovan mot den.

`ri` räknas upp när register 03h inte läser tillbaka 0Dh. Det händer när dekodern har återställts av en spänningsdipp eller en störning på RESETB. Då är dess utgångar avstängda, och FPGA:n skriver uppstartsregistren igen utan att röra den andra dekodern. Samma sak sker i M4 och M6, men bara M3 visar räknaren.

Testbänken `sim/test_probe.py` kör samma rapport mot en ren NTSC-bild och mot en dekoder med fasta bitar.

## 4. Felsökning

| Proben visar | Trolig orsak |
|---|---|
| `no SCLK` | SCLK-tråden, modulen saknar ström eller kristall, eller dekodern står i reset |
| `tog` saknar en bit, och biten saknas också i `hi` | den biten är fast låg: avbrott, kortslutning mot GND eller fel stift |
| `tog` saknar en bit, men biten finns i `hi` | fast hög: kortslutning mot 3,3 V eller något annat som driver stiftet |
| `tog 00 hi 00` men `sclk` är rätt | databussen är tyst: 1,8 V-nivåer (se avsnitt 0), eller dekodern startar inte (`i2c`) |
| `len ---------`, `ln 00000` | inga synkord: en databit fel räcker. Titta på `tog`/`hi` först |
| `len` varierar, `xe` stiger | brus eller fel samplingsflank: korta trådarna, jord mellan signalerna |
| `i2c NA` | SDA eller SCL, pull-up saknas, eller fel adress (YOUT7-strappning) |
| `i2c OK` men låsbitarna i `st` är nollor (sista siffran inte `E`) | ingen videosignal: mottagaren, kanalen eller videokabeln |
| `st` börjar på `4`–`7` (t.ex. `400E`) | dekodern flaggar svag signal: antenn, avstånd, eller mottagaren på fel kanal |
| `ri` stiger då och då | dekodern återställs under drift: glapp i matningen eller på RESETB-tråden |
| `ri` går till `FF` på några sekunder, `st ----` | register 03h läser aldrig tillbaka 0Dh: SDA ligger låg hela tiden (kortslutning läses som svar), eller kretsen tar inte emot skrivningarna |

**Pull-testet** hittar glapp utan mätinstrument:

```bash
PULL=UP gateware/build.sh m3_probe      # -> build/m3_probe_pullup.fs
PULL=DOWN gateware/build.sh m3_probe    # -> build/m3_probe_pulldown.fs
```

Ett svagt internt pull-motstånd kan inte flytta ett stift som dekodern verkligen driver. En bit som följer pull-up/pull-down (syns i `hi` och `tog`) drivs alltså inte: glapp eller fel stift. Idén kommer från otanl/CVBS2HDMI.

Två begränsningar:

- Bit 7 får ingen pull. YOUT7 är dekoderns adresstrapp (I2CSEL), som läses vid reset. En pull-up mot modulens eget strappmotstånd kan flytta dekodern till adress BAh, och då visar proben `i2c NA` för en dekoder som är rätt kopplad. Bit 7 kontrolleras i stället med `tog` och `hi` i den vanliga bitströmmen.
- Tre stift har motstånd på kortet som är starkare än FPGA:ns pull (Sipeeds scheman 3921 och 3923): stift 26 (YOUT2 A) har cirka 7 kΩ mot jord genom HDMI hot-plug-delaren, stift 79 (YOUT6 B) cirka 5 kΩ mot jord vid RGB-lysdioden, och stift 49 (YOUT4 B) 27 kΩ mot 3,3 V vid bakbelysningskretsen. En odriven bit där följer kortets motstånd, inte pull-testet.

## 5. Delade stift på Tang Nano 20K (rev 3923)

Stiftplanen använder alla vanliga stift på stiftlisterna. Några av dem är också kopplade till annat på kortet (Sipeeds schema rev 1.3, enligt [openfpga-deck:s kortbeskrivning](https://github.com/Yash-Kamat/openfpga-deck/pull/11)):

| Stift | Vår signal | Också kopplat till | Risk |
|---|---|---|---|
| 26 | YOUT2 A | HDMI hot-plug (spänningsdelare från 5 V) | Låg: dekodern driver mot ett motstånd när en skärm sitter i |
| 18 | RESETB | lysdiod 3 (510 Ω till 3,3 V) | Före konfigurering hålls RESETB inte låg, se nedan |
| 19, 20 | RX5808 DATA, SEL | lysdiod 4 och 5 (510 Ω till 3,3 V) | Ofarligt: båda vilar höga, lysdioderna blinkar till när en kanal skrivs |
| 76 | YOUT0 B | BL616 SPI MOSI | **Kontrollera:** om BL616 driver stiftet blir bit 0 fel. Proben visar det. |
| 86 | YOUT5 B | BL616 SPI DIR | **Kontrollera,** samma |
| 75 | SCL | BL616 SPI MISO | Låg om stiftet är ingång på BL616. Inte kontrollerat: är BL616 SPI-slav driver den MISO, och då visar proben `i2c NA` |
| 88, 87 | S1, S2 (knappar) | FPGA:ns MODE0 och MODE1 (1 kΩ till jord, knappen drar mot 3,3 V) | Intryckt knapp vid start hindrar laddning från flash. Släpp knapparna innan kortet får ström |
| 48, 49 | YOUT3/4 B | LCD DE, LCD-bakbelysningens drivkrets (LP3320 EN) | Bakbelysningsomvandlaren slås av och på i bildtakt utan last. Lyssna och mät snö med M6. |
| 79 | YOUT6 B | WS2812 RGB-lysdiodens data | Ofarligt: RGB-lysdioden blinkar i slumpfärger |
| 80, 85 | SCLK B, SDA A | microSD med 10 kΩ pull-up | Ofarligt |
| 51 | SDA B | ljudförstärkarens SD_MODE | Ofarligt: förstärkaren slås av och på |

**RESETB före konfigurering.** Lysdiod 3 och dess 510 Ω drar stift 18 mot 3,3 V, så RESETB hålls inte låg medan FPGA:n laddas. Enligt SLES209E avsnitt 3.18 är dekoderns utgångar odefinierade tills den har fått en resetpuls. Det skadar inget: dekoderns utgångar går till stift som är ingångar i FPGA:n, och `tvp_ctrl` ger en hel resetpuls (20 ms väntan, 2 ms låg) efter konfigureringen. Efter pulsen är YOUT avstängda tills register 03h skrivs.

**Inga utgångar på stift 25–42.** Bank 4 och 5 bär HDMI-paren. Apicula 0.32 sätter `BANK_VCCIO` för hela banken efter bankens första vanliga utgång, och då packas HDMI-klockparet annorlunda än i M0. RESETB låg tidigare på stift 25 (som dessutom går till HDMI-CEC genom 100 Ω) och är därför flyttad till stift 18. Dekodrarnas databitar på 26–31, 41 och 42 är ingångar och påverkar inte packningen (`tools/test_lvds_bank_inputs.py`).

`tools/test_tmds_bank_outputs.py` vaktar regeln: det läser toppmodulernas portar mot cst-filerna, och det bygger små testdesigner som visar att en utgång på stift 18 lämnar HDMI-parens IOB-fuses orörda medan en på stift 25 eller 41 ändrar dem. Efter ett bygge jämför `tools/tmds_fuses.py` de färdiga bitströmmarnas HDMI-par mot M0:

```bash
gateware/build.sh m0_testpattern && gateware/build.sh m4_dual_mix && gateware/build.sh m6_puck_proto
.venv/bin/python gateware/tools/tmds_fuses.py
```

I byggena från 2026-10-05 har alla fyra HDMI-par i M4 och M6 samma IOB-fuses som i M0. Klockparet har 18 satta; med RESETB på stift 25 var det 16 i M4 och M6. Om en skärm bryr sig om skillnaden är inte provat. Regeln gör att en fungerande M0 säger något om HDMI-utgången i M4 och M6.

Om bit 0 eller 5 på dekoder B visar sig störd (BL616): byt den signalen mot stift 71 och flytta SPI-klockan till lysdiodsstift 17 (J6-15; lysdiod 2 försvinner då). Ändringen görs i `boards/*.cst` och `top/*.v`.
