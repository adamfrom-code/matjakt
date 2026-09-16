// P04b: ett recept-id som blivit alias betyder fortfarande samma rätt.
//
// Tio rätter låg i banken under två id var (docs/RECEPTIDENTITET.md). Det
// recept som blev kvar bär de gamla id:na som `aliases` - i /api/recipes-
// listan och i reservbanken, som är samma projektion. Men favoriter, veckan,
// historiken och betygen skrevs med de gamla id:na, och servern tolkar varken
// kontoblobben (`users.synced_state`) eller hushållsdokumenten: de är text
// för den. Så det finns bara ett ställe att peka om dem på - här, där appen
// läser dem. En gång per laddad bank, en gång per hämtad blob.
//
// Idempotent och försiktigt: bara id som är alias i den bank som råkar vara
// laddad rörs. Ett okänt id lämnas som det är - det kan vara ett recept
// banken inte laddat än, och att gissa vore värre än att vänta.

/** Map gammalt id -> kanoniskt, ur recepten som bär `aliases`. */
export function aliasMap(recipes) {
  const map = new Map();
  for (const recipe of recipes || []) {
    for (const alias of recipe?.aliases || []) {
      if (alias && alias !== recipe.id) map.set(alias, recipe.id);
    }
  }
  return map;
}

export function canonicalRecipeId(id, map) {
  return map?.get(id) ?? id;
}

/** Receptet för ett id - eller för ett av dess alias. null när det saknas. */
export function findRecipe(recipes, id) {
  return recipes.find(recipe => recipe?.id === id)
    ?? recipes.find(recipe => Array.isArray(recipe?.aliases) && recipe.aliases.includes(id))
    ?? null;
}

function mapIds(ids, map, changed) {
  return ids.map(id => {
    const next = map.get(id);
    if (next === undefined) return id;
    changed.value = true;
    return next;
  });
}

/**
 * Pekar om varje recept-id i tillståndet enligt `map`. Muterar `state` och
 * returnerar om något ändrades.
 *
 *  - favoriter, valda: mängder - ett alias och dess kanoniska blir EN post
 *  - weekPlan, weekHistory[].plan: dagordningen bevaras; stod aliaset och
 *    det kanoniska på två dagar blir det samma rätt två dagar - veckan
 *    hittas inte på, nästa "Skapa ny vecka" rättar det
 *  - apiRecipes: posternas id byts; blir två poster samma id behålls den som
 *    redan var kanonisk
 *  - betyg: högsta betyget vinner när två nycklar möts
 *  - feedback: det kanoniska id:ts omdöme vinner när båda finns
 */
export function migrateRecipeIds(state, map) {
  if (!state || !map?.size) return false;
  const changed = { value: false };

  for (const key of ["favoriter", "valda"]) {
    if (state[key] instanceof Set) {
      const next = new Set(mapIds([...state[key]], map, changed));
      if (changed.value) state[key] = next;
    }
  }
  if (Array.isArray(state.weekPlan)) state.weekPlan = mapIds(state.weekPlan, map, changed);
  if (Array.isArray(state.weekHistory)) {
    state.weekHistory = state.weekHistory.map(entry => (Array.isArray(entry?.plan)
      ? { ...entry, plan: mapIds(entry.plan, map, changed) }
      : entry));
  }
  if (Array.isArray(state.apiRecipes)) {
    const seen = new Set();
    const kept = [];
    for (const recipe of state.apiRecipes) {
      const next = map.get(recipe?.id);
      const record = next === undefined ? recipe : { ...recipe, id: next };
      if (next !== undefined) changed.value = true;
      if (seen.has(record?.id)) {
        // Två poster för samma rätt: den som var kanonisk från början står
        // först i `kept` bara om den låg först - så byt om aliasposten kom
        // först men den kanoniska finns.
        const index = kept.findIndex(item => item?.id === record.id);
        if (next === undefined && index >= 0) kept[index] = record;
        continue;
      }
      seen.add(record?.id);
      kept.push(record);
    }
    state.apiRecipes = kept;
  }
  if (state.betyg && typeof state.betyg === "object") {
    for (const [id, value] of Object.entries(state.betyg)) {
      const next = map.get(id);
      if (next === undefined) continue;
      state.betyg[next] = Math.max(Number(state.betyg[next]) || 0, Number(value) || 0);
      delete state.betyg[id];
      changed.value = true;
    }
  }
  if (state.feedback && typeof state.feedback === "object") {
    for (const [id, value] of Object.entries(state.feedback)) {
      const next = map.get(id);
      if (next === undefined) continue;
      if (!state.feedback[next]) state.feedback[next] = value;
      delete state.feedback[id];
      changed.value = true;
    }
  }
  return changed.value;
}
