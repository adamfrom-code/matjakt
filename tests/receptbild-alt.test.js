// P09c: alt-texten i appen är bevisets (P09b), inte receptnamnets.
//
// Servern skickar imageAlt ur bildstatusens bevis ("<titel> (foto: <källa>)").
// fromApi() bär den som bildAlt, och receptbildMarkup() skriver den i alt -
// receptnamnet bara som reserv när ingen alt finns (äldre data).
import assert from "node:assert/strict";
import { test } from "node:test";

globalThis.document = { querySelector: () => null, baseURI: "http://localhost/app/" };

const { receptbildMarkup } = await import("../frontend/app/src/views/receptbild.js");

test("alt är bevisets när den finns, annars namnet", () => {
  const med = receptbildMarkup({ namn: "Biff med lök", bild: "assets/recipes/biff.jpg",
                                 bildAlt: "Beef medallion topped with fried onions (foto: Wikimedia Commons)" });
  assert.match(med, /alt="Beef medallion topped with fried onions \(foto: Wikimedia Commons\)"/);
  assert.doesNotMatch(med, /alt="Biff med lök"/);
  const utan = receptbildMarkup({ namn: "Biff med lök", bild: "assets/recipes/biff.jpg" });
  assert.match(utan, /alt="Biff med lök"/);
  // Escapas som allt annat i markupen.
  assert.match(receptbildMarkup({ namn: "x", bild: "assets/recipes/x.jpg", bildAlt: '"<b>' }), /alt="&quot;&lt;b&gt;"/);
});

test("fromApi bär serverns imageAlt som bildAlt", async () => {
  const bank = [{ id: "a", name: "A", image: "assets/recipes/a.jpg", imageAlt: "mixed salad (foto: Pexels)",
                  servings: 4, nutrition: { kcal: 1 }, ingredients: [], instructions: [], tags: [] }];
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ recipes: bank }) });
  try {
    const { loadRecipes } = await import("../frontend/app/src/data/recipes.js");
    const [r] = await loadRecipes();
    assert.equal(r.bildAlt, "mixed salad (foto: Pexels)");
    assert.match(receptbildMarkup(r), /alt="mixed salad \(foto: Pexels\)"/);
  } finally {
    globalThis.fetch = original;
  }
});
