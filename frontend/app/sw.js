// Bumped together with the ?v= query on app.js/styles.css in index.html.
// All three have to move: the query busts the browser's HTTP cache, and the
// cache name makes the service worker drop its old copy in activate(). Miss
// any of them and a returning user keeps running the previous release under
// the same URL - which is exactly what happened after the recipe-bank and
// week-type work shipped: the site was updated, phones still showed the old
// three week types.
const CACHE_NAME = "matjakt-shell-v12";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
  );
  self.clients.claim();
});

// Network-first for everything except /api/* - API calls must always hit the
// server live (prices, auth, recipes). Static assets are cached as a fallback
// so the app shell still opens when offline.
//
// Cache-reglerna inför release:
// - Bara SAMMA ORIGIN caches. Cross-origin (Pexels-bilder, fonter) blir
//   opaka svar som inte kan felkontrolleras och räknas med kvotpadding -
//   webbläsarens egen HTTP-cache sköter dem bättre.
// - Bara response.ok caches. En cachad 404/500 skulle annars bli appens
//   offline-"fallback" för alltid.
// - Navigationer och /app/src/-modulerna hämtas med cache: "no-cache" så
//   varje sidöppning revaliderar mot servern (ETag/304 är billigt). Utan
//   detta kunde GitHub Pages 10-minuters HTTP-cache blanda ny app.js med
//   gamla moduler - "sidan är deployad men telefonen kör gammal kod".
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;

  const revalidate = event.request.mode === "navigate" || url.pathname.includes("/src/");
  const request = revalidate ? new Request(event.request, { cache: "no-cache" }) : event.request;

  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok && url.origin === self.location.origin) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
