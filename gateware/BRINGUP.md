# Uppstart på bänken: Tang Nano 20K + två TVP5150-moduler + två RX5808

Ordningen är M0 → M3 → M2a → M4 → M6; M2a kan också tas direkt efter M0 (avsnitt 2.1). Varje steg bevisar en sak innan nästa läggs på. Allt nedan gäller stiftplanen i `boards/m4_dual_mix.cst` (samma i M3 och M6).

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

**Digital ingång på dekoder B:s plats (byggvalet `DIGIN=1`, `m4_dual_mix_digin.fs`).** Kanal B tar då C5VRX-mottagarens
6-bitars sampelbuss (XIAO ESP32-C5, PARLIO TX 40 MS/s, komposit med färgbärvågen) i stället för en TVP5150; `rtl/cvbs_capture.v`
gör samma radord och markörer som `chan_capture.v`, i det här steget bara luma (navets `docs/design/2026-10-24/DIGITAL_INGANG.md`).
Firmwaren måste lägga ut sampelklockan på MTMS-paden (GPIO2, kortets baksida): det privata bygget från 2026-10-24
(synkhjulet av med konsol `U`) eller Twotoz PR #257 byggd med klockvalet `C5VRX_OUT_DAC6_CLOCK` (inget synkhjul;
flasharens PR-bygge har klockan av), se designnoten. 3,3 V-logik, korta trådar.

| XIAO | Signal | Tang | | XIAO | Signal | Tang |
|---|---|---|---|---|---|---|
| MTMS-pad (GPIO2) | sampelklocka 40 MHz | J5-4 (PIN80) | | D7 | bit 3 | J5-10 (PIN48) |
| D4 | bit 0 | J5-3 (PIN76) | | D8 | bit 4 | J5-12 (PIN49) |
| D5 | bit 1 | J5-5 (PIN42) | | D9 | bit 5 | J5-13 (PIN86) |
| D6 | bit 2 | J5-6 (PIN41) | | GND | jord | GND |

Data byter värde på klockans negativa flank och samplas på den positiva. Mätt på bussen 2026-10-27 (`top/m7_digin_probe.v`,
navets `docs/BENCH.md` "Den digitala bussen"): klockan 40,0 MHz, synktopp kod 22–24, släckning 30–32, video 40–56, vitt 62;
`cvbs_capture` sveper därför skiljaren tills den hittar synken (grenen `digin/levels`; `6b845e8` väntade synk vid 4 och gav
inga rader). Dekoder A (TVP, RX5808) är orörd: A analog mot B digital från samma kamera är det första diversity-provet. Klart när lysdiod 2 (rader från B) lyser, hjärtslaget går från
4 Hz till 1 Hz på B:s eget lås (`cvbs_capture` `lock`, sedan 2026-10-26; bitströmmen `6b845e8` före det blinkar 4 Hz med
bara B) och bilden från B syns på HDMI; inget synklås krävs från någon TVP för kanal B. M6 har ingen digital ingång än,
så M6-loggens B-fält gäller TVP B.

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
| M4, M6 | hjärtslag: 4 Hz utan låst dekoder, 1 Hz när en är låst, 2 Hz när båda är det (sedan 2026-10-21; förut 1 Hz bara med båda); M4 med `DIGIN=1` räknar B:s eget lås (sedan 2026-10-26) | rader från A | rader från B |

M4 visar de första 3 sekunderna i stället SDRAM-självtestet på lysdiod 1 och 2 (README under M4, "SDRAM-självtestet"): 1 tänd = läspunkt 5 läste båda testskurarna rätt; 2 tänd = den gjorde det inte, men läspunkt 4 eller 6 gjorde det; båda tända = ingen läspunkt. M6 skriver resultatet sist i varje loggrad (2.2).

**OLED (M6):** SCL J6-3, SDA J6-4 (samma buss som dekoder A), 3,3 V, GND.

**Sändaren LST-S4:** ställ den på NTSC (blå lysdiod enligt manualen) och band F, kanal 4 (5800 MHz). M3 och M4 ställer mottagarna på F4. M6 ställer dem på menyns kanal, som är F4 vid start.

**När kanalen skrivs** (`rtl/rx5808_tune.v`): 0,5 s efter start, och sedan varannan sekund så länge ingen dekoder är låst. En mottagare som får ström efter FPGA:n, eller tappar den, står på sin startkanal (5865 MHz enligt RTC6715-databladet) och ställs om inom 2 s. Så länge en dekoder är låst skrivs kanalen inte om, eftersom det inte är provat om en omskrivning stör bilden. I M6 skrivs kanalen dessutom direkt vid varje band- eller kanalbyte.

## 2. Stegen

| Steg | Bitström | Kopplat | Klart när |
|---|---|---|---|
| M0 | `m0_testpattern` | bara Tang + HDMI | testbilden syns på skärmen |
| M3 | `m3_probe` | allt ovan utom OLED | proben visar friska rader för båda dekodrarna (nedan) |
| M2a | `m2a_memtest` | bara Tang + USB | en ren läspunkt `rs=5` (avsnitt 2.1) |
| M4 | `m4_dual_mix` | samma | lysdiod 0 går från 4 Hz till 1 Hz (en dekoder låst; 2 Hz med båda); kamerabilden syns på HDMI; byte mellan mottagarna när en antenn tas bort |
| M6 | `m6_puck_proto` | + OLED, knappar | flygvyn och menyn på OLED och OSD, kanalbyte fungerar, posten `FILT` växlar `TV`/`VCR` och `HDMI` `FULL`/`LTD`, mätloggen kommer över USB (2.2), inställningarna står kvar efter strömavbrott och flygvyn säger `SAVED` (2.3) |

```bash
gateware/build.sh m3_probe
openFPGALoader -b tangnano20k gateware/build/m3_probe.fs
```

**Dekoderns I2C-adress.** TVP5150AM1 tar adressen (5C eller 5D) från YOUT7:s nivå när den startar, och en modul kan ha den fast dragen åt endera hållet. Den röda modulen CP803A svarar på 5D (bänken 2026-10-21: `i2c NA` med frisk klocka på 5C, `i2c OK` på 5D). Sedan 2026-10-21 provar `tvp_ctrl.v` båda adresserna själv, per dekoder: svarar ingen på den första (5C, eller 5D med `TVP_ADDR=5D`) går samma skrivning till den andra, och den adress som svarat behålls till nästa reset, också när dekodern initieras om. M3-proben skriver adressen i fältet `i2c` (`5C` eller `5D`). Två moduler med olika strappning går alltså i samma bitström, och `TVP_ADDR=5D` behövs inte längre; valet finns kvar och anger vilken adress som provas först. Utan RESETB-tråd kan adressen bero på FPGA:ns pull medan den konfigureras (navets `docs/design/2026-10-21/LOGIKGRANSKNING.md`, F3); löd därför tråden. Simulerat mot slavmodellen, inte provat på kortet. Rev A-kortet drar båda dekodrarna till 5C.

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

**Kört på kortet 2026-10-21** (rev 3923, Fable över usbipd/WSL; navets `docs/bench/`): med standardbygget (utan I/O-cellregister) `rs=5 err=00000000` varv efter varv, `rs=4 err=00400000` (alla ord fel: ordet före) och `rs=6 err=00380000 pos=FFFFFFF0` (sju av åtta ord fel: ordet efter), vid fas 9, 10 och 11. Standardfasen 225° och läspunkten 5 står alltså med en marginal på minst ett steg åt vardera hållet. Byggt med `IOREG=1`, standarden fram till 2026-10-21, är raden oläsbar (README "I/O-register i I/O-cellerna"); en sådan logg är inget minnesresultat.

### 2.2 M6: filterfältet, HDMI-fältet och mätloggen

Filterfältet står på rad 4 som `TV` eller `VCR` (före 2026-10-18 `FILT TV`) och gäller båda dekodrarna (register 02h, 30h respektive 20h). Efter reset står det på `TV`. Det skrivs till dekodrarna mellan pollrundorna och igen efter en dekoderomstart. Vilket läge som håller låset och bilden bäst är inte avgjort; prova båda med samma kamera och kanal och logga varje läge för sig.

Efter filtret kommer HDMI-fältet, sist före sidvalet: `HDMI FULL` (standard) eller `HDMI LTD`. Det gör något bara i HDMI-bygget (`HDMI=1 gateware/build.sh m6_puck_proto`, filen `m6_puck_proto_hdmi.fs`): `FULL` sänder 0–255 och säger fullt omfång i AVI-infoframen, `LTD` skalar bilden till 16–235 och säger begränsat. Bytet slår igenom vid nästa bild. Kortet kan inte läsa skärmens EDID, så vilket läge som ger rätt svärta avgörs med gråskala och EDID per skärm (navets `docs/MATPROTOKOLL.md`, blad 16; README under M0, "Omfånget i HDMI-läget"). DVI-bygget, standard, påverkas inte.

Mätloggen kommer på samma serieport som proben: en rad per mätfönster (cirka 15 per sekund), **89 byte** inklusive CR LF (87 före SDRAM-självtestet 2026-10-21, 85 före HDMI-tecknet 2026-10-18, 62 före RSSI-fälten 2026-10-13). Efter mixläget står filtret som `T` eller `V` och HDMI-omfånget som `F` eller `L`, före tappflaggan och de två låstecknen; därefter RSSI A och B, kalibrerat värde och ett tecken per mottagare (`W`, `L`, `-`, `?`), och sist SDRAM-självtestet: `2` när bara standardläspunkten 5 läser rätt, som den ska. Utan ADS1115 på kortet står RSSI som `-----` och `??`.

Filtertecknet är menyvalet som begärts, inte en återläsning av 02h, så direkt efter ett byte kan en dekoder ännu stå i det gamla läget. Fältens betydelse står i tabellen i 2.3 och i README under M6.

```bash
python gateware/tools/snowlog.py /dev/ttyUSB1 --label tv --seconds 30 --out filt.csv
python gateware/tools/snowlog.py /dev/ttyUSB1 --label vcr --seconds 30 --out filt.csv
python gateware/tools/snowlog.py --summary filt.csv
```

**Utan knappar** (byggvalet `DEVCMD=1`, `m6_puck_proto_devcmd.fs`, inte provat på kortet): enbytes-kommandon på samma serieport ställer latensläge, filter, mixläge, `HOLD`, kanal och OSD, och `?` ger en statusrad med dekodrarnas adress, 88h/89h och 03h. Loggraden blir då 101 byte och visar varje kommando. Listan står i README under M6, "Kommandon från datorn".

```bash
python gateware/tools/m6ctl.py V          # filter VCR, skriver loggraden som visar det
python gateware/tools/m6ctl.py '?'        # statusraden
```

Samma byggen har fältdumpen (README under M6, "Fältdumpen"): ett fält ur dekoder A före mixern, eller ur mixerns utström, rad för rad över UART till PNG. Vid 115 200 baud tar ett NTSC-fält cirka 35 s; `UART_BAUD=921600` vid bygget kortar det (och alla verktyg får då `--baud 921600`).

```bash
python gateware/tools/fielddump.py D --out dekoder_a
```

`snowlog.py` läser också de äldre raderna på 87, 85, 62, 60, 57 och 43 byte från tidigare bitströmmar; kolumnerna de saknar blir tomma. En CSV-fil skriven före kolumnen `sdram` (2026-10-21) eller `hdmi` (2026-10-18) får inga nya rader; skriv till en ny fil.

### 2.3 M6: SCAN, CAL och sparade inställningar

Allt här är simulerat (`sim/test_chan_scan.py`, `sim/test_rssi_adc.py`, `sim/test_flash_store.py`, `sim/test_puck_ui.py`); inget är provat på kortet. **Första hårdvaruprovet är de sparade inställningarna med bara Tang-kortet** (navets `docs/MATPROTOKOLL.md`, blad 19): M6 i flash och en HDMI-skärm eller OLED:en, inga dekodrar. `SCAN` (blad 18) kräver mottagare, dekodrar och en sändare; `CAL` (blad 17) dessutom rev A-kortets ADS1115.

**Menyn** (sedan 2026-10-19, navets `docs/UI_FLYGVY_2026-10-19.md`). Skärmen startar i flygvyn: kanalen dubbelhögt, dekoderstatus och RSSI per mottagare, mixläge/latens/filter och sparstatus. Knapparna har inga namn, skärmen visar dem som pilar: ▼ = S1, ▲ = S2. ▲ öppnar menyn, som visar en post per skärm: ▼ går till nästa post (efter `HOLD` tillbaka till flygvyn), ▲ ändrar posten, 15 s utan knapp ger flygvyn igen. ▼ i flygvyn bläddrar mätare → RSSI → flygvy.

| Funktion | Var | Gör så här | Vad som händer |
|---|---|---|---|
| Filtret | menyn, femte posten `FILT` | ▲ i flygvyn öppnar menyn på `BAND`, ▼ fyra gånger (`CH`, `MODE`, `LAT`, `FILT`), ▲ växlar `TV`/`VCR` | avsnitt 2.2 |
| `HDMI` | menyn, sjätte posten | ▼ en gång till, ▲ växlar `FULL`/`LTD` | avsnitt 2.2; i DVI-bygget står `HDMI N/A` och ▲ gör inget |
| `SCAN` | menyn, sjunde posten | ▼ en gång till, ▲ startar | Skärmen visar `SCANNING`, kanalen som provas och `ANY BUTTON ABORTS`; 100–160 ms per kanal, 5–8 s för alla 48. Hittas en kanal där en dekoder låste med lägst brus slutar menyn i flygvyn med den. Låste ingen står startkanalen kvar och skärmen visar `SCAN NONE` till nästa knapptryck. Varje knapp under skanningen avbryter och ställer tillbaka startkanalen. Med `HOLD` på startar ingen skanning |
| `HOLD` | menyn, åttonde posten | ▼ en gång till, ▲ växlar OFF/ON; ▼ igen ger flygvyn | ON: `BAND`, `CH` och `SCAN` reagerar inte, flygvyn visar ett hänglås. Sparas inte; av efter start |
| `CAL` | RSSI-sidan (▼ två gånger i flygvyn) | ▲ slår på; flytta sändaren nära och långt bort, eller stäng av den; ▲ stänger av | Min och max per mottagare. En mottagare är kalibrerad när spannet är minst 400 koder: rad 4 visar `OK` och rad 2–3 ett värde 0–100 i stället för `---`. Att lämna sidan (▼) avslutar kalibreringen |
| Sparstatus | flygvyn, rad 4 | | `SAVED` när flashen har en post med just de här inställningarna, `UNSAVED` från en ändring tills posten är skriven och återläst (3 s efter sista ändringen), `SAVE ERR` om återläsningen inte stämde, `DEFAULTS` när flashen saknar post och inget är ändrat |

**Loggraden, 89 byte** (115200 8N1, ungefär 15 rader per sekund):

```
S 012345 002345 000017 000000 040 034 025 F4 5800 MIX T F - -- 12000 04567 075 003 -W 2
```

| Fält | I exemplet | Betydelse |
|---|---|---|
| snö A, B | `012345 002345` | medel-HF-energi per rad över 1 024 rader; `------` när inga rader kommer från mottagaren |
| brus A, B | `000017 000000` | lumasampel utanför 16–235 i de senaste 1 024 raderna |
| A, B, blandning | `040 034 025` | procent av de senaste 1 024 mixerbesluten |
| kanal, frekvens | `F4 5800` | inställd kanal |
| mixläge | `MIX` | `MIX`, `A` eller `B` |
| filter | `T` | `T` (TV) eller `V` (VCR), menyvalet |
| HDMI | `F` | `F` (`FULL`) eller `L` (`LTD`), menyvalet; står också i DVI-bygget |
| tappflagga | `-` | `!` om mixern sedan start har tappat en rad för att radplatserna var fulla |
| lås A, B | `--` | `L` hel pollrunda med "lost lock" (88h bit 4), `-` hela rundor utan, `?` ingen hel runda |
| RSSI A, B | `12000 04567` | ADS1115-kod, `-----` utan avläsning |
| kalibrerat A, B | `075 003` | 0–100, `---` okalibrerat |
| tillstånd A, B | `-W` | `W` svag (mixern undviker den), `L` låg, `-` ingetdera, `?` ingen avläsning |
| SDRAM-självtest | `2` | `-` inte kört än, annars en siffra 0–7: bit 0, 1, 2 = läspunkt 4, 5, 6 läste testskurarna rätt. `2` är rätt; `1` eller `4` betyder fas eller läspunkt ett steg fel för det här bygget (kör M2a-svepet), `0` att ingen läspunkt fungerar |

Latensläget (`BUF`/`LOW`) finns inte i loggen, bara på OLED:n och i OSD:n. En rad skickas efter varje fönster om 1 024 mixerbeslut, och sedan 2026-10-21 också en gång i sekunden när inget fönster kommer (utan video från någon dekoder: snö och brus `------`, procenttalen från senaste fönstret).

**Att se att en inställning sparats och lästs.** Loggen har ingen särskild startrad, men redan den första raden efter start visar det som lästs: flashen läses inom cirka 10 ms efter konfigurationen, före första loggraden och före första kanalskrivningen (0,5 s). Utan sparad post startar M6 på `F4 5800`, `MIX`, `BUF`, `TV`, `HDMI FULL`, RSSI okalibrerad.

1. Programmera M6 i flash (`openFPGALoader -b tangnano20k -f gateware/build/m6_puck_proto.fs`). `build.sh` packar M6 med `--mspi_as_gpio`, och manifestet ska säga `mspi` 1; utan det når M6 inte flashen.
2. Byt kanal, till exempel till `A1 5865`, filtret till `VCR` och HDMI till `LTD`. Rör sedan ingen knapp på minst 3 s: en post skrivs när inställningarna har legat stilla i 3 s, inte vid varje knapptryck.
3. Flygvyn ska gå från `UNSAVED` till `SAVED` inom cirka 3 s efter sista knapptrycket. Bryt strömmen (dra ur USB) och slå på. OSD:n visas 5 s efter start; den, OLED:n och första loggraden ska visa `A1 5865`, `VCR` och (i menyposten `HDMI`) `LTD` (i loggen `V` och `L`), och flygvyn `SAVED`.
4. Samma för RSSI-kalibreringen: efter `CAL` av och 3 s, starta om; RSSI-sidan ska visa `OK` och värden, och loggens kalibrerade fält ska vara tal.
5. Posterna kan läsas direkt ur flashen (8380416 = 7FE000h):

```bash
openFPGALoader -b tangnano20k --dump-flash -o 8380416 --file-size 8192 settings.bin
xxd settings.bin | head
```

Varje post är 16 byte: `A5`, löpnummer (två byte), tio byte inställningar, antalet nollbitar i de 13 byten före (Z), `FF`, CRC-8. Antalet poster är antalet sparanden sedan sektorn raderades. Bitströmmar före 2026-10-14 skrev `FF FF` i stället för Z och `FF`; deras poster godtas inte längre, så M6 startar på standardvärdena första gången efter uppdateringen. HDMI-omfånget är bit 5 i den andra inställningsbyten, som förut alltid var 0, så poster från bitströmmar före 2026-10-18 laddas som `HDMI FULL`.

Det som inte syns: `flash_store.v` sätter en felflagga när en skrivning inte läses tillbaka lika, men M6 visar den ingenstans. Ett skrivfel märks bara som att inställningen saknas efter omstart, eller i läsningen ovan.

**Att radera inställningarna utan att röra bitströmmen.** Skriv 8 KB med FFh över de två sektorerna 7FE000h och 7FF000h:

```bash
python3 -c "import sys; sys.stdout.buffer.write(b'\xff' * 8192)" > ff8k.bin
openFPGALoader -b tangnano20k -f -o 8380416 ff8k.bin
openFPGALoader -b tangnano20k --dump-flash -o 8380416 --file-size 8192 check.bin
python3 -c "print(set(open('check.bin', 'rb').read()) == {255})"
```

Sista raden ska skriva `True`. Efter nästa start står M6 på standardvärdena. Enligt openFPGALoaders källkod (`src/gowin.cpp`: rå fil till GW2AR:s externa flash på en adress; `src/spiFlash.cpp`: `erase_and_prog` raderar bara det område som skrivs, avrundat uppåt till 4 KB, eller 64 KB, alltså 7F0000h–7FFFFFh, om programmet inte känner flashens sektorradering) rör det inte bitströmmen, som slutar under cirka E0000h. Av samma skäl ska programmering av bitströmmen med `-f` lämna inställningarna kvar. Källkoden är läst 2026-10-13; inget av detta är provat på kortet (blad 19 kontrollerar det).

**Tom eller skadad flash.**

| Läge | Vad M6 gör |
|---|---|
| Tom (allt FFh: nytt kort eller raderat som ovan) | Ingen post laddas, standardvärdena gäller. Första sparandet raderar 7FE000h och skriver post 0 där |
| Nyaste posten trasig (fel CRC, fel Z eller utan `A5`), till exempel efter ett strömavbrott mitt i en skrivning | Posten hoppas över och den näst nyaste giltiga laddas: inställningen före den sista ändringen |
| Strömavbrott mitt i raderingen av en full sektor | Den halvraderade sektorns poster godtas inte (Z fångar varje fel åt ett håll); den nyaste posten i den andra sektorn laddas, och nästa sparande raderar den halvraderade sektorn igen. Före 2026-10-14 kunde en sådan post klara `A5` och CRC och laddas, och nästa sparande raderade då sektorn med den riktiga posten (granskningen 2026-10-14, FL-1) |
| En post med band eller läge som menyn inte kan ställa (band 6 och 7, läge 3) | Godtas inte |
| Ingen giltig post alls (skräp i båda sektorerna) | Som tom: standardvärden, och första sparandet raderar 7FE000h först |
| Sektorn full (256 poster) | Nästa post skrivs först i den andra sektorn, som raderas innan; den fulla sektorns nyaste post finns kvar under raderingen |
| Löpnumret passerar FFFFh | Nyast avgörs i serienummerordning, så räknarens varv stör inte |

Tom flash, trasig nyaste post, full sektor, avbruten radering (150 halvraderade avbilder, bitarna satta slumpvis: en antagen modell, XTX beskriver inte vad ett avbrott lämnar), band 7 och löpnumret förbi FFFFh är simulerade mot `model/flash_store_ref.py` med en flashmodell (`sim/test_flash_store.py`), med hela flashavbilden jämförd byte för byte. Skräp i båda sektorerna är inte simulerat; raden är läst ur `flash_store.v`.

## 3. Vad M3-proben ska visa

En rad per dekoder och sekund. Frisk NTSC:

```
A sclk 27000064 tog FF hi FF len 1716-1716 ln 14565 fld 060 xe 0000 i2c 5C st 000E ri 00
```

| Fält | Friskt | Betyder |
|---|---|---|
| `sclk` | 27 000 000 ± några hundra | dekoderns klocka i Hz |
| `tog` | `FF` | vilka av YOUT7..0 som växlat |
| `hi` | `FF` | vilka som någon gång varit 1 |
| `len` | `1716-1716` (PAL `1728-1728`) | kortaste och längsta raden i byte |
| `ln` | ca 14 500 | aktiva rader per sekund |
| `fld` | `060` (PAL `050`) | fält per sekund, räknade på första aktiva raden efter vertikalsläckningen (före 2026-10-21 F-bitens växlingar, som gav `000` för en källa utan sammanflätning) |
| `xe` | `0000` | synkord med bitfel som inte gick att rätta (per rad högst 255; förut slog räknaren runt vid 256) |
| `i2c` | `5C` (eller `5D`) | dekodern svarade på den senaste I2C-frågan, på den adressen (`NA`: inget svar, `--`: uppstarten är inte klar; före 2026-10-21 `OK`) |
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
| `i2c NA` | SDA eller SCL, pull-up saknas; varken 5C eller 5D svarar |
| `i2c 5C` eller `5D` men låsbitarna i `st` är nollor (sista siffran inte `E`) | ingen videosignal: mottagaren, kanalen eller videokabeln |
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

- Bit 7 får ingen pull. YOUT7 är dekoderns adresstrapp (I2CSEL), som läses vid reset. En pull-up mot modulens eget strappmotstånd kan flytta dekodern till adress BAh (5D); proben hittar den där och visar `i2c 5D` (före 2026-10-21 `i2c NA`). Bit 7 kontrolleras i stället med `tog` och `hi` i den vanliga bitströmmen.
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

I alla byggen sedan 2026-10-05, senast ur `0da655d` (2026-10-12, även M2 och M2s), har alla fyra HDMI-par i M4 och M6 samma IOB-fuses som i M0. Klockparet har 18 satta; med RESETB på stift 25 var det 16 i M4 och M6. Om en skärm bryr sig om skillnaden är inte provat. Regeln gör att en fungerande M0 säger något om HDMI-utgången i M4 och M6.

Om bit 0 eller 5 på dekoder B visar sig störd (BL616): byt den signalen mot stift 71 och flytta SPI-klockan till lysdiodsstift 17 (J6-15; lysdiod 2 försvinner då). Ändringen görs i `boards/*.cst` och `top/*.v`.
