# Mixer-prototyp (offline, Python)

Milstolpe M3 i `design/GATEWARE_PLAN.md`: utveckla och pröva en regel för radvis mixning av två mottagare **innan** den skrivs i FPGA-logik.

## Hypotes

Svag signal ger "snö", som höjer högfrekvensenergin längs en videorad. Per rad: ta mottagaren med lägst energi; byt bara när den andra är tydligt bättre (hysteres); medelvärdesbilda när båda är ungefär lika rena. Kommersiella mixers (RapidFire, Fusion, SteadyView) är opublicerade — detta är vår egen startpunkt och ska prövas mot riktiga inspelningar.

## Arbetsflöde

1. Två mottagare på **samma kanal** (t.ex. två USB-UVC-mottagare, `bom/GATEWARE_DEVKIT.md`), samma antenntyp, gärna olika placering/orientering.
2. `python mixer/capture_dual.py --list` → hitta enheterna. Sedan
   `python mixer/capture_dual.py --a 0 --b 1 --seconds 120 --out data/flyg1`
   Flyg nära, långt bort, bakom hinder, nära metall (multipath).
3. `python mixer/line_mixer.py data/flyg1_a.mkv data/flyg1_b.mkv --out data/flyg1_mix.mkv --stats data/flyg1.csv`
4. Jämför de tre videorna visuellt; `--stats` ger brusnivå per bild för A, B och mix samt andel rader från A/B/blandning. Justera `--blend-margin` och `--switch-margin`.

Inspelningarna justeras automatiskt: bildförskjutning i tid (ljusstyrkans tidsserie) och förskjutning i bilden (fasskorrelation per bild där varje kanals brusiga rader först repareras, median över bilder).

## Tester

`python -m pytest -q mixer` (syntetisk video med slumpmässiga snöskurar per kanal):
- mixern väljer den rena kanalen i > 95 % av raderna där bara den ena är störd, och felet mot facit blir under halva det bästa enskilda kanalens fel;
- rena kanaler blandas (> 90 % av raderna);
- tids- och bildförskjutning återfinns, även med snö (bildförskjutning inom ±0,5 pixel i testet).

## Begränsningar

- USB-mottagarna komprimerar troligen bilden; komprimering ändrar brusets utseende. Slutlig validering sker med okomprimerad BT.656 i FPGA:n.
- Valet görs per rad utan hänsyn till rörelse; snabba panoreringar kan ge annan HF-energi i de två kanalerna om de inte är perfekt synkade.
- Ingen färg (bara luma) i prototypen.
