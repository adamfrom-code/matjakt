// ---------------------------------------------------------------------------
// VÄNTA TILLS ANVÄNDAREN SLUTAT SKRIVA
//
// `createDebouncedSearch` i recipe-search.js gör det här för NÄTANROP och
// bär hela sin promise-kedja. Ett fält som bara räknar om något lokalt
// behöver ingen promise - det behöver bara sluta räkna om per tangenttryck.
//
// Timern går att skicka in, så en debounce går att prova i Node utan att
// vänta på riktig tid.
// ---------------------------------------------------------------------------

export function debounce(fn, waitMs, { setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let timer = null;
  let pending = null;

  function fire() {
    timer = null;
    if (!pending) return;
    const args = pending;
    pending = null;
    fn(...args);
  }

  function debounced(...args) {
    pending = args;
    if (timer !== null) clearTimer(timer);
    timer = setTimer(fire, waitMs);
  }

  // Vissa ögonblick tål ingen väntan: fältet lämnas, knappen bredvid trycks,
  // sidan stängs. Då ska det sista värdet gälla NU - annars kan en budget
  // användaren precis skrivit in försvinna med den väntande timern.
  debounced.flush = (...args) => {
    if (args.length) pending = args;
    if (timer !== null) clearTimer(timer);
    fire();
  };

  return debounced;
}
