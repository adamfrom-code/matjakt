// ---------------------------------------------------------------------------
// FÖRSTA-VÄRDE-ÖGONBLICKET (G8)
//
// Ögonblicket är skärmen där veckan lämnas över: onboardingens sista knapp,
// "Skapa min vecka" på Hem, "Skapa ny vecka" i veckoarket. Regeln är en enda
// mening - DET FINNS INGET HÄNGLÅS PÅ EN LEVERANSSKÄRM. Sälj efter leverans,
// inte före.
//
// Halva regeln fanns redan: onboardingens sista knapp öppnade planjämförelsen
// där sju av åtta veckotyper var låsta, och den vägen är borta -
// finishOnboarding() kör chooseMenu() rakt till Vecka (src/views/account.js).
// Men butikskorten stod kvar. G13 flyttade butiksvalet till Vecka, och en ny
// användare som just svarat på fyra frågor möttes av "Var blir det billigast?"
// med två kort som sa *Se pris med Premium* - OVANFÖR veckan, alltså före
// sin första måltid. Hänglåsväggen hade inte försvunnit, den hade bytt plats.
//
// Under ögonblicket ritas bara den butik hon faktiskt har: hennes pris, hennes
// kröning, och spridningsraden ("Priserna skiljer sig med upp till 75 kr...")
// som säger sanningen utan att låsa något. Erbjudandet är inte borttaget - det
// kommer tillbaka i samma sekund hon navigerar vidare, och då ritas
// butikskorten om (se vyBytt).
//
// Ögonblicket lever bara i minnet, avsiktligt: en omladdning är ett nytt
// besök, och då är veckan inte ny längre.
// ---------------------------------------------------------------------------

// Nästa vybyte är leveransen själv (chooseMenu -> setView("week")), inte ett
// flikbyte. Utan den här skillnaden skulle ögonblicket avsluta sig självt i
// samma andetag som det började.
let levererar = false;

// Leveransskärmen visas just nu.
let visasNu = false;

/**
 * En vecka lämnas över till skärmen.
 *
 * `visasForAnvandaren` är chooseMenu:s `shouldScroll`: uppstarten bygger en
 * vecka i tysthet (`chooseMenu(false)`) bakom onboardingrutan utan att byta vy.
 * Det är ingen leverans - ingen ser den - och den ska därför inte tysta
 * butikskorten på den skärm hon råkar stå på.
 */
export function veckanLevereras(visasForAnvandaren = true) {
  if (!visasForAnvandaren) return;
  levererar = true;
  visasNu = true;
}

/**
 * setView-hook. Sant = ögonblicket tog slut och erbjudandet ska ritas om.
 *
 * Varje vybyte räknas, även ett tillbaka till Vecka: att trycka på en flik är
 * att navigera, och då är hon inte längre kvar i leveransen. Omritningen är
 * själva poängen med returvärdet - annars skulle korten sakna sina låsta
 * butiker ända tills något annat råkade rita om dem, och "råkade" är inget att
 * bygga ett gränssnitt på.
 *
 * Anroparen ska rita om DIREKT, inte lägga omritningen i en renderkö: vyn
 * hinner annars bytas medan korten fortfarande står filtrerade, och
 * erbjudandet kommer tillbaka en bildruta för sent.
 */
export function vyBytt(view) {
  if (levererar) {
    levererar = false;
    // Ankomsten till leveransskärmen, inte ett steg bort från den.
    if (view === "week") return false;
  }
  if (!visasNu) return false;
  visasNu = false;
  return true;
}

/**
 * Butikskorten utan hänglås under ögonblicket.
 *
 * Aldrig ner till noll kort: har hon bara låsta butiker är ett lås ärligare än
 * ett tomt "Var blir det billigast?" - då står korten kvar som de är.
 */
export function utanHanglas(entries) {
  if (!visasNu) return entries;
  const oppna = entries.filter(entry => !entry.locked);
  return oppna.length ? oppna : entries;
}
