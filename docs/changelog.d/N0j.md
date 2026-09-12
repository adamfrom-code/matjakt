---
paket: N0j
titel: Vävningen prövas mot den riktiga katalogen
---

`tests/changelog.test.js` byggde upp ett eget litet repo i `/tmp` med två
påhittade fragment och vävde det. Det prövar vävningens **logik**, och gör
det bra — men säger ingenting om filerna som faktiskt ligger i
`docs/changelog.d/`.

Följden: tre fragment (N0d, N0e, N0f) låg på main utan front matter, och
`weave_checkpoint.mjs` kastar för **hela** katalogen om en enda fil saknar
det. Ingen releasevävning gick att köra. CI var grön hela tiden.

Nu körs skriptet mot repot som det står, plus en kontroll per fil som pekar
ut vilken fil som är trasig i stället för att stanna på den första.
