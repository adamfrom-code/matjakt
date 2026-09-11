// ---------------------------------------------------------------------------
// VILKEN BUTIK APPEN VISAR
//
// `cheapestBranch()` byggde en EGEN VECKOPLAN PER NÄRBUTIK: en fullständig
// kombinationssökning (30-40k kombinationer för en sjudagarsvecka, säger
// koden själv) plus en `shoppingListCost` för varje filial. Med tio filialer
// blev det 300-400k kombinationer - och `branchCache`-nyckeln bar
// `state.budget`, så budgetfältets lyssnare körde hela svängen PER
// TANGENTTRYCK.
//
// Allt det arbetet slängdes. Veckoplanen användes till exakt två saker: ett
// `total` som ingen läste, och ett "gick det att bygga en vecka alls?" som är
// samma svar för varje filial (planeraren tar emot en butik men läser den
// aldrig). Sorteringen som faktiskt avgör vilken butik det blir har hela
// tiden varit AVSTÅNDET.
//
// Så butiksvalet är vad det alltid var: närmaste butik - och med Premium
// närmaste butik av den kedja serverns egen jämförelse krönt till billigast.
// Ingen kombinatorik, inga recept, ingen budget. Modulen kan inte ens se ett
// recept, vilket är själva poängen: samma indata kan inte ge olika butik.
// ---------------------------------------------------------------------------

// Den enda del av valet som behöver receptbanken är frågan om det går att
// bygga en vecka över huvud taget. Faller den, finns ingen butik att visa -
// precis som förut, när noll kandidater gav noll filialer kvar efter filtret.
export function canPlanWeek(candidateCount, dinners) {
  return candidateCount > 0 && dinners > 0;
}

const branchDistance = (branch, distanceTo) => {
  const measured = distanceTo ? distanceTo(branch) : null;
  return Number.isFinite(measured) ? measured : (Number.isFinite(branch.avstandKm) ? branch.avstandKm : Infinity);
};

// Stabil sortering på avstånd. `Array.prototype.sort` är stabil i alla
// motorer vi bryr oss om, men stabiliteten gäller INDATAORDNINGEN - och två
// filialer på exakt samma avstånd ska inte kunna byta plats mellan två
// anrop. Därför avgörs oavgjort på filialens egen identitet.
const byDistanceThenIdentity = distances => (a, b) =>
  distances.get(a) - distances.get(b) || identity(a).localeCompare(identity(b));

const identity = branch => String(branch.primatKey || branch.externalStoreId || branch.namn || "");

export function chooseBranch({ branches = [], chain = null, position = null, distanceTo = null,
                               premium = false, cheapestChain = null, hasMenu = true } = {}) {
  if (!hasMenu) return null;
  const eligible = branches.filter(branch => !chain || branch.kedja === chain);
  if (!eligible.length) return null;

  const distances = new Map(eligible.map(branch => [branch, branchDistance(branch, distanceTo)]));
  const withDistance = branch => ({ ...branch, avstandKm: distances.get(branch) });

  // Utan Premium delar alla filialer samma schablonpris (ingen riktig
  // kedjedata finns förrän livepriser hämtats, vilket sker först efter att en
  // vecka valts). Att sortera det på "total" vore ett godtyckligt oavgjort -
  // precis så ett felaktigt "X är billigast" uppstår. Avståndet avgör, och
  // appen påstår aldrig att det är billigast.
  const nearest = pool => withDistance([...pool].sort(byDistanceThenIdentity(distances))[0]);
  if (!premium) return nearest(eligible);

  // Premium: serverns egen jämförelse (riktiga priser, riktiga
  // täckningsspärrar - se compare_chains) avgör vilken KEDJA som är
  // billigast; närmaste filial av den kedjan vinner.
  const ofWinner = cheapestChain ? eligible.filter(branch => branch.kedja === cheapestChain) : [];
  return nearest(ofWinner.length ? ofWinner : eligible);
}

// Cache-nyckeln bärs av EXAKT det valet beror på. Budgeten står inte med -
// den kan inte längre påverka vilken butik det blir, och det är hela
// skillnaden mot att räkna om 300-400k kombinationer per tangenttryck.
// Serverns billigaste kedja står med, vilket den inte gjorde förut: en ny
// jämförelse kunde landa utan att butiksvalet någonsin hörde talas om den.
export function branchChoiceKey({ branches = [], chain = null, position = null,
                                  premium = false, cheapestChain = null, hasMenu = true,
                                  pinned = null } = {}) {
  return JSON.stringify([branches.map(identity), chain, position, premium,
                         cheapestChain, hasMenu, pinned]);
}
