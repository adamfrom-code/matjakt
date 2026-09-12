// CACHE-STÄMPELN. Den hör ihop med ?v= på app.js/styles.css i index.html:
// queryn spräcker webbläsarens HTTP-cache, och cachenamnet får service workern
// att släppa sin gamla kopia i activate(). Missas något av dem kör en
// återvändande användare den förra releasen under samma URL - exakt det som
// hände efter receptbanks- och veckotypsarbetet: sidan var uppdaterad,
// telefonerna visade de gamla tre veckotyperna.
//
// DET STÅR INGET TAL HÄR, OCH DET SKA INTE GÖRA DET (L9). Platshållaren nedan
// byts ut av byggsteget mot eran plus en digest över varje fil under app/ i
// bygget - `matjakt-shell-v120-a1b2c3d4e5`. Två skäl, båda mätta:
//
//   - Ett handskrivet tal kunde SJUNKA. `app.js?v=` gick 102 -> 25 (964d45e),
//     upp till 103 (7aeb57c) och ner till 26 igen (3a36dd2) när de tre
//     räknarna slogs ihop, så allt under 104 är cache-nycklar som redan
//     serverats en gång med annat innehåll. Felet den här filen finns för att
//     undvika hade alltså redan hänt två gånger i main. En digest kan inte
//     sjunka och kan inte råka bli densamma som förra releasens.
//   - Raden var den enda åtta parallella grenar konfliktade på. G5 låg DIRTY
//     med grön CI i fyra timmar, D11 baserades om fyra gånger och gick från
//     v56 till v107 - och båda konflikterna var enbart versionsraderna.
//
// Utvecklingsservern serverar den här filen som den står, och platshållaren är
// ett fullt dugligt cachenamn lokalt - den behöver inget tal. Det som deployas
// är alltid stämplat: bygget vägrar skriva ut en kopia där platshållaren står
// kvar, och grinden räknar om digesten ur bygget och jämför. Se
// scripts/frontend_version.mjs och backend/scripts/check_frontend_version.py.
const CACHE_NAME = "matjakt-shell-v__MATJAKT_VERSION__";

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
