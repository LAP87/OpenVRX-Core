# Färgmodell vid C5VRX:s uppmätta nivåer

Modellundersökning för Core #27, från `a6e3c2b`, 2026-11-05. Underlag: utkast `6fe4d6a` och granskningsgrenen `b5974c0`. Ingen RTL-ändring, native färgsimulering eller ny hårdvarumätning. Modellen är inte godkänd för FPGA-implementation: det frysta noggrannhetsmålet missas vid en av två källskalor.

## Fyra fel som rättades i utkastet

1. Chroma-packningen behöll Cb-bit 7 från den neutrala byten `0x80`. Alla Cb-värden blev därför minst 128. Masken är nu `0xFF00FF00`; båda chromabytes ersätts, båda lumabytes bevaras.
2. Active-flaggan för en rad togs från slutet på raden i en första genomgång. Den sista raden saknade en sådan händelse och fick därför föregående rads färg. Modellen följer nu originalfångstens faktiska start- och active-signaler i en enda genomgång, även på sista raden.
3. Gränsen 720 räknade alla luma-ticks sedan synk, inte 720 aktiva pixlar. Färgen slutade därför uppdateras för tidigt. En separat aktiv räknare och en kontroll mot varje faktiskt emitterat ord förhindrar gammal färg. Både Cb och Cr kommer från samma ords andra pixel.
4. Bildens luma och chroma beskrev olika staplar; dessutom var flera värden i den gamla "BT.601"-paletten fel. Nu används samma åtta RGB-staplar för Y, Cb och Cr. Ett oberoende numeriskt test beräknar deras värden från [ITU-R BT.601-7](https://www.itu.int/dms_pubrec/itu-r/rec/bt/r-rec-bt.601-7-201103-i!!pdf-e.pdf), ekvationerna 1, 4 och 5.

Inversens tecken och skala kontrolleras också genom numerisk korrelation av två sinusformade rader. Testet genererar inte sina I/Q-värden från avkodarens ROT/K-formel. Både 2 542 och 2 543 klockors verklig radfördröjning provas: samma rotation duger inte för båda. Boxcar-summornas delbitar behålls tills färgbyten avrundas.

## Mätkontrakt

360 syntetiska NTSC-rader från rad 1; åtta fullnivåstaplar vit, gul, cyan, grön, magenta, röd, blå, svart. Ursprungliga `cvbs_capture_ref` avgör lås, rader och alla Y-bytes/markörer. Vardera chromaparets sanning hämtas vid dess faktiska sampelklockor, i staplarnas centrala 30 pixlar och efter fyra synliga rader. Tom utdata ger inget numeriskt färgbetyg.

Två källskalor: 23/31/62 och 13/25/50 (synk/släckning/vitt), brus σ 0/1/2/3, frö 1. Bursttoppen är `(blank-sync)/4`, alltså 2 respektive 3 koder; inte fasta fyra. Endast befintlig gain-tabell `WHITE_X8=31` används här. Burstloopens kontrollvärde redovisas separat från den verkliga avkodade kulöravvikelsen.

Det frysta målet före rättad mätning: varje stapels medelfärgvektorfel högst 16 koder och medelkulörfel högst 10° vid brus 0, med verkliga bildord på alla staplar. Det ändrades inte efter utfallet.

| Skala | Brus σ | Bildord | Chroma RMS, koder | Kulör RMS, ° | Största medelvektorfel |
|---|---:|---:|---:|---:|---:|
| 23/31/62 | 0 | 28 080 | 10,69 | 6,41 | **28,27** |
| 23/31/62 | 1 | 28 080 | 20,32 | 15,39 | 33,21 |
| 23/31/62 | 2 | 28 080 | 21,22 | 15,89 | 36,06 |
| 23/31/62 | 3 | 26 280 | 26,85 | 31,06 | 43,02 |
| 13/25/50 | 0 | 115 560 | 7,20 | 5,44 | **5,21** |
| 13/25/50 | 1 | 115 560 | 8,94 | 6,74 | 5,52 |
| 13/25/50 | 2 | 28 080 | 18,51 | 14,44 | 4,38 |
| 13/25/50 | 3 | 28 080 | 21,95 | 17,08 | 6,47 |

Olika antal bildord beror på när fångsten låser och hittar vertikalsynken. Från 115 560 till 28 080 är en täckningsförlust, inte förbättrad färg. Låstid, markörer och samtliga stapelvärden finns i JSON-kvittot. Medelvärden kan dölja brus: se också RMS-kolumnerna.

## Varför målet missas

Vid 23/31/62 lämnar vitt bara en kod till taket 63. Den syntetiska gula stapelns bärvåg klipper: 40 557 aktiva sampel klipps redan före det tillagda bruset. Gul får i medel Cb 44,11 där sanningen är 16; Cr 143,01 mot 146. Det är främst för låg färgmättnad, inte en stor medelkulörvridning. Ingen signal som redan klippts beskrivs som fullständigt återställd av packningsrättningen.

Vid 13/25/50 klipper inga aktiva sampel före brus och färgmålet klaras (största medelkulörfel 2,49°). Men samma fasta gain-tabell ger bara 11,03 dB luma-SNR mot den syntetiska fullnivåsanningen, jämfört med 19,48 dB vid första skalan. Ett godkänt färgmått är alltså inte ett godkänt totalbildmått. Verklig vitnivå och kontrast kräver känd testbild; sparade kameraklipp räcker inte för att fastställa dem.

Källan använder utkastets uttryckliga polära Cb/Cr-modulationskonvention med chromaamplitud 0,35 av vitt–släckning. Den syntetiska strömmen har självständiga sampel på 40 MHz-rutnätet; PARLIO:s dubblerade sampel och fel på bussen ingår inte i denna matris. Det är ett isolerat syntetiskt test av fas, invers och ordformat, inte en full elektrisk NTSC-sändarmodell eller ett bevis på att samma klippning finns på bänken. Modellen behöver därför mätning av ett känt färgmönster och kontroll av parströmmens färg innan dess amplitudkalibrering blir FPGA-underlag.

## Kontroller och nästa steg

19 riktade modelltester kontrollerar den oberoende färgsanningen, inversens båda radlängder, bytes under 128, sista raden, identiska original-Y/markörer, fel gain, comb av, burst av med okänd källfas, och att tom bild eller klippt skala inte får falskt godkänt kvalitetsbetyg. Slutlig fil gav **19 PASS på 19,431 s**. Den obligatoriska snabbsviten gav **720 begärda PASS i 458 processer, 321,895 s driver**, med 4 794 oförändrade käll-/runtime-/helperbindningar. Root återläste exakta nodidentiteter och utfall; interna fixtureutfall läggs inte till de 720. Ingen fullsvit eller Core-mainmerge.

Första quick-försöket stoppade i collection på en syntaxmiss i en kommentarrensning, före alla simuleringstester. Originalfil och fellogg är bevarade. Efter rättningen kördes syntaxkontroll, första faktiska quick och därefter de riktade testerna på slutlig fil. De ursprungliga mätningarnas beräkningsfunktioner jämfördes också med den hashbundna rena mätversionens AST; resultatmåtten ändrades inte av kommentarrensningen. Ett misslyckat försök att återskapa en mellanversions exakta kommentarbytes används inte som evidens. Maskinläsbart resultat: [COLOUR_MODEL_2026-11-05.json](COLOUR_MODEL_2026-11-05.json).

Originalutkast och första körningars resultat är bevarade privat; inga gamla jobb återstartades. Det här ersätter inte en RTL-/modelljämförelse och innehåller inget färgbygge eller någon flashning. Ändra inte FPGA-gain eller C5-firmware enbart på dessa syntetiska nivåer.

Nästa värdefulla jämförelse utan kortet är IQ-modellen i #28. För färgspårets fortsättning behövs känt färg-/gråmönster, faktisk busskala, burstamplitud och klippmarginal. PAL och två mottagares färgfas/diversity är fortfarande oprövade.

```sh
.venv/bin/python gateware/model/colour_demod_ref.py --json /tmp/colour-matrix.json
.venv/bin/python -m pytest -q gateware/model/test_colour_axes.py gateware/sim/test_colour_demod.py
```
