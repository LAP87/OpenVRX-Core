# Parade sampel och tappade fält, Core #29

Modellundersökning från `a6e3c2b`, 2026-11-05. Inga RTL-ändringar eller nya hårdvaruprov. `Capture()` behåller originalalgoritmen; `robust_pulses=True` är ett avstängt modellförslag som ännu inte finns i FPGA:n.

## Baslinjen och händelsen som tappar fältet

Originalexperimentet i #29 reproducerades med sex frön, en syntetisk NTSC-bildruta, nivåerna 23/31/62 och brus σ=2. `pair_stream` behåller varannat sampel och upprepar det; strömmens längd och tidsbas är oförändrade. Det är syntetiskt brus, inte en inspelning av fysisk kontinuitet.

| Frö | Original, oparad | Original, parad | Modellförslag, parad |
|---|---:|---:|---:|
| 1 | 87 480 | 84 600 | 87 480 |
| 2 | 87 480 | 86 400 | 87 480 |
| 3 | 87 480 | 0 | 87 480 |
| 4 | 87 480 | 0 | 87 480 |
| 5 | 87 480 | 85 680 | 87 480 |
| 6 | 87 480 | 85 320 | 87 480 |

Siffrorna är antal bildord, inte bildkvalitet. Efter uppstarten återstår 243 aktiva rader à 360 ord i denna enbildrutasimulering; det första fältets vertikalsynk passerar innan svepet låst. Det finns 242 markörer: den sista radens markör kommer först vid nästa radstart, utanför klippet. Modellen ger därför inte två fullständiga fält med detta stimulus.

Spåret från originalmodellen visar följande vid andra fältets vertikalintervall:

- Frö 3, källrad 267: den oparade strömmens accepterade puls var 1 083 klockor. På den parade strömmen delades den i en första accepterad puls om 263 och en efterföljande om 820. Den senare låg utanför radkantens fönster och räknades inte som radens puls.
- Frö 4, samma källrad: 1 081 klockor oparat, men först 492 och sedan 587 parat. Varken den första accepterade pulsen eller nästa rads första puls nådde breddgränsen 600.
- Utan accepterad bred puls växlade fältbiten aldrig. `countdown` stannade på −1 och inga rader numrerades, trots fortsatt horisontallås.
- När en sönderbruten bred puls felklassades som vanlig synk uppdaterades även släckningsnivån från ett fönster som fortfarande låg i synken. Frö 3:s släckning föll från 31 till 27, frö 4:s till 26. Detta följdfel ökade fragmenteringen.

De parade brusvärdenas korrelation är en rimlig förklaring till fler tröskelpassager. Den observerade orsaken till just nollorden är däremot den missade bredpulsen och den uteblivna fältstarten; ingen uppmätt varianskvot eller generell RF-förbättring påstås.

## Avstängt modellförslag

Behåll medelvärdesfönstret, den stigande pulsens startpunkt och breddgränserna. Bekräfta i stället pulsens slut först efter 16 höga medelvärden i rad, men bara om en 4 096-klockors ruta bekräftat identiska sampelpar på en paritet och minst 16 ändringar på den andra. En platt ström är inte bevis för parstruktur. Nytt fönster utan bevis återgår till tre höga värden.

16 klockor är 0,4 µs vid modellens 40 MHz, under den 4,7 µs långa normala synkpulsen och serrationsgapet. De extra klockorna som väntar på pulsens slut får inte räknas som extra låg pulsbredd: klassificeringen behåller originalets högst två efterföljande höga klockor. Ett tröskelnära kort pulstest kontrollerar detta.

Första förslaget med åtta klockor återställde båda tappade fälten men lämnade en saknad rad för frö 5. I den radens stabila synkdel finns ett åtta klockor långt högt avbrott i medelvärdesjämförelsen (start vid sampel 719 524). Det förklarar varför åtta fortfarande avslutar pulsen. Ett första ovillkorligt 16-förslag återställde alla sex frön men ändrade även den gamla råfångsten och underkändes av kontrollen. Den bekräftade parstrukturen är därför en uttrycklig gräns för det slutliga förslaget, inte ett byte av kontrollens förväntningar.

## Kontroller och begränsningar

- Originalets sex felutfall finns kvar som regression och negativ kontroll. Förslaget ger 243 rader, 360 ord per rad och ordindex 0–359 på varje rad, lås och bekräftade sampelpar.
- En ren, oparad kompositbildruta behåller exakt alla ord, markörer och låsväxlingar när förslaget slås på.
- Originalets bootstrapfall med 30 rader nivå 50 och två kopior av den riktiga 12:51-fångsten behåller exakt ord, markörer, låsväxlingar, bootstrapavvisningar och slutnivåer.
- `vectors/ntsc_clean_frame.hex`, som ärendet nämner, är 902 616 byte BT.656-data från `make_vectors.py`, inte sexbitars kompositsampel (725 514 värden över 63). Båda modellvarianterna ger noll utdata på den filen. Detta kontrolleras som formatgräns och räknas inte som bildtäckning; det rena kompositfallet ovan är bildkontrollen.
- Båda pariteterna, förlorat parbevis, platt insignal och kort/bred puls runt 600-gränsen har egna kontroller.
- Sex extra frön 7–12, valda efter sexfrödiagnosen, gav alla 87 480 ord både oparat och parat med den slutliga pargrinden. Ingen justering gjordes efter dessa utfall.

Förslaget är inte en allmän brusgaranti. Fel i den andra sampelkopian, skiftande parfas mitt i en puls, andra brusmodeller, PAL, verklig RF, bildkvalitet och hårdvaruresurser är inte verifierade. Att en råfångst behåller sina utdata bevisar inte dess fullständiga fälthistoria. En senare RTL-uppgift behöver eget modellkontrakt, negativ kontroll och berört bygge; ingen sådan merge eller flashning ingår här.

## Reproduktion

```sh
.venv/bin/python gateware/model/paired_noise_audit.py --out /tmp/noise-original.json
.venv/bin/python gateware/model/paired_noise_audit.py --robust-pulses --out /tmp/noise-proposal.json
.venv/bin/python -m pytest -q gateware/model/test_paired_noise.py
```

Auditkommandot använder stdlib och vägrar skriva över en befintlig resultatfil. Resultatet innehåller ord-/markörantal, hash av alla emitterade entries, låsväxlingar, per-radnivåer, pulsbreddshistogram och pulserna i vertikalintervallen. Filen är modellspårning, inte RTL- eller hårdvaruevidens.

Verifiering av slutlig kod: **14 riktade modelltester PASS på 21,673 s**, därefter **720 begärda snabbsvitutfall PASS i 458 processer på 324,646 s**. Root återläste de exakta 720 nodidentiteterna och deras utfall separat från eventuella interna fixturekörningar. 4 790 käll-/runtime-/helperbindningar var oförändrade före och efter snabbsviten och vid rootgranskningen. Python 3.12.12, pytest 9.1.1 och befintlig lokal Icarus användes; inget installerades. Maskinläsbart kvitto: [PAIRED_NOISE_2026-11-05.json](PAIRED_NOISE_2026-11-05.json).

Hela sviten och syntes/routning ingår inte i modelluppgiften. Ingen Core-merge till `main` påstås av denna rapport; fullsviten krävs före sådan merge.
