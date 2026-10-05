# Latensrigg (glas-till-glas)

Mäter tiden från att en LED tänds framför FPV-kameran tills samma LED syns tändas på skärmen. Ingen specialutrustning: en blinkande LED, en mobil som filmar i 240 fps, och `analyze_latency.py`.

## Hårdvara

- **LED + 220 Ω** på valfri 3,3/5 V-utgång som blinkar med **slumpmässigt intervall** (300–700 ms), så att blinkningarna inte låser i fas med kamerans eller skärmens bildfrekvens. Valfri mikrokontroller du har (t.ex. LicheeRV Nano-kortens GPIO, ESP32, Arduino). Exempel för Arduino:

  ```cpp
  void setup() { pinMode(13, OUTPUT); randomSeed(analogRead(A0)); }
  void loop() { digitalWrite(13, HIGH); delay(random(150, 350)); digitalWrite(13, LOW); delay(random(300, 700)); }
  ```
- **Mobil med 240 fps slowmotion** (fast exponering om möjligt, inte autoexponering som "andas").
- FPV-kedjan som ska mätas.

## Uppställning

1. LED:en ca 10 cm framför FPV-kameran, i bildens **mitt**. Mät alltid mot samma ställe på skärmen — skärmar ritar uppifrån och ned, så en LED i bildens topp och botten ger olika tider (upp till en bild ≈ 17–20 ms).
2. Mobilen ska se **både LED:en och skärmen** i samma bild. Mörkt rum, skärmens ljusstyrka normal.
3. För XR-glasögon: filma genom ena okularet med mobilen tätt intill; placera LED:en så att den syns i bildens kant bredvid glasögonen.
4. Filma minst 30 blinkningar per konfiguration, två–tre klipp.
5. **Referens först:** mät Moneagle (direkt analog) med samma uppställning; mät sedan konverterare + glasögon. Skillnaden är vad kedjan lägger till.

## Analys

```bash
python tests/latency/analyze_latency.py klipp.mp4 --preview 100
```

Öppna `klipp.frame100.png` (rutnät med koordinater) och läs av rutorna för LED och skärm (x,y,bredd,höjd). Sedan:

```bash
python tests/latency/analyze_latency.py klipp.mp4 --capture-fps 240 --led 410,620,24,24 --screen moneagle=880,410,60,40 --csv resultat.csv
```

- `--capture-fps 240` behövs om mobilen sparar slowmotion som 30 fps (vanligt). Utan det blir allt 8× för långt.
- Flera `--screen` går att ange om två skärmar syns i samma klipp.
- **Parning:** först hittas kedjans totala fördröjning genom att korskorrelera LED:ens slumpmässiga på/av-mönster med skärmens. Sedan paras varje blinkning med högst en skärmblinkning inom ±20 ms (`--tolerance-ms`) från den fördröjningen. Varje skärmkant får användas en gång och kan inte ligga före LED-kanten. Det gör att även fördröjningar längre än blinkperioden mäts rätt. Om mönstret är tvetydigt (t.ex. regelbunden blinkning) avbryts analysen i stället för att ge en felaktig siffra. Sökområde: upp till 1 000 ms (`--max-delay-ms`).
- Namnlösa `--screen` får namnen screen1, screen2 …; dubbla namn avvisas.
- Tiden räknas vid **halv ljusstyrka** i rutan (interpolerat mellan bildrutor), vilket motsvarar ungefär "första ljusa fält" snarare än "första ljusa pixel".

## Noggrannhet

- Upplösning: en bildruta = 4,17 ms vid 240 fps; interpoleringen ger bättre än så men räkna med **±2 ms** per mätning.
- Spridningen (sd) visar kedjans egen variation (t.ex. konverterarens bildbuffert), inte bara mätfel.
- Rapportera alltid: kamera (PAL/NTSC), mottagare, konverterare + läge (720p/1080p), skärm/glasögon, antal mätningar, median och sd.

## Tester

`python -m pytest -q tests/latency` genererar syntetiska klipp med känd fördröjning (25, 50 och 500 ms) och kontrollerar att analysen hittar dem inom ±1 ms, inklusive slowmotion-fallet, två namnlösa skärmar och att regelbunden blinkning flaggas som tvetydig.

500 ms-fallet rättades 2026-10-01 efter Astras motexempel. En-till-en-parning och avvisad negativ fördröjning tillkom 2026-10-05; ett test låter två LED-kanter konkurrera om samma skärmkant.
