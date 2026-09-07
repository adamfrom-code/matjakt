import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  RECIPE_FALLBACK_ART, RECIPE_FALLBACK_KINDS, RECIPE_FALLBACK_LABEL, kindFor,
} from "../frontend/app/src/services/recipe-fallback.js";

test("varje sort har både ikon och etikett", () => {
  for (const kind of RECIPE_FALLBACK_KINDS) {
    assert.ok(RECIPE_FALLBACK_ART[kind], `ikon saknas för ${kind}`);
    assert.ok(RECIPE_FALLBACK_LABEL[kind], `etikett saknas för ${kind}`);
  }
});

test("receptkällans egna taggar och typ går före namnet", () => {
  assert.equal(kindFor({ namn: "Något okänt", tags: ["fisk"] }), "fisk");
  assert.equal(kindFor({ namn: "Något okänt", typ: "Kyckling" }), "kyckling");
  // Namnet säger biff, men källan har taggat den som fisk - källan vinner.
  assert.equal(kindFor({ namn: "Biff", tags: ["fisk"] }), "fisk");
});

test("soppa går före vego - en vegetarisk soppa är fortfarande en soppa", () => {
  assert.equal(kindFor({ namn: "Gul ärtsoppa på grönsaksbuljong", tags: ["vegetariskt"] }), "soppa");
  assert.equal(kindFor({ namn: "Minestrone med vita bönor", tags: ["vegetariskt"] }), "soppa");
});

test("kött går före vego i namnsökningen", () => {
  // "bönor" finns i vego-mönstret; utan ordningen blev den här vegetarisk.
  assert.equal(kindFor({ namn: "Bruna bönor med stekt fläsk" }), "kott");
});

test("okänd rätt får den neutrala karotten i stället för en gissning", () => {
  assert.equal(kindFor({ namn: "Kroppkakor med smör och lingon" }), "standard");
  assert.equal(kindFor({ namn: "" }), "standard");
  assert.equal(kindFor({}), "standard");
  assert.equal(kindFor(null), "standard");
});

test("varje bildlös rätt i receptbanken får en giltig sort", () => {
  const utanBild = [];
  for (const fil of fs.readdirSync("backend/recipe_sources").filter(f => f.endsWith(".json"))) {
    const data = JSON.parse(fs.readFileSync(`backend/recipe_sources/${fil}`, "utf8"));
    for (const recept of Array.isArray(data) ? data : data.recipes || []) {
      if (!recept.image) utanBild.push(recept);
    }
  }
  // Om receptbanken en dag har foton överallt är testet meningslöst, inte grönt.
  assert.ok(utanBild.length > 0, "inga bildlösa recept - testet mäter ingenting");
  for (const recept of utanBild) {
    const kind = kindFor({ namn: recept.name, tags: recept.tags || [], typ: (recept.categories || []).join(" ") });
    assert.ok(RECIPE_FALLBACK_KINDS.includes(kind), `${recept.name} gav okänd sort ${kind}`);
  }
});
