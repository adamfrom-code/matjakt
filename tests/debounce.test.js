// E9 (a): budgetfältet ska räkna om när skrivandet tagit slut, inte per
// tecken. Timern skickas in här, så testet inte behöver vänta på riktig tid.
import test from "node:test";
import assert from "node:assert/strict";
import { debounce } from "../frontend/app/src/services/debounce.js";

// En klocka som bara rör sig när testet säger till.
function fakeClock() {
  let nextId = 1;
  const timers = new Map();
  return {
    setTimer: (fn, wait) => { const id = nextId++; timers.set(id, { fn, wait }); return id; },
    clearTimer: id => timers.delete(id),
    tick: () => { const due = [...timers.values()]; timers.clear(); due.forEach(timer => timer.fn()); },
    pending: () => timers.size,
  };
}

test("E9: åtta tecken ger en omräkning, inte åtta", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce(value => körda.push(value), 250, clock);
  for (const value of ["8", "80", "800", "8000", "800", "80", "8", "85"]) räknaOm(value);
  assert.deepEqual(körda, [], "inget ska hända medan användaren fortfarande skriver");
  clock.tick();
  assert.deepEqual(körda, ["85"], "det sista värdet är det som gäller");
});

test("E9: varje tecken avbryter den föregående timern", () => {
  const clock = fakeClock();
  const räknaOm = debounce(() => {}, 250, clock);
  räknaOm("1"); räknaOm("12"); räknaOm("123");
  assert.equal(clock.pending(), 1, "en väntande timer, inte tre staplade");
});

test("E9: flush låter det sista värdet gälla omedelbart", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce(value => körda.push(value), 250, clock);
  räknaOm("900");
  räknaOm.flush();
  assert.deepEqual(körda, ["900"], "värdet får inte försvinna med timern när fältet lämnas");
  assert.equal(clock.pending(), 0);
  clock.tick();
  assert.deepEqual(körda, ["900"], "och det ska inte köras en gång till efteråt");
});

test("E9: flush med ett eget värde vinner över det som väntade", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce(value => körda.push(value), 250, clock);
  räknaOm("90");
  räknaOm.flush("900");
  assert.deepEqual(körda, ["900"]);
});

test("E9: flush utan något att göra gör ingenting", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce(value => körda.push(value), 250, clock);
  räknaOm.flush();
  räknaOm.flush();
  assert.deepEqual(körda, []);
});

test("E9: efter en körning börjar nästa skrivning om från noll", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce(value => körda.push(value), 250, clock);
  räknaOm("800"); clock.tick();
  räknaOm("900"); clock.tick();
  assert.deepEqual(körda, ["800", "900"]);
});

test("E9: alla argument följer med", () => {
  const clock = fakeClock();
  const körda = [];
  const räknaOm = debounce((...args) => körda.push(args), 250, clock);
  räknaOm("a", "b", "c");
  clock.tick();
  assert.deepEqual(körda, [["a", "b", "c"]]);
});
