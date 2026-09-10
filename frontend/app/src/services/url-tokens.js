// Engångstoken ur adressfältet: plockas UPP och BORT i samma andetag (B7).
//
// VARFÖR DEN HÄR FINNS. `?reset=<token>` ÄR kontot. Den som får tag i
// strängen sätter ett nytt lösenord och äger inloggningen - i en timme,
// vilket är hur länge servern låter token gälla. Ändå blev den kvar i
// adressfältet ända tills användaren hunnit fylla i och skicka in det nya
// lösenordet: URL:en rensades först EFTER lyckad inlämning. Fram till dess
// stod hela token i adressfältet, i webbläsarhistoriken och i
// sessionsåterställningen ("återställ flikar" tar med query-strängen).
//
// Och den läses av mer än användaren. CSP:n släpper in plausible.io och
// cloud.umami.is i både script-src och connect-src, och båda skickar sidans
// FULLA URL som sidvisning. Metataggen matjakt-traffic är tom idag, så
// läckan är latent - men den dagen någon slår på besöksstatistiken går
// varje återställningslänk till tredje part utan att någon rör en rad kod.
// Samma sak gäller `?verify=`: svagare, men det är också ett engångstoken
// som inte har i en delbar URL att göra.
//
// DÄRFÖR: läs och rensa först av allt vid inläsning, före all annan
// startkod, och lämna kvar det som inte är en hemlighet. `recept`, `invite`
// och `billing` behövs längre fram i starten och bär ingenting känsligt -
// att svepa hela query-strängen skulle ta dem med sig.

export const SENSITIVE_URL_PARAMS = ["reset", "verify"];

/**
 * Plockar ut engångstoken ur adressraden och skriver om URL:en utan dem.
 * Returnerar `{ reset, verify }` med de värden som fanns.
 *
 * `win` finns för testbarhetens skull - i appen är det window.
 */
export function takeUrlTokens(win = globalThis) {
  const taken = {};
  let url;
  try {
    url = new URL(win.location.href);
  } catch {
    return taken;                       // ingen adress att rensa (t.ex. i en worker)
  }
  let found = false;
  for (const name of SENSITIVE_URL_PARAMS) {
    const value = url.searchParams.get(name);
    if (value === null) continue;       // "" är en tom parameter och ska också bort
    if (value) taken[name] = value;
    url.searchParams.delete(name);
    found = true;
  }
  // replaceState, inte pushState: token får inte gå att bläddra tillbaka
  // till. Sökvägen och fragmentet behålls oförändrade.
  if (found) {
    try {
      win.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch {
      /* en webbläsare som vägrar skriva om historiken ska inte stoppa starten */
    }
  }
  return taken;
}
