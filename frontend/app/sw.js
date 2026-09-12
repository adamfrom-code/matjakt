// CACHE-STÄMPELN. Talet här hör ihop med ?v= på app.js/styles.css i
// index.html: queryn spräcker webbläsarens HTTP-cache, och cachenamnet får
// service workern att släppa sin gamla kopia i activate(). Missas något av
// dem kör en återvändande användare den förra releasen under samma URL -
// exakt det som hände efter receptbanks- och veckotypsarbetet: sidan var
// uppdaterad, telefonerna visade de gamla tre veckotyperna.
//
// Talet står kvar i källan, men det redigeras inte längre för hand och det är
// inte det som deployas. `node scripts/frontend_version.mjs --bump` räknar upp
// alla tre ställena från det HÖGSTA tal som någonsin stått i main, och
// byggsteget (scripts/build_frontend.mjs) stämplar bygget med talet plus en
// hash av det som faktiskt byggdes. Två grenar som båda höjde 51 till 52 blir
// EN höjning vid ombasering, utan ett ord - hashen är det som gör att den
// tystnaden ändå inte kan gömma ny kod bakom en adress webbläsaren redan sett.
//
// Att talet hoppade förbi ett femtiotal steg till 104 är generatorns första
// körning, och den
// säger något obehagligt om historiken: `app.js?v=` gick 102 -> 25 (964d45e),
// upp till 103 (7aeb57c) och ner till 26 igen (3a36dd2) när de tre räknarna
// slogs ihop. Allt under 104 är alltså cache-nycklar som redan serverats en
// gång, med annat innehåll - felet det här paketet handlar om har redan hänt
// två gånger i main. Ett tal som kan gå ner är värre än tre tal som kan gå
// isär, så det räknas numera från det högsta som någonsin setts och aldrig
// från det som råkar ligga i den egna grenen.
// Se scripts/frontend_version.mjs.
const CACHE_NAME = "matjakt-shell-v113";

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
      // OFFLINE MED QUERY I ADRESSEN.
      //
      // caches.match(request) matchar på EXAKT URL, query och allt. Varje
      // djuplänk appen själv delar ut bär en - ?recept=, ?invite=, ?verify=,
      // ?reset=, ?billing=success - och ingen av dem finns i cachen, för de
      // har aldrig hämtats förut. Offline gav därför webbläsarens felsida på
      // precis de adresser som skickas i mejl och delas vidare.
      //
      // En NAVIGERING vill åt appskalet. Det är samma dokument oavsett query,
      // och appen läser sin egen adress när den startat (takeUrlTokens m.fl.).
      // Så: exakt träff först, sedan samma adress utan query, sist skalet på
      // scopets rot. Allt som inte är en navigering beter sig som förut - att
      // svara med HTML-skalet på en produktbild vore värre än inget svar.
      .catch(() => caches.match(event.request).then(hit => hit
        || (event.request.mode === "navigate"
          ? caches.match(event.request, { ignoreSearch: true }).then(shell => shell || caches.match("./"))
          : undefined)))
  );
});
