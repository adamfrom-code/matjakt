// Vad veckan ANTAR att du redan har (U06).
//
// VARFÖR DEN HÄR FINNS. Varje recept bär en "hemma"-lista - salt, olja,
// kryddor - och de raderna prissätts aldrig och hamnar aldrig på
// inköpslistan. Antagandet syntes bara som en rad smått inuti ett UTFÄLLT
// receptkort, och det fanns ingen väg att säga att man faktiskt inte har
// olja. Den som lagar för första gången i ett nytt kök får då en lista det
// inte går att laga mat av, och ett pris som är för lågt av ett skäl ingen
// har berättat.
//
// SAMMA VARA I FYRA RECEPT ÄR ETT ANTAGANDE, inte fyra. Nyckeln är namnet i
// gemener, men stavningen som visas är den receptet självt använder - vi
// hittar inte på en egen normalform åt något användaren ska känna igen.

export function assumedHomeItems(recipes) {
  const namn = new Map();
  for (const recipe of recipes || [])
    for (const post of recipe?.hemma || []) {
      const rent = String(post ?? "").trim();
      const nyckel = rent.toLowerCase();
      if (rent && !namn.has(nyckel)) namn.set(nyckel, rent);
    }
  return [...namn.values()].sort((a, b) => a.localeCompare(b, "sv"));
}

export const ASSUMED_STATE = {
  OFFER: "offer", ON_LIST: "on_list", ADDED: "added", AT_HOME: "at_home",
};

// SAMMA NAMN KAN VARA BÅDA. Receptbanken har 21 varor som är antagna i ett
// recept och köpta i ett annat: Ris antas i 1 recept och köps i 50, Vitlök
// antas i 9 och köps i 70, Smör antas i 63 och köps i 16. En vecka med båda
// sorternas recept satte alltså varan på inköpslistan OCH erbjöd den här -
// ett dubbelköp med ett tryck. Därför vägs listan tyngst.
//
// Etiketten säger att varan KÖPS, inte att mängden räcker. Det antagna
// receptets del har ingen mängd alls (pantryStaple bär amount = null), så
// vi vet inte hur mycket extra det behövs - och att påstå något annat vore
// att gissa.
//
// Varan försvinner ALDRIG ur listan när den hanterats. Den som undrar
// "räknade ni med olja?" ska få samma svar oavsett vad hen redan gjort -
// annars blir en tom lista tvetydig: antog vi inget, eller är allt klart?
export function assumedState(namn, tillagda, iSkafferi, påListan) {
  const nyckel = String(namn ?? "").trim().toLowerCase();
  if (påListan?.has(nyckel)) return ASSUMED_STATE.ON_LIST;
  if (tillagda?.has(nyckel)) return ASSUMED_STATE.ADDED;
  if (iSkafferi?.has(nyckel)) return ASSUMED_STATE.AT_HOME;
  return ASSUMED_STATE.OFFER;
}
