// Besöksstatistik utan kakor. Laddar Plausible eller Umami - bara om sidan
// säger vilken, via <meta name="matjakt-traffic">:
//
//   plausible:matjakt.store          (domänen som är registrerad hos Plausible)
//   umami:xxxxxxxx-xxxx-...          (Umami Clouds website-id)
//
// Tomt värde = ingenting laddas. Aldrig på localhost, så utvecklingen inte
// räknas som besökare. Båda tjänsterna är kakfria och kräver ingen
// samtyckesbanner; de får en sidvisning med URL, hänvisande sida och grov
// geografi, aldrig konto eller e-post. Värdarna måste också finnas i
// CSP:n (script-src + connect-src) - se app/index.html och api_server.py.
(function () {
  try {
    var meta = document.querySelector('meta[name="matjakt-traffic"]');
    var value = (meta && meta.content || "").trim();
    var host = location.hostname;
    if (!value || host === "localhost" || host === "127.0.0.1") return;
    var colon = value.indexOf(":");
    var provider = value.slice(0, colon), id = value.slice(colon + 1).trim();
    if (!provider || !id) return;
    var script = document.createElement("script");
    script.defer = true;
    if (provider === "plausible") {
      script.src = "https://plausible.io/js/script.js";
      script.setAttribute("data-domain", id);
    } else if (provider === "umami") {
      script.src = "https://cloud.umami.is/script.js";
      script.setAttribute("data-website-id", id);
    } else {
      return;
    }
    document.head.appendChild(script);
  } catch (e) { /* statistik får aldrig störa sidan */ }
})();
