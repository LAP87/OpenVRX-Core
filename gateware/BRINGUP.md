# Uppstart på bänken: Tang Nano 20K + två TVP5150-moduler + två RX5808

Ordningen är M0 → M3 → M4 → M6. Varje steg bevisar en sak innan nästa läggs på. Allt nedan gäller stiftplanen i `boards/m4_dual_mix.cst` (samma i M3 och M6).

## 0. Innan något kopplas in

**Kortrevision.** Läs revisionen på Tang-kortets undersida (t.ex. "3923"). Stiftplanen förutsätter rev 3923 och **fungerar inte på rev 3921 eller 3850**. Där går stift 75 (vår SCL) till BL616-kretsens BOOT-stift, som har 10 kΩ mot jord. Pull-upen på SCL håller då BOOT hög vid start, BL616 startar i programmeringsläge, och kortet får varken USB-JTAG eller USB-UART. Stift 71–76 och 86 hör dessutom till BL616:s HSPI-buss. (Läst ur Sipeeds 3921-schema, inte provat.) Har du ett sådant kort behövs en annan stiftplan.

**TVP5150-modulernas spänning.** Mät stift 10 (IO_DVDD) på TVP-kretsen när modulen är strömsatt. Visar den 3,3 V går datasignalerna direkt till Tang-kortet. Visar den 1,8 V läser Tang-kortet dem inte säkert, och då behövs nivåomvandlare (TXS0108E, två per modul). Mata modulen enligt dess egen märkning.

**Reset.** Den röda modulen saknar resetstift. Löd en tråd från TVP-kretsens stift 8 (RESETB) till J6-18, eller låt den sitta på modulens egen reset om den har en sådan krets. J6-18 är också lysdiod 3 på Tang-kortet: den lyser medan dekodrarna hålls i reset.

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

**Gemensamt:** SCL till båda modulerna och OLED:n på J6-3 (PIN75). RESETB till båda på J6-18 (PIN18, lysdiod 3). Inte J6-10: stift 25 ligger i HDMI-banken och är skärmens CEC-ledning. GND till GND (J6-20, J5-2). Pull-up 2,2–4,7 kΩ till 3,3 V på SCL och båda SDA, om modulerna inte redan har det.

Båda modulerna svarar på samma I2C-adress, därför har varje modul sin egen SDA.

**RX5808 (båda parallellt, efter SPI-moden):**

| RX5808 | Tang |
|---|---|
| CH3 (SPI CLK) | J5-18 (PIN71) |
| CH1 (SPI DATA) | J6-17 (PIN19, lysdiod 4) |
| CH2 (SEL) | J6-16 (PIN20, lysdiod 5) |
| 5 V, GND | separat 5 V, gemensam GND |
| Video ut | TVP-modulens videoingång (A respektive B) |

DATA och SEL ligger på lysdiodsstift, eftersom alla vanliga stift på stiftlisterna används av dekodrarna. Stift 52/53 är konfigurationsstift och dessutom HDMI-DDC och fungerar inte. Lysdiod 4 och 5 är släckta i vila och blinkar kort när en kanal skrivs.

**OLED (M6):** SCL J6-3, SDA J6-4 (samma buss som dekoder A), 3,3 V, GND.

**Sändaren LST-S4:** ställ den på NTSC (blå lysdiod enligt manualen) och band F, kanal 4 (5800 MHz). M3 och M4 ställer mottagarna på F4 en halv sekund efter start (M6 på menyns kanal) och skriver om kanalen varannan sekund så länge ingen dekoder är låst. Mottagare som slås på efter FPGA:n, eller som tappat matningen, hamnar alltså rätt; från fabrik startar en RX5808 på 5865 MHz.

## 2. Stegen

| Steg | Bitström | Kopplat | Klart när |
|---|---|---|---|
| M0 | `m0_testpattern` | bara Tang + HDMI | testbilden syns på skärmen |
| M3 | `m3_probe` | allt ovan utom OLED | proben visar friska rader för båda dekodrarna (nedan) |
| M4 | `m4_dual_mix` | samma | kamerabilden syns på HDMI; byte mellan mottagarna när en antenn tas bort |
| M6 | `m6_puck_proto` | + OLED, knappar | menyn på OLED och OSD, kanalbyte fungerar, mätloggen kommer över USB |

```bash
gateware/build.sh m3_probe
openFPGALoader -b tangnano20k gateware/build/m3_probe.fs
```

Loggen läses från kortets andra USB-serieport (BL616 visar två; UART:en är oftast den andra):

```bash
stty -F /dev/ttyUSB1 115200 raw -echo && cat /dev/ttyUSB1
```

## 3. Vad M3-proben ska visa

En rad per dekoder och sekund. Frisk NTSC:

```
A sclk 27000064 tog FF hi FF len 1716-1716 ln 14565 fld 060 xe 0000 i2c OK st 000E
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
| `i2c` | `OK` | dekodern svarar |
| `st` | `000E` | statusregister 89h,88h: 88h bit 1/2/3 = H-, V- och färglås, bit 5 = 1 betyder 50 Hz och bit 6 = 1 radalternerande, så PAL ger `006E`; 89h bit 6 = svag signal (SLES209E 3.21.49–50) |

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
| `i2c OK` men låsbitarna i `st` är nollor | ingen videosignal: mottagaren, kanalen eller videokabeln |
| `fld 000` men `ln` är normal | källan är inte sammanflätad (240p/288p) och F-biten växlar aldrig. Mixern hanterar inte det än (Core issue #4) |
| `i2c NA` på båda efter pull-testet | en knapp hölls nere vid start, eller YOUT7-strappningen flyttades (se pull-testet) |

**Pull-testet** hittar glapp utan mätinstrument:

```bash
PULL=UP gateware/build.sh m3_probe      # -> build/m3_probe_pullup.fs
PULL=DOWN gateware/build.sh m3_probe    # -> build/m3_probe_pulldown.fs
```

Ett svagt internt pull-motstånd kan inte flytta ett stift som dekodern verkligen driver. En bit som följer pull-up/pull-down (syns i `hi` och `tog`) drivs alltså inte: glapp eller fel stift. Idén kommer från otanl/CVBS2HDMI.

YOUT7 lämnas utan pull: den är också dekoderns I2C-adress-strap, som läses vid reset, och en pull-up skulle kunna flytta adressen. Stift 26, 49 och 79 har motstånd på Tang-kortet (HDMI hot-plug, bakbelysningsdrivaren, WS2812) och följer inte alltid en svag pull; där bevisar testet mindre.

## 5. Delade stift på Tang Nano 20K (rev 3923)

Stiftplanen använder alla vanliga stift på stiftlisterna. Några av dem är också kopplade till annat på kortet (Sipeeds schema rev 1.3, enligt [openfpga-deck:s kortbeskrivning](https://github.com/Yash-Kamat/openfpga-deck/pull/11)):

| Stift | Vår signal | Också kopplat till | Risk |
|---|---|---|---|
| 26 | YOUT2 A | HDMI hot-plug (spänningsdelare från 5 V) | Låg: dekodern driver mot ett motstånd när en skärm sitter i |
| 18 | RESETB | lysdiod 3 (510 Ω till 3,3 V) | Ingen: lysdioden lyser under reset. (Tidigare stift 25: HDMI-banken och CEC, flyttat.) |
| 76 | YOUT0 B | BL616 SPI MOSI | **Kontrollera:** om BL616 är SPI-master driver den stiftet, och bit 0 blir fel. Proben visar det. |
| 86 | YOUT5 B | BL616 SPI DIR | **Kontrollera,** samma |
| 75 | SCL | BL616 SPI MISO | **Kontrollera:** om BL616 är SPI-slav (Sipeeds `spi`-läge i BL616-konsolen) driver den stiftet. Lämna konsolen i standardläget. |
| 87, 88 | S1, S2 (M6-knapparna) | FPGA:ns MODE-stift (1 kΩ mot jord) | Håll inte en knapp nere när kortet startar: då laddas inte bitströmmen från flash |
| 48, 49 | YOUT3/4 B | LCD DE, LCD-bakbelysningens drivkrets (LP3320 EN) | Bakbelysningsomvandlaren slås av och på i bildtakt utan last. Lyssna och mät snö med M6. |
| 79 | YOUT6 B | WS2812 RGB-lysdiodens data | Ofarligt: RGB-lysdioden blinkar i slumpfärger |
| 80, 85 | SCLK B, SDA A | microSD med 10 kΩ pull-up | Ofarligt |
| 51 | SDA B | ljudförstärkarens SD_MODE | Ofarligt: förstärkaren slås av och på |

Om bit 0 eller 5 på dekoder B visar sig störd (BL616): byt den signalen mot stift 71 och flytta SPI-klockan till lysdiodsstift 17 (J6-15). Ändringen görs i `boards/*.cst` och `top/*.v`.
