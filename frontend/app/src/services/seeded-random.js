// ---------------------------------------------------------------------------
// SLUMPEN SOM GÅR ATT UPPREPA
//
// Receptvalet behöver slump: utan den gav "Skapa ny vecka" exakt samma vecka
// varje gång. Men slumpen låg i `Math.random()` mitt i en rankningsfunktion
// som kördes om vid varje omritning - och då blev samma indata olika svar.
// I en app vars hela löfte är "vem är billigast" är det inte en
// prestandafråga utan en trovärdighetsfråga: två identiska frågor ska ge
// samma svar, annars är svaret inte ett svar.
//
// Lösningen är inte att ta bort slumpen utan att BESTÄMMA den. Ett frö dras
// en gång per "skapa vecka"-tillfälle; allt som händer inom det tillfället
// läser samma ström och går därför att upprepa exakt. Nästa gång användaren
// ber om en ny vecka dras ett nytt frö, och då ÄR det en ny fråga.
//
// mulberry32: 32 bitars tillstånd, jämn fördelning, fyra rader. Det här är
// inte kryptografi - det är "samma frö, samma vecka".
// ---------------------------------------------------------------------------

export function createSeededRandom(seed) {
  // Frö 0 skulle låsa strömmen vid noll; 1 är lika godtyckligt och rör sig.
  let state = (seed >>> 0) || 1;
  return function random() {
    state = (state + 0x6D2B79F5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Fröet för NÄSTA tillfälle. Det enda stället i receptvalet där en riktig,
// obestämd slump hör hemma - och det körs en gång per vecka användaren ber
// om, inte en gång per tangenttryck.
export function newSeed(random = Math.random) {
  return (random() * 0x100000000) >>> 0;
}
