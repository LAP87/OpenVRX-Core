# Formella bevis

`run.sh` bevisar med k-induktion i yosys, utan extern lösare, och körs av `tools/test_formal.py` (cirka en minut). Varje bevis har negativa kontroller: en avsiktligt felaktig variant som måste ge ett motexempel från reset. `PROVEN` och `CONTROL OK` räknas i testet.

Här beskrivs klockdomänsövergångarna i `rtl/fb_backend.v`. FIFO:n och genlocken står i `gateware/README.md`.

## Modellen

- **Klockor.** Varje klocka är en fri insignal (`clk2fflogic`). Mellan två stigande flanker av den ena klockan kommer högst 3 flanker av den andra; en fjärde får sammanfalla med nästa. Det gäller för alla par från 27–108 MHz mot 74,25 MHz, åt båda hållen: 108 / 74,25 = 1,45 och 74,25 / 27 = 2,75. Utanför det intervallet gäller bevisen inte utan nya tal.
- **Övergången.** En bit som mottagaren samplar och som har ändrats sedan mottagarens förra flank får läsas som vilket värde som helst: ett sampel mitt i en ändring som faller åt ena eller andra hållet, eller skevning mellan databitarna. En bit som har stått still en hel period läses rätt.
- **Inga tomma steg.** I varje steg ändras minst en klocka. Varje verklig tidsföljd kan skrivas så.
- **Reset.** Bevisen börjar i nollställt läge. Reset mitt i drift, asynkront mellan domänerna, ingår inte.

## Bevisat

Synkroniserarna ligger i `rtl/cdc_sync.v`. `fb_backend.v` och `fb_display.v` instansierar dem, så bevisen gäller den kod som byggs.

| Bevis | Övergång | Påstående | Negativ kontroll |
|---|---|---|---|
| `cdc_toggle` (`toggle_props.v`) | `toggle_rx`: radbegäran (pixel → SDRAM), publicering och lågfördröjningstrigger (SDRAM → pixel) | Om sändaren vänder `tgl` högst var 16:e egen klocka och håller data 16 klockor efter vändningen: ingen händelse tappas eller dubbleras, varje händelse tas emot inom 4 mottagarflanker, och `q` är datan från den senast mottagna vändningen | Flanken tagen direkt från andra domänen (inget synksteg): fel data. Vändning var 8:e klocka: en händelse tappas. Data som ändras 2 klockor efter vändningen: fel data |
| `cdc_level` (`level_props.v`) | `sync2`: `ll_mode` in i båda domänerna | Varje domäns bild av läget ändras bara på en flank av den egna klockan, och är lika med läget från tredje flanken efter ett byte. De två domänerna kan bara vara oense medan någon av dem har haft färre än tre flanker sedan bytet | Lägesbiten utan `sync2`: ändras mellan flankerna. Inställd redan efter två flanker: falskt, första samplet kan bli det gamla värdet |
| `fb_linebuf_slots` (`linebuf_props.v`, egenskapen i `fb_display.v`) | Radbuffertens platser i `BUF`-läget | Med den riktiga tidsbasen, liten bild: en rad som begärs under en aktiv utrad går till en plats som displayen inte läser under resten av raden. Bildens första begäran (plats 0, som displayen då läser) görs på en släckrad | Begäran till platsen som läses (utan förskjutningen en rad framåt): egenskapen faller |

Kontrollerna körs utan induktionsförstärkningen (`FORMAL_NO_STRENGTHEN`), så motexemplet kommer från själva egenskapen. Vilket påstående som föll är kontrollerat för hand för varje kontroll.

Om "längre än två cykler": med modellen ovan är gränsen tre flanker av den egna klockan, inte två. Med två flanker hittar `cdc_level_two_edges` ett motexempel. Oenigheten varar alltså kortare än tre perioder av den långsammare klockan.

## Inte bevisat

1. **Att två synksteg räcker mot metastabilitet.** Modellen låter ett sampel bli vilket värde som helst, men inte en vippa som står mellan nivåerna en stund. Med ett enda steg hittar modellen inget fel: `toggle_rx` klarar 40 steg från reset och nivåbeviset sluter sig (kört för hand 2026-10-06). Det andra steget är standardpraxis och inte bevisat nödvändigt.
2. **Sändarnas avstånd och hålltid** (16 sändarklockor) är inte bevisade för de moduler som sänder. De följer av koden:
   - Radbegäran (`fb_display.v`): högst en begäran per utrad (vid `x == 2`), bildens första vid `x == 0` på sista släckraden. Data ändras bara med vändningen. Avståndet är minst en radlängd minus två klockor (1 648 pixelklockor i 720p).
   - Publicering (`fb_sdram.v`): `pub_lines` ändras en klocka före vändningen. Efter varje publicering sveper skrivaren 128 SDRAM-klockor utan att läsa FIFO:n, så nästa publicering och nästa ändring kommer tidigast 128 klockor senare.
   - Lågfördröjningstriggern (`fb_backend.v`): en trigger per fält, på ord 359 i en rad. Två triggrar ligger minst 360 ord isär, alltså minst 360 SDRAM-klockor.
3. **Öppet: `s_ll_lines`.** Radantalet som följer lågfördröjningstriggern ändras när nästa fält börjar, inte med triggern. Beviset kräver att data står still 16 SDRAM-klockor efter vändningen. Med riktig video kommer nästa fält hundratals rader senare. En källa vars fält slutar direkt efter rad 1 kan däremot byta fält en klocka efter triggern, och pixeldomänen kan då läsa ett blandat värde. Samma gäller ett fältbyte strax efter en fördröjd trigger (`ll_wait`). Följden blir fel radantal under en bild: skalningen och valet mellan 720p50 och 720p60 (`ll_pal`). Egenskapen ligger bortkommenterad i `run.sh` (`cdc_toggle_ll_lines`); kontrollen `cdc_toggle_data_early` visar vad som händer. En rättning vore att hålla `s_ll_lines` oförändrat 16 klockor efter varje trigger. Den är inte införd, eftersom passet gällde bevis.
4. **`frame_low` och `ll_low`** är nivåer som läses vid `y == 0`. `sync2` är bevisad, men att värdet har kommit fram före läsningen beror på tid. `frame_low` sätts när SDRAM-sidan tar emot bildens första radbegäran, som skickas en utrad före rad 0; att mottagningen inte dröjer längre än så är inte visat. `ll_low` sätts senast på samma SDRAM-flank som triggern vänds. Det går genom två steg, triggern genom tre plus ett register. Bildstarten kan komma redan klockan efter att triggern tagits emot (`genlock_timing.v` avslutar bilden på `trig`). Med modellen ovan räcker det med minst en klockas marginal, men det är inte bevisat.
5. **Radbuffertens skrivsida.** Beviset visar att läsaren inte rör den begärda platsen förrän vid nästa radstart, 1 650 pixelklockor (22,2 µs) senare. Att SDRAM-sidan har skrivit hela raden dessförinnan beror på latensen i `fb_sdram.v` och `sdram_burst.v` (skrivaren, uppdatering, arbitrering). Simulerat: en rad hämtas på högst 11,7 µs (`sim/test_m2.py`, `sim/test_fb.py`). Det är inte bevisat.
6. **Lågfördröjningsringen** (16 platser): att skrivaren aldrig ligger 16 rader före och att läsaren aldrig går om beror på in- och utradernas tider (63,6 µs mot 3 × 22,2 µs) och på genlocken. Det är ett tidsresonemang över en hel bild, hundratusentals klockor, och går inte att bevisa med k-induktion här. Simulerat i `sim/test_m2.py` och `sim/test_fb.py`.
