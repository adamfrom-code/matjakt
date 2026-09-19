---
paket: AO1
titel: Mobil ergonomi — fält som inte får iOS att zooma, och tryckytor på 44 pt
---

Granskning i 375 px viewport (DOM-mätt, inte skärmdump — skärmdumparna i
panelen var opålitliga: panelen är ~420 px hög och fixerade element följer
den synliga ytan, så "tabraden mitt på skärmen" och "tomma Recept-vyn" var
emuleringsartefakter, dokumenterade och släppta).

Verkliga fynd, nu åtgärdade i `styles.css` under `@media (max-width:480px)`:

- **iOS zoomar in vid fokus** på fält med typsnitt under 16 px: sökfältet
  (15 px), recept-filtren (13 px), "Lägg till vara" (15 px), onboardingens
  budgetfält (15 px), kodfältet. Nu 16 px på telefonbredd; desktop orörd.
- **Tryckytor:** dagens ＋ i Veckan var 34 px bred (nu 44), receptchipsen
  32 px höga (nu minst 40 i en rullande rad).

Inte fel, noterat: filterraden i Recept rullar i sidled (kcal-selecten
klipps vid kanten som rullhint, "Favoriter" nås genom att rulla);
kapitäler på 9,5–10 px i Inställningar och etiketter är ett designval men
små. Onboardingens ark på 375×667: 400 px högt, "Hoppa över" inom skärmen,
24 px under det är arkets safe-area-marginal — inget tomrum, inget som
klipps.

E2E `test_mobil_ergonomi.py` läser datorns beräknade stil i 375 px och i
1024 px: fälten ≥ 16 px, chip ≥ 40, ＋ ≥ 44 — och desktop exakt som förut.
