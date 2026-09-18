# Bildstatus — vad källan säger att fotot visar

Genererad av `backend/scripts/bildstatus.py`. Redigera inte för hand — kör skriptet.

| status | antal | betyder |
|---|---|---|
| MISSING | 11 | ingen bild i källan |
| REJECTED | 52 | källan säger att fotot visar något annat, eller ett generiskt foto, eller delas av rätter med olika protein |
| EXACT-KANDIDAT | 62 | fotografens titel nämner rättens protein eller rättterm — bekräftas med ögat |
| GOOD_VARIANT-KANDIDAT | 54 | delas av recept med samma rättyp; högst ett kan vara EXACT |
| NEEDS_REVIEW | 51 | titeln avgör inte |

## Alt-texten är inget bevis

`imageAlt` är genererad ur receptnamnet (*"<namn> upplagd på tallrik"*). Samma foto bär därför olika alt-texter som påstår olika rätter. Den ska inte användas som evidens och bör i P09b ersättas med källans egen beskrivning eller *"Foto: <källa>"*.

## REJECTED, med bevis

| id | namn | skäl |
|---|---|---|
| `bonbowlmatvete` | Bönbowl med matvete och salsa | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `currykottfarsgryta` | Currykryddad köttfärsgryta | delas av 5 recept med olika huvudprotein (färs, kyckling) |
| `halloumibowl` | Halloumibowl med rostade grönsaker | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `korvgratang` | Korvgratäng med pasta | delas av 5 recept med olika huvudprotein (fläsk, färs, korv, kyckling) |
| `kycklingmatvete` | Kryddig kycklingbowl med matvete | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `kycklinggryta` | Kycklinggryta med ris | delas av 5 recept med olika huvudprotein (färs, kyckling) |
| `laxsallad` | Laxsallad med matvete och dill | delas av 2 recept med olika huvudprotein (fisk, kyckling) |
| `rotfruktsgratang` | Rotfruktsgratäng med rökt falukorv | delas av 5 recept med olika huvudprotein (fisk, fläsk, korv) |
| `svartbonsbowl` | Svartbönsbowl med matvete | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `tacobonor` | Tacobowl med svarta bönor | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `vegofarsgryta` | Vegofärsgryta med ris | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `kottbullar-potatismos` | Köttbullar med potatismos och lingon | fotot visar en köttbit ("fried meat cutlet served with boiled potatoes and salad"), rätten är färs |
| `tacos-kottfars` | Tacos med köttfärs och krispiga grönsaker | generiskt matfoto ("close up of tacos with assorted fillings and sauce") - visar ingen bestämd rätt |
| `kottfarslimpa-graddsas` | Köttfärslimpa med gräddsås | fotot visar ägg ("delicious meatloaf with egg and zesty potatoes"), rätten är färs |
| `kvargbowl-kyckling` | Kycklingbowl med kvarg och matvete | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `aggrora-bacon-bonor` | Äggröra med bacon och vita bönor | fotot visar ägg ("egg omelet on blue and white ceramic plate"), rätten är fläsk |
| `korvgryta-potatis` | Korvgryta med potatis och paprika | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `bonsoppa-tomat` | Bönsoppa med tomat och vitlök | delas av 2 recept med olika huvudprotein (korv, vego) |
| `potatisgratang-skinka` | Potatisgratäng med skinka | delas av 5 recept med olika huvudprotein (fisk, fläsk, korv) |
| `raggmunk` | Raggmunk med fläsk och lingon | fotot visar fisk ("fresh salmon on white ceramic plate"), rätten är fläsk |
| `fiskgratang-dill` | Fiskgratäng med dill och räkor | delas av 5 recept med olika huvudprotein (fisk, fläsk, korv) |
| `kycklinggryta-paprika` | Kycklinggryta med paprika och crème fraiche | delas av 5 recept med olika huvudprotein (färs, kyckling) |
| `gulaschgryta` | Gulaschgryta med potatis | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `kottfarssoppa` | Köttfärssoppa med rotfrukter | delas av 2 recept med olika huvudprotein (fisk, färs) |
| `fisksoppa-saffran` | Fisksoppa med lax och räkor | delas av 2 recept med olika huvudprotein (fisk, färs) |
| `kyckling-shawarma-bowl` | Kycklingbowl med ris och vitlökssås | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `kyckling-caesarsallad` | Caesarsallad med kyckling och krutonger | fotot visar ägg ("classic caesar salad with egg and parmesan"), rätten är kyckling |
| `kycklinggryta-honung-senap` | Kycklinggryta med honung och senap | delas av 5 recept med olika huvudprotein (färs, kyckling) |
| `svarta-bonor-tacos` | Tacos med svarta bönor och majssalsa | generiskt matfoto ("close up of tacos with assorted fillings and sauce") - visar ingen bestämd rätt |
| `biffbowl-teriyaki` | Teriyakibowl med strimlad biff | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `kottfarsgryta-bulk` | Köttfärsgryta med ris och svarta bönor | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `kassler-potatisgratang` | Kassler med potatisgratäng | fotot visar nöt ("steak and potato puree on a plate"), rätten är fläsk |
| `bonburgare` | Bönburgare med klyftpotatis | fotot visar fläsk ("hamburger on tray"), rätten är vego |
| `korvgryta-krossade-tomater` | Korvgryta med paprika och pasta | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `tacogratang` | Tacogratäng med tortillachips | delas av 5 recept med olika huvudprotein (fläsk, färs, korv, kyckling) |
| `pastasallad-kyckling-lunch` | Pastasallad med kyckling och pesto | delas av 2 recept med olika huvudprotein (fisk, kyckling) |
| `biffgryta-rotter` | Mustig köttgryta med rotfrukter och timjan | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `bulk-kyckling-jattebowl` | Bulkbowl med kyckling, ris och jordnötssås | fotot visar vego ("grains and beans on bowls"), rätten är kyckling |
| `laxpoke` | Pokébowl med lax och ris | generiskt matfoto ("close up of variety of rice in bowls") - visar ingen bestämd rätt |
| `krogarens-makaroner` | Stuvade makaroner med falukorv | fotot visar nöt ("delicious macaroni and ground beef dish"), rätten är korv |
| `torskgratang-vasterbotten` | Torskgratäng med ostsås och purjolök | delas av 5 recept med olika huvudprotein (fisk, fläsk, korv) |
| `sotpotatis-bulk-bowl` | Bulkbowl med färsbiffar och sötpotatis | fotot visar vego ("grains and beans on bowls"), rätten är nöt |
| `korvsoppa` | Korvsoppa med rotfrukter | delas av 2 recept med olika huvudprotein (korv, vego) |
| `kebabgryta` | Kebabgryta med ris | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `makaroner-kottbullar` | Makaroner och köttbullar | fotot visar nöt ("delicious macaroni and ground beef dish"), rätten är färs |
| `kramig-kycklinggryta` | Krämig kycklinggryta med grönsaker | delas av 5 recept med olika huvudprotein (färs, kyckling) |
| `kycklinggratang-broccoli` | Kycklinggratäng med broccoli | delas av 5 recept med olika huvudprotein (fläsk, färs, korv, kyckling) |
| `korvgryta-curry` | Korvgryta med curry | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `flaskgryta-paprika` | Fläskgryta med paprika | generiskt matfoto ("top view of cooking ingredients") - visar ingen bestämd rätt |
| `kottfarsgratang-mos` | Köttfärsgratäng med potatismos | delas av 5 recept med olika huvudprotein (fläsk, färs, korv, kyckling) |
| `broccoligratang-skinka` | Broccoligratäng med skinka | delas av 5 recept med olika huvudprotein (fisk, fläsk, korv) |
| `kassler-ananas-gratang` | Kasslergratäng med ananas och ris | delas av 5 recept med olika huvudprotein (fläsk, färs, korv, kyckling) |

## MISSING

`dillkott`, `morotsbiffar-tzatziki`, `lax-i-ugn-fetaost`, `torskrygg-ortstekt`, `krispiga-kikartor-bowl`, `stekt-flask-loksas`, `bruna-bonor-flask`, `flaskkotlett-artor`, `kycklingklubbor-klyftpotatis`, `fiskbullar-dillsas`, `pitepalt`

## Nästa steg (P09b, inte det här paketet)

1. `image_status` sätts ur `docs/bildstatus.json` vid import; REJECTED visar reservkortet. Hellre MISSING än fel bild.
2. EXACT-KANDIDAT och GOOD_VARIANT-KANDIDAT bekräftas med ögat och blir EXACT / GOOD_VARIANT / REJECTED.
3. Alt-texten byts mot källans beskrivning.
