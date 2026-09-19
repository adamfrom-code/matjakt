// AA1 · RESTER - vad som blir över när färre äter än det lagas för.
//
// Roadmapens AA: ingen restportion, ingen "resten av gårdagens" i
// planeraren. Grunden här är REN aritmetik på det appen redan vet: listan
// och priset räknas för hela hushållet (portionFactor(state.personer)), och
// T1 vet hur många som faktiskt äter hemma per dag. Skillnaden är rester.
//
// Ingen gissning om hållbarhet eller om vad som "brukar bli över": över
// blir exakt kokta − ätna portioner, och rester räknas bara till NÄSTA dag.
// Modulen ritar inget och rör inget tillstånd; AA2 kopplar den till Veckan
// bakom flaggan vecka.rester.

/**
 * @param weekPlan  veckans recept-id per dag (null/undefined = tom dag)
 * @param people    hushållet - så många det lagas för (state.personer)
 * @param presence  T1: så många som äter hemma per dag (null = alla)
 * @returns en rad per dag: { index, lagas, kokta, atna, over, resterFran, rackerImorgon }
 */
export function resterPlan({ weekPlan = [], people = 2, presence = [] } = {}) {
  const dagar = Math.max(7, Array.isArray(weekPlan) ? weekPlan.length : 0);
  const hushall = Math.max(1, Number(people) || 1);
  const atna = i => {
    const egen = Array.isArray(presence) ? presence[i] : null;
    const n = Number(egen);
    return egen != null && Number.isFinite(n) && n >= 1 ? Math.min(hushall, Math.round(n)) : hushall;
  };
  const rader = [];
  let over = 0;                       // portioner kvar från igår
  for (let i = 0; i < dagar; i += 1) {
    const lagas = Boolean(weekPlan?.[i]);
    const ater = atna(i);
    const kokta = lagas ? hushall : 0;
    const resterFran = over > 0 ? i - 1 : null;
    // Rester från igår räcker till hela dagens ätare: dagen kan vara en
    // "resterdag" - ingen ny rätt behövs. Räcker de inte, äts de upp ändå
    // (och tas inte med vidare - rester är en dags sak).
    const rackerImorgon = lagas && kokta - ater >= atna(i + 1) && atna(i + 1) > 0 && i + 1 < dagar;
    rader.push(Object.freeze({ index: i, lagas, kokta, atna: ater, over: lagas ? Math.max(0, kokta - ater) : 0,
                               resterFran, resterRackerHelaDagen: over >= ater && over > 0, rackerImorgon }));
    over = lagas ? Math.max(0, kokta - ater) : 0;
  }
  return Object.freeze(rader);
}

/** Dagar där resterna räcker till alla som äter - kandidater för "resterdag". */
export function resterDagar(plan) {
  return plan.filter(r => r.resterRackerHelaDagen).map(r => r.index);
}

/** En läsbar rad för en dag, eller "" när inget är att säga. */
export function resterText(rad, plural = (n, a, b) => `${n} ${n === 1 ? a : b}`) {
  if (!rad) return "";
  if (rad.resterRackerHelaDagen) return "Rester från igår räcker";
  if (rad.over > 0) return `${plural(rad.over, "portion", "portioner")} över`;
  return "";
}
