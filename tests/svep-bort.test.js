// G5: svep vänster tar bort en vara ur inköpslistan.
//
// Gesten ersätter ett 30x30-kryss som satt i tumzonen, intill "Köpt". Den
// enda intressanta frågan om en sådan gest är när den INTE ska utlösa: en
// skrollning genom en lång lista får aldrig råka radera en vara.

import assert from "node:assert/strict";
import test from "node:test";
import { LUTNING, TRÖSKEL_PX, kopplaSvepBort, ärBorttagssvep }
  from "../frontend/app/src/utils/swipe-remove.js";

test("ett långt svep åt vänster är ett borttag", () => {
  assert.equal(ärBorttagssvep(-120, 4), true);
  assert.equal(ärBorttagssvep(-TRÖSKEL_PX - 1, 0), true);
});

test("en skrollning är inte ett borttag, hur lång den än är", () => {
  assert.equal(ärBorttagssvep(-120, 300), false, "en lodrät rörelse räknades som svep");
  assert.equal(ärBorttagssvep(-100, 100), false, "en diagonal rörelse räknades som svep");
  // Precis på gränsen: lika mycket vågrätt som lutningen kräver räcker inte.
  assert.equal(ärBorttagssvep(-100, 100 / LUTNING), false);
});

test("kort, eller åt höger, är inte ett borttag", () => {
  assert.equal(ärBorttagssvep(-TRÖSKEL_PX + 1, 0), false, "ett kort svep räckte");
  assert.equal(ärBorttagssvep(120, 0), false, "ett svep åt höger tog bort en vara");
  assert.equal(ärBorttagssvep(0, 0), false, "ett rent tryck tog bort en vara");
});

/** Minsta möjliga stubbar: modulen rör bara addEventListener, style och closest. */
function rigga({ rad = { style: {} } } = {}) {
  const lyssnare = {};
  const behållare = {
    addEventListener: (typ, fn) => { lyssnare[typ] = fn; },
    removeEventListener: (typ) => { delete lyssnare[typ]; },
  };
  const borttagna = [];
  const koppla = kopplaSvepBort(behållare, { väljRad: () => rad, taBort: (r) => borttagna.push(r) });
  const peka = (typ, x, y, extra = {}) =>
    lyssnare[typ]?.({ pointerType: "touch", clientX: x, clientY: y, target: {}, ...extra });
  return { peka, borttagna, rad, koppla, lyssnare };
}

test("svepet tar bort raden och låter den följa fingret på vägen", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 260, 202);
  assert.equal(rad.style.transform, "translateX(-40px)", "raden följde inte fingret");
  peka("pointermove", 180, 204);
  peka("pointerup", 180, 204);
  assert.equal(borttagna.length, 1);
  assert.equal(rad.style.transform, "", "raden lämnades förskjuten efter svepet");
});

test("en skrollning släpper raden direkt och tar inte bort något", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 292, 260);        // mest lodrätt: det här är en skrollning
  assert.equal(rad.style.transform, "", "raden flyttade sig under en skrollning");
  peka("pointermove", 150, 400);        // även om fingret sedan råkar dra åt vänster
  peka("pointerup", 150, 400);
  assert.deepEqual(borttagna, [], "en skrollning tog bort en vara");
});

test("mus sveper inte - där finns krysset kvar", () => {
  const { peka, borttagna } = rigga();
  peka("pointerdown", 300, 200, { pointerType: "mouse" });
  peka("pointerup", 100, 200, { pointerType: "mouse" });
  assert.deepEqual(borttagna, []);
});

test("ett avbrutet svep lämnar ingenting efter sig", () => {
  const { peka, borttagna, rad } = rigga();
  peka("pointerdown", 300, 200);
  peka("pointermove", 200, 202);
  peka("pointercancel", 200, 202);
  assert.equal(rad.style.transform, "");
  peka("pointerup", 120, 202);
  assert.deepEqual(borttagna, [], "ett avbrutet svep tog ändå bort varan");
});

test("utan en rad att svepa händer ingenting", () => {
  const lyssnare = {};
  const behållare = { addEventListener: (t, f) => { lyssnare[t] = f; }, removeEventListener() {} };
  const borttagna = [];
  kopplaSvepBort(behållare, { väljRad: () => null, taBort: (r) => borttagna.push(r) });
  lyssnare.pointerdown({ pointerType: "touch", clientX: 300, clientY: 200, target: {} });
  lyssnare.pointerup({ pointerType: "touch", clientX: 100, clientY: 200, target: {} });
  assert.deepEqual(borttagna, []);
});

test("saknas behållaren kraschar inte appen", () => {
  assert.doesNotThrow(() => kopplaSvepBort(null, { väljRad: () => null, taBort: () => {} })());
  assert.doesNotThrow(() => kopplaSvepBort({ addEventListener() {} })());
});
