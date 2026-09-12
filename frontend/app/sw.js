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

// ---------------------------------------------------------------------------
// H1: SÖNDAGSNOTISEN
//
// Appen hade ingen `push`-lyssnare alls. Notisinställningarna under Konto →
// Hushåll styrde en in-app-toast som bara syns om appen råkar vara öppen -
// alltså exakt när ingen behöver påminnas. Det här är den andra halvan:
// servern skickar söndag 17:00 (backend/services/push/schedule.py) och det
// här tar emot.
//
// TVÅ REGLER.
//
// 1. EN PUSH FÅR ALDRIG KASTA. Gör den det visar webbläsaren sin egen
//    "den här sajten uppdaterades i bakgrunden"-notis i stället - en notis
//    användaren varken bad om eller kan tolka. Därför läses nyttolasten
//    genom en try/catch med en färdig reservtext, och showNotification är
//    det enda som kan misslyckas efter den punkten.
// 2. ETT TRYCK SKA GE EN FÄRDIG VECKA. `notificationclick` landar inte på
//    startsidan. Den öppnar (eller lyfter fram) appen med ?notis=vecka, och
//    app.js bygger veckan på den signalen. En notis som leder till en tom
//    startsida är en notis som lär folk att inte trycka.
const NOTIFICATION_FALLBACK = {
  title: "Dags att planera veckan",
  body: "Förslaget till veckan är redan klart.",
};
// Samma tag varje söndag: en oläst notis ERSÄTTS i stället för att en till
// läggs på hög. Databasens push_log är första försvaret mot dubbletter, det
// här är andra - och det enda som också gäller mellan två servrar.
const WEEK_NOTIFICATION_TAG = "matjakt-vecka";
const WEEK_NOTIFICATION_URL = "./?notis=vecka";

function notificationPayload(data) {
  try {
    const parsed = data && data.json();
    if (parsed && typeof parsed === "object") return parsed;
  } catch { /* inte JSON - texten nedan duger */ }
  try {
    const text = data && data.text();
    if (text) return { ...NOTIFICATION_FALLBACK, body: text };
  } catch { /* ingen nyttolast alls */ }
  return NOTIFICATION_FALLBACK;
}

self.addEventListener("push", event => {
  const payload = notificationPayload(event.data);
  event.waitUntil(self.registration.showNotification(payload.title || NOTIFICATION_FALLBACK.title, {
    body: payload.body || NOTIFICATION_FALLBACK.body,
    tag: payload.tag || WEEK_NOTIFICATION_TAG,
    icon: "assets/icons/icon-192.png",
    badge: "assets/icons/icon-192.png",
    lang: "sv-SE",
    // Notisen bär inget känsligt (antal middagar och personer), men den
    // ligger på en låst skärm och ska kunna läsas där - inget mer.
    data: { url: payload.url || WEEK_NOTIFICATION_URL, kind: payload.kind || "sondagsnotis" },
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(openFromNotification(event.notification.data));
});

function openFromNotification(data) {
  const target = new URL((data && data.url) || WEEK_NOTIFICATION_URL, self.location.href);
  // Djuplänken är en UPPMANING, inte en adress: app.js läser ?notis= och
  // bygger veckan. Den sätts även på en redan öppen flik, som annars hade
  // lyfts fram på vilken vy den nu stod.
  return self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(windows => {
    const open = windows.find(client => {
      try { return new URL(client.url).origin === self.location.origin; } catch { return false; }
    });
    if (!open) return self.clients.openWindow(target.href);
    // postMessage först, focus sen: en flik som inte går att lyfta fram
    // (vissa webbläsare vägrar) har då ändå fått veta vad som ska hända.
    if (open.postMessage) open.postMessage({ type: "matjakt-notis", url: target.href });
    return open.focus ? open.focus() : undefined;
  });
}
