export function filterRecipes(recipes, query) {
  const normalized = String(query || "").trim().toLocaleLowerCase("sv");
  if (!normalized) return recipes;
  return recipes.filter(recipe => [recipe.namn, recipe.typ, ...(recipe.ingredienser || [])]
    .some(value => String(value).toLocaleLowerCase("sv").includes(normalized)));
}

export function createDebouncedSearch(search, delay = 300) {
  let timer;
  let controller;
  return query => new Promise((resolve, reject) => {
    clearTimeout(timer);
    controller?.abort();
    controller = new AbortController();
    timer = setTimeout(() => search(query, controller.signal).then(resolve, reject), delay);
  });
}
