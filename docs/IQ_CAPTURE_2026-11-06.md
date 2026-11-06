# IQ till kompositdekoder: rätt radformat räcker inte

Uppgift 75, från Core `81a448c` och PLL-utkastet i PR #32. Ingen ursprunglig modell eller något predikat ändras. Vi provar den befintliga pulsbredds- och periodföljande dekodern efter IQ-demodulering; det ersätter inte det missade slicermålet i Core #28.

## Fryst bildkedja

Två NTSC-ramar: 1 050 källrader från rad 1 med åtta gråstaplar. FS 40 MS/s, deviation 2,8 MHz/V, kanal 12 MHz, video-LP 4,2 MHz och seed 1. Samma kvantiserade IQ-array till båda demodulatorerna per brusfall och bitdjup. Varje brusfas startades separat efter granskning av föregående fas.

Den befintliga nominella skalan round(22+0,22*IRE), klippt till 0..63, matar Python-heltal till originalets Capture(comb=True,avg=8,white_x8=20,boot_check=True). Ingen sanningsstyrd nivåjustering, tidssökning eller ny tröskel. Det är inte en fysisk C5-kalibrering. PLL-koefficienterna är oförändrade från uppgift 74.

En strukturellt giltig rad har 360 ord med index 0..359, rätt fält-/radtagg inom raden, bad=0 och markörlängd 1716±2. Pixel-RMSE använder alla 720 Y-värden mot kända staplar, utan medelvärdesborttagning eller efterhandsjustering. Pixelkolumnen kräver dessutom rad-RMSE <16 Y-koder, fryst före första kontrollen.

| Fall | Demodulator | Hela rader | Giltig struktur | Struktur och pixelbudget | RMSE, alla hela rader |
|---|---|---|---|---|---|
| clean | bypass | 972 | 972 | 972 | 4.702 |
| clean | adjacent7 | 972 | 972 | 972 | 4.756 |
| clean | gated7 | 972 | 972 | 972 | 4.557 |
| clean | wrong_sign7 | 3 | 3 | 0 | 72.227 |
| cn4 | adjacent4 | 1 | 1 | 0 | 129.682 |
| cn4 | gated4 | 16 | 3 | 0 | 115.297 |
| cn4 | adjacent7 | 2 | 0 | 0 | 115.448 |
| cn4 | gated7 | 11 | 3 | 0 | 108.792 |
| cn8 | adjacent4 | 18 | 5 | 0 | 106.754 |
| cn8 | gated4 | 16 | 7 | 0 | 107.768 |
| cn8 | adjacent7 | 15 | 4 | 0 | 92.641 |
| cn8 | gated7 | 6 | 5 | 0 | 78.230 |
| cn12 | adjacent4 | 16 | 6 | 0 | 75.428 |
| cn12 | gated4 | 20 | 3 | 0 | 84.063 |
| cn12 | wrong_sign4 | 0 | 0 | 0 | inga pixlar |
| cn12 | adjacent7 | 140 | 134 | 0 | 44.866 |
| cn12 | gated7 | 50 | 50 | 0 | 32.745 |

De rena bypass-, fasdifferens- och PLL-fallen ger 972 hela giltiga rader med båda fältfaserna och cirka 4,6–4,8 koders RMS-fel. Alla dessa rader klarar pixelbudgeten. Fel looptecken lämnar bara 3 rader med 72,2 koders fel: en faktisk semantisk negativ kontroll.

Vid 4, 8 och 12 dB klarar ingen rad både struktur och pixelbudget. PLL:n ger ibland lägre fel eller fler rader, men det är inte en återvunnen bild enligt det frysta kvalitetsmåttet. Radformat, låsflagga och pixelinnehåll måste redovisas separat. Vi har inte flyttat gränsen efter resultaten.

## Verifiering

Alla fyra modellfaser avslutades rc0 utan signaler, timeout eller omkörningar: 17 fall på sammanlagt 68,500 s driver. Råa ord och markörer är sparade i ett fast 16-byteformat. En separat stdlib-granskare, utan producentimporter, återläste ordning, taggar, index, neutral chroma, markörlängder och pixelkvadratsummor mot en egen stapelformel. Filerna innehåller tillsammans 18 794 701 byte inklusive fasernas JSON-kvitton.

Tio riktade adapter-/skadekontroller PASS på 0,10 s: bland annat saknade/bytta ord, fel pixel/chroma, fel markör och ej stängd slutrad. Snabbsviten ger 720 begärda PASS i 458 testenheter, 303,987 s driver. Alla 4 824 bundna käll-/runtime-/hjälpar-/rådatafiler var oförändrade under körningen. Inga ursprungliga IQ-, PLL-, Capture-, RTL-, test- eller byggfiler ändras; tilläggen är modelladapter, audit och dess test.

## Vad detta inte visar

Gråstaplarna är identiska mellan rader och ramar. Pixelmåttet verifierar därför inte att en utmatad fält-/radtagg motsvarar rätt källtid. Källans två ramar innehåller 974 aktiva rader. De rena fallen ger 972 stängda utmatade rader och slutar med ytterligare 360 ord utan markör; dessa ord sparas men räknas inte som en hel rad. Skillnaden mot källans radantal kan inte tillskrivas en viss källrad utan tids- eller radkodad sanning. RMSE-kolumnen gäller alla hela rader, även dem med ogiltig markör, medan pixelbudgetkolumnen kräver giltig markör också.

Brusfallen omfattar andra, längre IQ-arrayer än 60-radersmatrisen i uppgift 74. Deras slicerpoäng sparas separat och ersätter inte de gamla. Ett frö vid tre C/N-punkter fastställer ingen känslighetströskel. Inga färg-, rörelse-, FPGA-, RF-, fysisk ADC- eller hårdvaruanspråk. Fullsvit och Core-mainmerge ingår inte.

Nästa orsak att undersöka är hur uppstartens puls-/nivåval reagerar på dessa strömmar. Avvisningsräknare och låsspår visar inte ensamma orsaken. En eventuell separat instrumentering måste läsa samma oförändrade tillstånd och indata; att stänga av skydd för fler gröna utfall är inte en lösning.

Kör ett nytt rent kontrollpaket med `.venv/bin/python gateware/model/iq_capture_audit.py --out NEW_DIR`; brusfaser med `--cn 4`, `--cn 8` eller `--cn 12`. Befintlig outputkatalog vägras.
