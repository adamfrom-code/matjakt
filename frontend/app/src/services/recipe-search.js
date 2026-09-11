export function filterRecipes(recipes, query) {
  const normalized = String(query || "").trim().toLocaleLowerCase("sv");
  if (!normalized) return recipes;
  return recipes.filter(recipe => [recipe.namn, recipe.typ, ...(recipe.ingredienser || [])]
    .some(value => String(value).toLocaleLowerCase("sv").includes(normalized)));
}

export function mergeRecipeResults(retained, fresh) {
  return [...retained, ...fresh].filter((recipe, index, all) => all.findIndex(item => item.id === recipe.id) === index);
}

// En promise som aldrig settlar frigörs aldrig. Varje tangenttryck skapade en
// ny, och clearTimeout tog bort det enda som NÅGONSIN hade kunnat anropa dess
// resolve eller reject: sökningen som aldrig blev av. Kvar låg promisen med
// hela sin closure - söksträngen, signalen, anroparens .then-kedja - för
// resten av besöket. Fyra fält i appen använder den här (recept,
// liveprodukter, skafferiet, postnummer), så en stunds skrivande lämnade
// hundratals.
//
// Nu settlar den föregående INNAN den ersätts, med ett AbortError. Det är
// inget fel utan ett besked om att en nyare sökning hann före, och samtliga
// anropare skiljer redan på det (`if (error?.name === "AbortError") return;`)
// - precis som de gör för den avbrutna fetchen, som alltid har avslutats så.
const abortError = () => (typeof DOMException === "function"
  ? new DOMException("Sökningen avbröts - en nyare hann före", "AbortError")
  : Object.assign(new Error("Sökningen avbröts - en nyare hann före"), { name: "AbortError" }));

export function createDebouncedSearch(search, delay = 300) {
  let timer;
  let controller;
  // Den väntande sökningens reject, så länge den fortfarande bara väntar.
  let abandonPending = null;
  return query => new Promise((resolve, reject) => {
    clearTimeout(timer);
    controller?.abort();
    abandonPending?.();
    controller = new AbortController();
    abandonPending = () => { abandonPending = null; reject(abortError()); };
    timer = setTimeout(() => {
      // Härifrån är sökningen igång och settlar via search() - också när
      // nästa tangenttryck avbryter den, för då kastar fetch sitt eget
      // AbortError. Bara den VÄNTANDE behöver ges upp för hand.
      abandonPending = null;
      search(query, controller.signal).then(resolve, reject);
    }, delay);
  });
}
