// Sparhistoriken: en post per vecka, aldrig en per klick.
//
// VARFÖR DEN HÄR FINNS. Posten skrevs förut med en push() rakt in i listan
// varje gång användaren tryckte "Välj den här". Öppnade man jämförelsen tre
// gånger och valde varje gång blev det tre poster - och renderStats
// summerar posterna, så samma vecka räknades som tre veckors besparing.
//
// NYCKELN ÄR VECKANS RÄTTER, INTE DAGENS DATUM. Byter man vecka samma dag
// är det en ny handling och ska bli en ny post. Väljer man om exakt samma
// vecka är det inte en ny handling, hur många gånger man än trycker.
//
// VAD DEN INTE LÖSER. Posten skrivs fortfarande när veckan VÄLJS, inte när
// den handlats. Att skilja möjlig, planerad och genomförd besparing åt är
// resten av F4 och kräver att avbockningsflödet skriver historiken - se
// docs/MASTER_BACKLOG.md.

export function weekKeyFor(recipeIds) {
  return [...(recipeIds || [])].sort().join("|");
}

export function recordWeekSaving(log, entry) {
  const list = Array.isArray(log) ? [...log] : [];
  const index = list.findIndex(existing => existing.weekKey === entry.weekKey);
  if (index >= 0) list[index] = entry;
  else list.push(entry);
  return list;
}
