# Uppdrag: Matjakt till lanseringsskick

**Till:** Claude Code
**Från:** Adam
**Datum:** 2026-09-10
**Repo:** https://github.com/adamfrom-code/matjakt

---

## 0. Så här vill jag att du arbetar

Läs det här stycket först. Det ersätter alla tidigare arbetsinstruktioner.

1. **Fråga inte.** Varje beslut i det här dokumentet är fattat. Där något är öppet står det uttryckligen "ADAMS BESLUT" — hoppa över det paketet och gå vidare. Allt annat bygger du.
2. **En agent = ett paket = en gren = en PR.** Grennamn `paket/<ID>-<kort-slug>`, commit-prefix `<ID>:`. Aldrig två paket i samma PR.
3. **Kör så många agenter du behöver.** Paketen är märkta med zon; paket i olika zoner kan köras samtidigt. Behöver du fyrtio agenter, kör fyrtio.
4. **Grön CI, sen merge, sen live.** Ingen merge på röd CI. Ingen forcerad merge. Vid konflikt: rapportera, forcera aldrig.
5. **Varje paket har ett acceptanskriterium.** Det är ett test, inte en åsikt. Skriv testet först om det inte finns.
6. **Rör inte de stora filerna i onödan.** `frontend/app/app.js` (5 297 rader) och `backend/api_server.py` (3 551 rader) är konfliktzoner. Ny logik i nya moduler; i den stora filen ändrar du bara inkopplingsraden.
7. **Rapportera kort.** En rad per paket när det är klart: ID, vad som ändrades, testet som bevisar det. Inte processberättelser.

Alla fynd nedan är verifierade mot koden. Radnummer avser commit `cb27b07`.

---

## 1. Läget i ett stycke

Matjakt är bättre byggt än det ser ut och sämre sålt än det förtjänar. Prismotorn är genuint disciplinerad — fail-closed, tvånivåprissättning, en jämförelse som vägrar kröna en billigaste butik utan täckning. Auth, hushållssynk och Stripe-webhooken är gjorda rätt på de ställen där de flesta gör fel. 1 243 backend-tester är gröna på 129 sekunder.

Tre saker står ändå mellan appen och en lansering:

- **Priserna är systematiskt för låga.** Inte slumpmässigt fel — alltid åt samma håll, och åt exakt det håll appen lovar att den aldrig felar åt. En 4-pack krossade tomater prissätts som en burk. Tre vitlöksklyftor prissätts som 210 gram vitlök. Ett recept med en osäker rad visar ett portionspris där den radens kostnad helt saknas.
- **Betalväggen är kosmetisk och betalningen kan tappas.** Tretton av sjutton premiumfunktioner är låsta med CSS. En Stripe-betalning där kundraden inte hittas markeras som konsumerad och återlevereras aldrig.
- **Produkten säljs inte alls.** matjakt.store är 52 rader: en rubrik, en mening och en knapp. Den färdiga landningssidan, filmen på 3,5 MB och Instagram-reelen ligger obrukade i repot. Sitemapen är tom. Utskicken är avstängda.

Och under allt: det finns ingen anledning att öppna appen på tisdag. Ingen notis, ingen veckorytm, ingen synlig sparsumma.

---

## 2. Arbetsordning

| Våg | Innehåll | Paket | Parallellt? |
|---|---|---|---|
| **A** | Infrastruktur för parallellt arbete | 4 | Nej — en agent, först |
| **B** | Pengar och säkerhet | 10 | Ja, inom vågen |
| **C** | Priser | 10 | Ja |
| **D** | Drift och datainhämtning | 10 | Ja |
| **E** | Frontend-buggar | 15 | Delvis — se E0 |
| **F** | Refaktorering av app.js | 6 | E0+E1 först, sen parallellt |
| **G** | Utseende och UX | 13 | Ja, efter F |
| **H** | Retention | 5 | Ja |
| **I** | Marknadsföring | 7 | Ja |
| **J** | Paketering och pris | 5 | Ja |
| **K** | CI och leverans | 6 | Ja |

**Zoner** (två paket i samma zon körs aldrig samtidigt):
`Z-INFRA` · `Z-AUTH` · `Z-BILLING` · `Z-PRICING` · `Z-GROCERY` · `Z-FRONT-CORE` · `Z-FRONT-VIEW` · `Z-STYLE` · `Z-MAIL` · `Z-SITE` · `Z-CI`

---

# VÅG A — Infrastruktur för parallellt arbete

*En agent. Måste vara klar innan någon annan startar.*

### A1 · `CLAUDE.md` i roten `Z-INFRA`
Repot saknar arbetsinstruktion för agenter. `.claude/launch.json` är allt som finns — och den filen läckte `MATJAKT_ADMIN_TOKEN` i klartext till ett publikt repo.

Skriv `CLAUDE.md` med: kommandon (`npm test`, `python backend/tests/run.py`, `npm run build`), zonkartan ovan, regeln en agent = en gren = en PR, och absoluta förbud — committa aldrig `*.db`, `.env*` eller hemligheter, skriv aldrig nyckelvärden i `.claude/`, redigera aldrig `CHECKPOINT.md` direkt.

**Acceptans:** filen finns; `secret_scan.py` körs i CI mot den.

### A2 · `CODEOWNERS` som zonkarta `Z-INFRA`
`.github/CODEOWNERS` med en rad per zon. `.github/**`, `render.yaml` och `backend/Dockerfile` får en enda ägare och rörs aldrig av ett arbetspaket.

**Acceptans:** filen finns och matchar zonlistan.

### A3 · Genererade filer ut ur git `Z-INFRA`
`audit_flags.tsv` och `audit_result.json` ligger i repo-roten och skrivs av `backend/scripts/audit_pricing.py:58`. Varje agent som kör prisauditen får en diff i roten — den perfekta konfliktgeneratorn. Dessutom är ~78 MB video under `marketing/build/` spårad trots att `.gitignore:29` säger `marketing/` (gitignore avspårar inget som redan är spårat). `.git` är 191 MB.

Skriv auditen till `backend/data/audit/` (gitignorerad), `git rm --cached` alla tre, låt CI publicera auditresultatet som artifact.

**Acceptans:** CI failar om en `*.tsv`/`*.json`-artefakt eller `marketing/build/**` är spårad.

### A4 · Append-only changelog `Z-INFRA`
`CHECKPOINT.md` är 18 kB välskriven berättelse — utmärkt för en människa, en garanterad konflikt när tjugo agenter redigerar den. Inför `docs/changelog.d/<paket-ID>.md`, en fil per agent, plus `scripts/weave_checkpoint.mjs` som väver ihop dem vid release.

**Acceptans:** två agenter kan skriva changelog samtidigt utan konflikt.

### ADAMS BESLUT (blockerar inget, men gör det snart)
- **Git-historiken.** `backend/data/backups/` med kontodatabasen (e-post, lösenordshashar, salt, reset-token-hashar, fritextfeedback) låg spårad i ett **publikt** repo 2026-08-31 → 2026-09-07. Borttagen ur HEAD i `1697d1f`, kvar i historiken: 33 nåbara objekt. `MATJAKT_ADMIN_TOKEN` i klartext i `27edd8a`. Rensning kräver `git filter-repo` + force-push som påverkar alla kloner. Bedöm också anmälningsplikten enligt GDPR art. 33 — 198 användarrader, varav 11 adresser inte ser ut som testkonton.
- **Branch protection + merge queue** på `main`. Med fyrtio agenter är "grön PR" inte samma sak som "grön main".

---

# VÅG B — Pengar och säkerhet

### B1 · Stripe kan tappa en betalning för alltid `Z-BILLING` · **KRITISK**
`backend/services/accounts/store.py:480-493`

Event-id:t skrivs in i `stripe_events` **före** kundraden slås upp. Hittas ingen användare med det `stripe_customer_id`:t commit:as ändå och 200 skickas — Stripe återlevererar aldrig, och nästa leverans svarar `duplicate`.

Scenariot är inte hypotetiskt: servern startar om (Render deployar) mellan `create_customer` och `set_stripe_customer_id` (`api_server.py:2773-2774`). Kunden har en Stripe-kund vi inte känner till. Hon slutför Checkout, debiteras 399 kr och blir kvar på Free. Permanent. Samma sak för varje prenumeration som skapas i Stripes dashboard.

**Gör:** registrera event-id:t efter lyckad applicering, eller svara 500 vid `unknown_customer` så Stripe retryar i tre dygn. Slå dessutom upp på `metadata[matjakt_user_id]` (sätts redan i `stripe_client.py:63-67`) och `client_reference_id` som fallback. Lägg till `GET /api/admin/stripe-reconcile` som listar aktiva Stripe-prenumerationer utan matchande konto.

**Acceptans:** test där webhooken kommer före `set_stripe_customer_id` och betalningen ändå landar på rätt konto vid andra leveransen.

### B2 · Ingen moms `Z-BILLING` · **KRITISK**
`backend/services/billing/stripe_client.py:70-80`

Checkout sätter varken `automatic_tax[enabled]`, `customer_update[address]` eller `tax_id_collection`. `verify_stripe_prices` (`api_server.py:155-166`) kontrollerar bara att beloppet är 5900/39900 SEK, inget om `tax_behavior`. Är 59 kr inkl. eller exkl. 25 % moms? Koden vet inte, Stripe vet inte, kvittot säger inget.

**Gör:** `tax_behavior: "inclusive"` på priserna i Stripe (rätt för svensk konsumentprissättning), aktivera Stripe Tax, skicka `automatic_tax[enabled]=true` + `customer_update[address]=auto`. Utöka `verify_stripe_prices` med `tax_behavior`-kontroll. Slå på kvitton i Stripe-dashboarden.

**Acceptans:** `verify_stripe_prices` failar om `tax_behavior` saknas.

### B3 · Ångerrätt saknas i köpflödet `Z-BILLING` · **HÖG**
Distansavtalslagen ger fjorton dagars ångerrätt. För en digital tjänst som levereras direkt måste kunden aktivt avstå den vid köp för att ni ska slippa återbetala. Det finns ingen sådan kryssruta någonstans.

**Gör:** kryssruta i köpflödet med texten *"Jag vill få tillgång till Premium direkt och godkänner att min ångerrätt upphör när tjänsten levererats."* Spara samtycket med tidsstämpel.

**Acceptans:** checkout går inte att starta utan sparat samtycke; testet bevisar det.

### B4 · `X-Forwarded-For` kan upphäva hela rate limitern `Z-AUTH` · **HÖG**
`backend/api_server.py:1746-1765`

Koden tar `forwarded.split(",")[0]` och kommentaren motiverar det med att resten läggs på av uppströms hopp. Det är baklänges för en proxy som *lägger till* (nginx `proxy_add_x_forwarded_for` och de flesta edge-proxies): listan blir `<klientens påhitt>, <verklig IP>`, och `[0]` är exakt det angriparen skrev. `MATJAKT_TRUST_PROXY=1` står i `render.yaml:24-28`.

För `/api/admin/*`, `register`, `feedback`, `partner_feed`, `scrape` och `unsubscribe` finns ingen andra hink — admin-tokengissningen på 10/h blir obegränsad, och skrapvägen (Chromium på en 512 MB-instans) blir en gratis OOM-knapp.

**Gör:** räkna hopp bakifrån.
```python
TRUSTED_PROXY_HOPS = int(os.environ.get("MATJAKT_TRUSTED_HOPS", "1"))
parts = [p.strip() for p in self.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
if len(parts) >= TRUSTED_PROXY_HOPS:
    return parts[-TRUSTED_PROXY_HOPS][:64]
```
**Acceptans:** test som skickar `X-Forwarded-For: 1.2.3.4, 9.9.9.9` och bevisar att hinken nycklas på `9.9.9.9`.

### B5 · En headerhemlighet står mellan internet och alla personuppgifter `Z-AUTH` · **HÖG**
`api_server.py:1779-1797` (kontrollen), `2161-2194` (`/api/admin/backup-download`)

Jämförelsen är korrekt (`hmac.compare_digest`) och alla tretton `/api/admin/*`-vägar går genom den — det är kontrollerat. Men: ingen utgång, ingen rotation, ingen identitet, ingen revisionslogg. Och `/api/admin/backup-download` streamar hela `matjakt.db` med varje e-postadress i klartext, hela `synced_state` och all fritextfeedback.

**Gör:** (a) egen `MATJAKT_BACKUP_TOKEN` för nedladdningen, skild från kontrollrummet; (b) kryptera arkivet innan det lämnar processen (`age`/`gpg` med publik nyckel — servern behöver bara den publika); (c) logga varje godkänt `_admin_ok()` med väg, maskerad IP och request-id.

**Acceptans:** test att kontrollrumstoken ger 404 på `backup-download`.

### B6 · Egen inloggning nollställer offrets IP-hink `Z-AUTH` · **MEDEL**
`api_server.py:2597-2599` → `ratelimit.py:205-217`

`clear_on_success("login", ip, email)` raderar båda hinkarna. En angripare med eget konto gör nio felgissningar, loggar in på sitt eget konto, och fortsätter. Kvar finns bara e-posthinken: 10 per 5 min ≈ 2 880 gissningar per dygn per konto — tillräckligt för svaga lösenord, och gränsen är åtta tecken utan komplexitetskrav (`store.py:230`).

**Gör:** `ratelimit.clear_on_success("login", email)` — aldrig IP-hinken.

**Acceptans:** test att IP-hinken överlever en lyckad inloggning från samma IP.

### B7 · Återställningstoken ligger kvar i adressfältet `Z-FRONT-CORE` · **MEDEL**
`api_server.py:2664` skickar `{APP_URL}/?reset={token}`. `app.js:4705` läser den men rensar URL:en först när nytt lösenord skickats in (`4712`). Fram till dess står full token i adressfält, historik och sessionsåterställning — en timme lång fullständig kontoövertagning.

CSP:n tillåter `plausible.io` och `cloud.umami.is` i både `script-src` och `connect-src`, och båda skickar sidans fulla URL som pageview. Metataggen är tom idag, så det är latent — men dagen någon slår på besöksstatistik läcker varje återställningslänk till tredje part.

**Gör:** rensa direkt vid inläsning, före allt annat. Samma för `?verify=`.
```js
let pendingResetToken = new URLSearchParams(location.search).get("reset");
if (pendingResetToken) history.replaceState(null, "", location.pathname);
```
**Acceptans:** E2E som bevisar att `location.search` är tom direkt efter boot med `?reset=`.

### B8 · Kontovägar utan rate limit, och inget anslutningstak `Z-AUTH` · **MEDEL**
`/api/auth/me` (2314), `/api/entitlements` (2257), `/api/account/state` GET (2322) och POST (2745), `/api/account/marketing` (2981) anropar aldrig `_rate_limit`. Alla går genom `AccountStore` med en delad SQLite-anslutning bakom ett processglobalt `RLock`, och POST skriver upp till 200 kB per anrop. En klient som hamrar den vägen serialiserar hela kontolagret.

`ThreadingHTTPServer` (`api_server.py:3541`) startar dessutom en tråd per anslutning utan tak. `timeout = 30` skyddar mot Slowloris per anslutning; inget hindrar 5 000 trådar på en 512 MB-instans.

**Gör:** `public`-hink på läsvägarna, egen `("state", 60, 60)` på skrivvägen, och en `BoundedSemaphore` runt `process_request` (`MATJAKT_MAX_CONNECTIONS`, standard 64).

**Acceptans:** test att anslutning nr 65 avvisas snabbt i stället för att skapa en tråd.

### B9 · Sessionstokenfragment i klartext i backupen `Z-AUTH` · **MEDEL**
`api_server.py:1818`, `2628`, `2691` skickar `(self._bearer_token() or "")[:16]` som rate-limit-identifierare, och `ratelimit.py:170-174` skriver den oförändrad till `rate_limit_hits.identifier` — en fil i datakatalogen som följer med i backupsetet och i tar.gz:en från B5. Det motsäger uttryckligen policyn i `store.py:66-79`.

**Gör:** `hashlib.sha256(token.encode()).hexdigest()[:32]`.

**Acceptans:** test att ingen rad i `rate_limit_hits` innehåller ett prefix av en levande token.

### B10 · GDPR: export saknas, spår lämnas kvar `Z-AUTH` · **MEDEL**
Radering finns och är gedigen. Men:
- Ingen dataexport (art. 20). `GET /api/account/state` ger bara appstaten, inte e-post, prenumerationshistorik, hushållsmedlemskap, samtyckestidpunkt eller feedback.
- `mail_log` (`mailings.py:87-94`) rensas aldrig vid kontoradering.
- `api_server.py:2570` och `2574` loggar användarens e-postadress — de enda två ställena i hela backenden, och de motsäger `observability.py:16-17`.
- `backup.py:24-25` påstår i sin docstring att inga hemligheter finns i filerna. Sant om credentials, falskt om personuppgifter.

**Gör:** `GET /api/account/export` (JSON: konto, synced_state, hushåll, skafferi, lista, analytics, prenumeration), `DELETE FROM mail_log WHERE user_id = ?` i `delete_account`, logga domändelen i stället för adressen, rätta docstringen.

**Acceptans:** test att exporten innehåller alla sju datakategorier och att `mail_log` är tom efter radering.

---

# VÅG C — Priser

*Produktlöftet står och faller här. Alla fynd nedan är körda mot koden, inte lästa ur den.*

### C1 · Portionspriset räknar bort de rader det själv kallar täckta `Z-PRICING` · **KRITISK**
`backend/services/recipes/prices.py:96-102` + `grocery/pricing.py:1726-1746`

`covered = realPriceItems + estimatedItems` släpper igenom recept med osäkra rader. Men `totalCheckoutCost` summerar bara rader med `exactPackaging` — en osäker rad får `row["totalCost"] = None` och bidrar med **noll kronor**. Receptet passerar "full match or nothing"-spärren och får ett portionspris där en hel ingrediens saknas.

Modulens egen docstring förbjuder precis detta: *"A portion cost that quietly omits the chicken … is the worst direction to be wrong in."*

**Gör:** kräv `realPriceItems == totalItems`, eller markera receptet som oprissatt när `estimatedItems > 0`. Lås med test i `test_recipe_pricing.py`.

**Acceptans:** ett recept med en osäker rad får `price_per_portion = None`, inte ett för lågt tal.

### C2 · Multipack läses som enkelförpackning `Z-PRICING` · **HÖG**
`grocery/pricing.py:992-1009`

`_SIZE_MASS_VOL_RE` provas först och returnerar direkt; `_SIZE_COUNT_RE` provas bara om den inte träffade. Kört mot verkliga strängformat:

| Sträng | Tolkas som | Borde vara |
|---|---|---|
| `450 g 2-pack` | 450 g | 900 g |
| `33 cl 24-pack` | 33 cl | 7,92 l |
| `390 g 4-pack` | 390 g | 1 560 g |
| `2x120g` | 240 g | ✅ rätt |

Veckan behöver 1 500 g krossade tomater; produkten är "Krossade Tomater 390 g 4-pack, 32 kr". Motorn räknar `ceil(1500/390) = 4 förpackningar × 32 kr = 128 kr` — **sexton burkar** för en rätt som behövde fyra. Raden är dessutom märkt `exactPackaging=True` och går alltså in i den "säkra" totalen och i Billigast-underlaget.

**Gör:** multiplicera mass/volym-träffen med ett efterföljande `N-pack`/`N-p`-antal i samma sträng.

**Acceptans:** de fyra strängarna ovan låsta i `test_units.py`.

### C3 · Vitlök prissätts som knoppar, inte klyftor `Z-PRICING` · **HÖG**
`grocery/pricing.py:888` sätter `"vitlok": 70` gram per styck. Receptbanken har **80 recept** med vitlök i "st": 33 recept med `2 st`, 25 med `3 st`, 9 med `1 st`, 3 med `4 st`.

Ingen svensk husmansrätt tar tre hela vitlöksknoppar. Recepten menar klyftor (~5 g). Motorn räknar 3 × 70 = 210 g. En vecka med fem vitlöksrecept blir ~840 g vitlök — cirka 125 kr på en veckobudget som skulle varit 15, och en påse som ruttnar.

**Gör:** inför `vitlöksklyfta ≈ 5 g` och normalisera receptbankens `vitlök + st` till klyftor. Granska samtidigt `korv: 60`, `brod: 35` och `dill: 20` (örtkruka) på samma sätt.

**Acceptans:** test som prissätter ett recept med "vitlök 3 st" och kräver under 5 kr på den raden.

### C4 · Kampanjprissatta viktvaror prissätts som paketpris `Z-PRICING` · **HÖG**
`pricing.py:1526-1534` + `967-971`, `providers/citygross.py:275`

`kilo_price_signature()` jämför `unit_price` mot `regular_price`. City Gross sätter `unit_price = currentPrice.comparativePrice` (kampanjens kr/kg) medan `regular_price = ordinaryPrice`. Under kampanj skiljer de sig → signaturen faller → `weight_priced` blir aldrig sant → kilopriset används rakt av som paketpris.

Fläskkarré ca 1,2 kg, ord. 99 kr/kg, kampanj 79 kr/kg. Motorn: en förpackning = 79 kr. Kassan: 94,80 kr. Felet går **alltid nedåt** och drabbar just kampanjvaror — vilket gör kedjan med kampanjen orättvist billigast i jämförelsen.

**Gör:** jämför `unit_price` mot `effective_price(price)`, inte mot `regular_price`.

**Acceptans:** test med kampanjprissatt viktvara som kräver rätt totalkostnad.

### C5 · Utgångna kampanjer kan visas i månader `Z-PRICING` · **HÖG**
`pricing.py:1302-1310` skyddar bara rader som *har* `valid_to`. Bara Primat och partnerfeeden sätter det; Axfood (Willys/Hemköp), City Gross och ICA gör det aldrig. Kampanjen försvinner först vid nästa **lyckade** import — och `publish.py:242-252` behåller medvetet gårdagens dataset när gaten faller.

Willys-importen faller fem dygn i rad. Kunden får fortsatt torsdagens extrapris på fläskfilé, går till butiken och betalar ordinarie.

**Gör:** maximal kampanjålder (8 dygn utan `valid_to` → falla tillbaka på ordinarie), och läs promotionens slutdatum ur Axfood-payloaden där det finns.

**Acceptans:** test att en kampanjrad äldre än gränsen inte längre används.

### C6 · Referenspriser har ingen åldersgräns alls `Z-PRICING` · **HÖG**
`pricing.py:1438-1446`. `MAX_STORE_PRICE_AGE_SECONDS = 4 dygn` gäller bara verifierade butikspriser. Referenspriserna läggs in utan cutoff. Enda spärren är `MAX_AGE_SECONDS_FOR_COMPARISON = 14 dygn` (`api.py:57`) — och den blockerar bara kröningen, inte visningen.

Dör City Gross-importen i tre månader ser kunden fortfarande fulla priser och en total. Varningstexten säger dessutom fel sak ("För få av varorna har aktuellt pris…", `app.js:2330`) eftersom `comparable` slår ihop täckning och ålder i en flagga.

**Gör:** egen åldersgräns för referensnivån, och skilda orsakskoder `too_old` / `low_coverage` hela vägen ut i UI-texten.

**Acceptans:** test per orsakskod.

### C7 · Kassasumman utelämnar tyst de osäkra radernas kostnad `Z-PRICING` · **HÖG**
`pricing.py:1733-1746`, `app.js:2336, 2355`. "Total kassakostnad" summerar rader med `totalCost != null`; en osäker rad bidrar med noll. Det står "N med uppskattat antal" bredvid, men rubriksiffran är ändå lägre än kassan. Tre msk-rader (honung, olivolja, tomatpuré) → ~60 kr saknas. Användaren budgeterar 640 och betalar 700.

**Gör:** visa totalen som ett golv, inte ett exakt tal: **"minst 640 kr + 3 varor utan säkert antal"**. Systemet kan uttrycka "den här raden vet vi inte" men inte "den här summan är minst X" — det är den saknade begreppet.

**Acceptans:** test att rubriksiffran aldrig presenteras som exakt när `rowUncertain` finns.

### C8 · Ingen rimlighetsspärr i motorn `Z-PRICING` · **MEDEL**
`audit.py:96-105` vet vad som är orimligt (>500 kr/rad, >10 paket, kilopris-som-paketpris) — men bara i offline-auditen. `price_item()` har ingen motsvarande kontroll.

Verkligt fall ur `audit_flags.tsv`: *rostbiff-potatissallad · Rostbiff · 400 g · Willys · "Rostbiff i Skivor Sverige" · 2 paket · **538,00 kr***. Delikatess-skivor (≈673 kr/kg) prissatta som stekbit. `WHOLE_CUT_FORBIDDEN_DEPARTMENTS` räddar inte, för kategorin mappas till `meat`, inte `coldcuts`.

**Gör:** (a) namnregel `rostbiff: exclude ["skivor", "deliskivor", "i skivor"]`; (b) flytta in rimlighetskontrollerna i `price_item()` så en orimlig rad blir **osäker** i stället för dyr — samma mekanism som redan finns för gissade paketantal.

**Acceptans:** rostbiffsfallet ger `rowUncertain`, inte 538 kr.

### C9 · Skafferiavdraget är enhetsblint `Z-PRICING` · **MEDEL**
`pricing.py:1698-1716` antar att skafferiets tal är i basenhet och väljer enhet efter receptradens enhet. Frontend skickar bara ett tal — `household-state.js:117-124` kastar bort `unit`-kolumnen som hushållsdatabasen faktiskt har (`household/store.py:222, 831`).

Två fel i motsatt riktning: "Ris 2 (kg) hemma" mot en 500 g-rad drar av **2 gram** (funktionen "har hemma" gör i praktiken ingenting för vikt- och volymvaror). Och "Potatis 1000" (gram) mot receptets "Potatis 4 st" drar av **1 000 st** — potatisen försvinner helt ur listan och ur totalen.

**Gör:** skicka med enheten och konvertera med `convert_amount`; vägra avdrag vid ojämförbara enheter (fallbacken finns redan på rad 1716).

**Acceptans:** båda fallen ovan som test.

### C10 · Auditens smakordsflagga är delsträngsmatchning `Z-PRICING` · **LÅG men brådskande**
`audit.py:106` + `FLAVOR_SUSPECTS:11-12` gör `any(word in _fold(name))`. `"te "` finns inuti `"penne riga**te** pasta"`. **75 av 114** `smakords_misstanke` i `audit_result.json` är "Pasta → Penne Rigate Pasta" — rena falsklarm. Det är exakt den bugg motorn själv övergav i `_exclusion_hit` (`pricing.py:1053-1085`).

Konsekvensen är larmtrötthet: 114 flaggor ingen orkar läsa, och en riktig träff drunknar.

**Gör:** återanvänd `_exclusion_hit` i auditen.

**Acceptans:** "Penne Rigate Pasta" flaggas inte.

---

# VÅG D — Drift och datainhämtning

*Systemet är stabilt mot dataskada och bräckligt mot tystnad.*

### D1 · Larmen har ingen mottagare `Z-GROCERY` · **KRITISK**
`grocery/alerts.py:59, 175-179`. `admin_email()` läser `MATJAKT_ADMIN_EMAIL` — som **inte finns** i `render.yaml`, **inte** i `.env.example`, och bara nämns i tester (verifierat). Saknas den skrivs incidenten till databasen och hamnar i `resultat["skipped"]`. Hela larmkedjan är byggd, testad och tyst.

**Gör:** `MATJAKT_ADMIN_EMAIL` i `render.yaml` (`sync: false`), och `alertsRecipientConfigured` i `/api/health` så avsaknaden syns i stället för att tigas ihjäl.

**Acceptans:** health visar `false` när variabeln saknas.

### D2 · Ingen kontroll av prisNIVÅ `Z-GROCERY` · **HÖG**
`publish.py:42-52, 58-92`. Gaten kontrollerar antal rader (≥30 % av föregående) och radformat (0 < pris ≤ 30 000). Ingenstans jämförs nytt pris mot gammalt för samma produkt. En decimalbugg — öre tolkat som kronor — passerar 95 %-gaten glatt: alla rader är sunda var för sig.

Matjakts hela värdeerbjudande är "vem är billigast". En kedja vars priser råkar delas med tio kröns Billigast och ingenting larmar.

**Gör:** medianförändring per körning mot `grocery_current_prices`. Avviker medianen mer än ±25 %, eller rör sig >40 % av raderna åt samma håll — publicera inte.

**Acceptans:** test med ett dataset där alla priser dividerats med tio; publiceringen ska stoppas.

### D3 · Missad körning återförsöks aldrig `Z-GROCERY` · **HÖG**
`scheduler.py:205, 508-533`. Tre fel i samma loop: fönstret är fem minuter (en deploy 02:03–02:05 hoppar över Willys helt den natten); `_last_fired[chain]` sätts **före** `importer.start()` (rad 524 vs 527), så en kedja som fick `already_running` markeras ändå som körd; och `_last_fired` ligger i minnet, så en omstart mitt i fönstret kan köra samma jobb två gånger.

En Willys-körning som drar över till 03:00 tar med sig Hemköp för hela dygnet, och det syns först som ett `stale`-larm efter 36 h — om larmen hade en mottagare.

**Gör:** markera först vid faktisk start, persistera i KV-store, och byt fönstret mot "kör om jobbet inte kört i dag och klockan passerat".

**Acceptans:** test att `already_running` inte konsumerar dygnets körning.

### D4 · "Noll produkter i natt" upptäcks tidigast efter 36 timmar `Z-GROCERY` · **HÖG**
`api.py:360, 407-419`. En körning som ger noll rader blir `status="failed"`, men `chain_health` returnerar `failed` bara om det saknas en tidigare lyckad körning. Finns en success från i går är statusen `healthy` tills `CHAIN_STALE_AFTER_SECONDS = 36 h` passerats — och då bara som `warning`.

Willys byter API-form tisdag natt. Onsdag hela dagen: allt ser friskt ut.

**Gör:** "senaste FÖRSÖKET misslyckades" som eget larmvillkor oavsett historik; sänk stale-gränsen för släppta kedjor till ~30 h så nattens resultat bedöms samma morgon.

**Acceptans:** test att ett misslyckat försök larmar direkt.

### D5 · ICA/Coop importeras om vid varje deploy och bränner kvoten `Z-GROCERY` · **HÖG**
`scheduler.py:251`, `importer.py:249`, `api.py:455`, `providers/primat.py:106`

`bootstrap_if_empty` startar varje schemalagd kedja som saknar `lastSuccessfulRun`. En Primat-körning som slår i radtaket kastar `ProviderBlockedError`, publiceras partiellt och märks `status="blocked"` — aldrig `"success"`. `provider_status` hämtar senaste lyckade körning med `WHERE status = 'success'`, så `lastSuccessfulRun` förblir `None` för alltid.

Varje deploy startar alltså ICA *och* Coop på nytt, var och en med tak `PRIMAT_MAX_ROWS_PER_RUN=40000` mot en dygnskvot på 20 000 — taket är dubbelt så högt som kvoten. Två deployer samma dag = kvoten slut.

**Gör:** låt `blocked` med publicerade rader räknas som genomförd körning (eller inför `last_completed_run`), sänk taket under dygnskvoten, och gör bootstrap beroende av `products == 0` i stället för av körningsstatus. Bokför förbrukade rader per dygn och kontrollera **före** start.

**Acceptans:** test att två bootstraps i rad inte startar samma kedja två gånger.

### D6 · City Gross tappar hela avdelningar tyst `Z-GROCERY` · **MEDEL**
`providers/citygross.py:426-428, 372-403, 158-163`. Axfood spårar `failed_categories` och gör körningen partiell. City Gross loggar och `break`:ar — körningen rapporteras `success`. Kedjan faller dessutom tillbaka på en hårdkodad avdelningslista med sajtens egna sid-id och en allow-list på avdelnings*namn*: döper City Gross om "Skafferiet" försvinner avdelningen utan ett enda felmeddelande. 30 %-regeln fångar bara om över 70 % försvinner.

**Gör:** samma `failed_categories`-spårning; larma när antalet insamlade avdelningar understiger föregående körning.

**Acceptans:** test att ett kategorifel gör körningen partiell.

### D7 · Två providers håller hela katalogen i RAM `Z-GROCERY` · **MEDEL**
Axfood streamar via `on_products` — bra. City Gross saknar `get_products_by_category` och returnerar hela listan (~8 700 `RawProduct`) på en gång; Primat håller `price_rows` + `details` för en hel Maxi-katalog. Samtidigt kör processen Chromium på en 512 MB-instans. En OOM under bootstrap är särskilt otäck: databasen förblir tom → nästa boot triggar samma bootstrap → hammarloop.

**Gör:** samma `on_products`-streaming i City Gross och Primat.

**Acceptans:** minnesmätning i test, eller minst ett test att `_collect` inte materialiserar hela listan.

### D8 · SQLite: inget `busy_timeout`, schemamigrering per request `Z-GROCERY` · **MEDEL**
`store.py:47-61` skapar ny anslutning och kör `_init_schema` + `_migrate_schema` vid **varje** anrop — `PRAGMA table_info` × 4 plus ett `executescript` per HTTP-request som rör grocery. `bulk_transaction` (`publish.py:281`) håller skrivlåset under hela publiceringen av ~10 000 upserts, och `busy_timeout` sätts aldrig (default 5 s) → samtidiga skrivningar kastar `OperationalError` mitt i nattens publicering.

`_CACHE` är dessutom process-global och töms **helt** vid 200 poster (`api.py:81-82`) — ingen LRU, alltså thrashing vid trafikvariation. `clear_cache()` är in-process: med två instanser serverar den ena gamla priser i fem minuter efter en import.

**Gör:** `PRAGMA busy_timeout=15000`, en anslutning per tråd i stället för migrering per request, och `clear_cache` som en `data_version`-koll mot databasen så flera processer självläker.

**Acceptans:** samtidighetstest som skriver under pågående publicering.

### D9 · robots.txt läses aldrig för de kedjor som faktiskt skrapas `Z-GROCERY` · **MEDEL**
Coops och ICA:s robots.txt är utredda och dokumenterade — men det är just de kedjor ni **inte** skrapar. Willys, Hemköp och City Gross är det inte. User-Agent utger sig dessutom för att vara Chrome 120 med ett `Matjakt/1.0 (+grocery-collector)`-suffix, utan kontakt-URL (till skillnad från `dabas.py:74`). Att maskera sig som webbläsare *och* identifiera sig halvvägs är den sämsta av två världar.

**Gör:** hämta och logga robots.txt per kedja vid varje körning och avbryt om sökvägen är förbjuden; byt UA till `Matjakt/1.0 (+https://matjakt.store/om-insamling)`. Skriv upp Primat-fallback för Willys/Hemköp som dokumenterad reservväg — Axfood kan lägga på samma WAF som ICA när som helst, och då står två av tre släppta kedjor still.

**Acceptans:** test att en `Disallow`-regel stoppar körningen.

### D10 · Backup och canary `Z-GROCERY` · **MEDEL**
Backupen är rätt byggd (sqlite backup-API, `integrity_check`, underkänd kopia raderas, sju set) men **oövervakad**: `newest_age_seconds()` anropas bara av backup-tråden själv, syns varken i `/api/health` eller `storage_info()`, och det finns inget `tests/test_backup.py`. Återställning är en manuell månadsbock i `docs/BACKUP.md`, inte ett test.

Lägg samtidigt in en **canary per kedja**: ett känt GTIN med känt prisintervall som kontrolleras efter varje import. Det är den billigaste möjliga upptäckten av "sajten ändrade sig".

**Gör:** backup-ålder i health + som larmvillkor; CI-test som tar backup av en fixturdatabas och startar mot återställningen; canary per kedja.

**Acceptans:** CI-testet finns och är grönt.

---

# VÅG E — Frontend-buggar

### E0 · Render-buss `Z-FRONT-CORE` · **först, ensam, ~30 rader**
`app.js:3657`. `render()` = `renderGreeting + renderRecipes + renderHemRecipePreview + renderBasket + updateSummary + renderStats + renderCampaignSection`. Att bocka av **en** vara i Handla river och bygger hela receptbiblioteket (200+ kort med bilder) och binder om alla lyssnare.

Ersätt de direkta anropen med `invalidate("basket" | "recipes" | "account")` som samlar i en `requestAnimationFrame`. Det här är förutsättningen för att E- och F-paketen ska kunna flytta funktioner utan att röra anropsordningen.

**Acceptans:** avbockning i Handla ritar inte om receptlistan (mät antal `innerHTML`-skrivningar i test).

### E1 · `app-state.js` `Z-FRONT-CORE` · **näst, ensam, ~250 rader**
Flytta `state`-literalen (`173-181`), `buildSyncPayload`, `applySyncBlob`, `saveState`, `scheduleServerSync`, `flushServerSync`, `setWeekPlan`, `addToWeekPlan`, `removeFromWeekPlan`, `swapWeekPlanDay`, `selectedRecipes` till `src/state/app-state.js`. Lös samtidigt E2, E3 och E4 här. **Alla F-paket beror på det här.**

### E2 · Dagsindex spricker när ett recept saknas `Z-FRONT-CORE` · **HÖG**
`app.js:131-134`. `selectedRecipes()` gör `.map(...).filter(Boolean)`. Saknas ett id — receptbanken inte laddad, recept borttaget i backend, provider-recept rensat vid utloggning — **förskjuts alla efterföljande dagar ett steg**. Samtidigt indexerar `swapWeekPlanDay(dayIndex)` in i den ofiltrerade `state.weekPlan`. De två indexrymderna divergerar: onsdagens rätt märks "Tis", och bytesrutan säger "Ons middag · nuvarande: …".

```js
function selectedRecipes() {
  const all = [...RECEPT, ...state.apiRecipes];
  return state.weekPlan.map(id => all.find(r => r.id === id) ?? null);  // null = tom dag
}
```
Låt varje render-site hantera `null` — `weekEmptyDayMarkup()` finns redan.

### E3 · localStorage: ingen version, ingen migrering, tyst kvotfel `Z-FRONT-CORE` · **HÖG**
`src/state/storage.js:12-19` returnerar `false` vid `QuotaExceededError` — och `app.js:286` (`saveState`) **ignorerar returvärdet** och visar ändå "Sparat på den här enheten". Blobben växer obegränsat: `weekHistory` (12 veckor), `savingsLog` (60), `stapleItems` (60), `apiRecipes`, `dbChainTotals` med hela item-listor. På iOS Safari (5 MB) är det nåbart. Användaren tror att veckan är sparad.

Ingen `schemaVersion` finns. Trasig JSON → `{}` → appen nollställs tyst och skriver över den trasiga datan vid nästa sparning.

**Gör:** `SCHEMA_VERSION`, en `normalizeState(blob)` som både boot-raden och `applySyncBlob` går genom, och `if (!writeStoredState(...)) setSyncStatus("error")` med texten *"Enhetens lagring är full — logga in så sparas veckan på kontot."*

### E4 · `applySyncBlob` litar blint på serverns blob `Z-FRONT-CORE` · **MEDEL**
`app.js:190-222`. Vid boot valideras `weekPlan` med `Array.isArray` och `personer` klampas till 1–12. I `applySyncBlob` görs ingen av kontrollerna. En gammal serverblob med `weekPlan` som objekt ger `TypeError: state.weekPlan.map is not a function` — och `pullAccountState` har `catch {}` (`284`), så synken misslyckas **tyst för alltid**. Samma `normalizeState` som i E3 löser det.

### E5 · Kampanjhämtningen blir en anropsstorm efter fel `Z-FRONT-CORE` · **HÖG**
`app.js:4776-4829`, anropad via `render()` på `3657`. Vid fel sätts `ownCampaignFetchKey = null` **och** en retry-timer schemaläggs. Eftersom `render()` körs vid varje interaktion kör nästa render `renderOwnCampaigns()` direkt utan cooldown: ett `/grocery/campaigns`-anrop per knapptryck plus en parallell exponentiell retry-kedja som aldrig avbryts.

**Gör:** `ownCampaignFetchKey` blir en tidsstämpel med cooldown-grind; avbryt gammal timer innan ny sätts. Samma mönster på prisretryn (`1688`), där timers också staplas.

### E6 · Inga timeouts på konto-, auth- och hushålls-API `Z-FRONT-CORE` · **HÖG**
Prisanropen har `AbortSignal.timeout(...)`. `src/api/auth.js` (alla 15 anrop) och `src/api/household.js:21-32` har **ingenting**. `refreshUser()` (`4746`) awaitar `fetchCurrentUser` innan `renderAccount()`, `loadHousehold()` och `loadNotifications()` — ett hängande anrop på dåligt mobilnät fryser hela kontoinitieringen för resten av sessionen. Inloggningsknappen inaktiveras dessutom aldrig (`4863`), så användaren kan dubbelsubmitta mot en död knapp.

**Gör:** delad `request()` i ny `src/api/http.js` med `AbortSignal.timeout(15000)`; `auth.js` och `household.js` går genom den. `disabled` på submit.

### E7 · Råa engelska tekniska fel visas för användaren `Z-FRONT-CORE` · **HÖG**
`src/api/auth.js:23` gör `new Error(data.error || "HTTP " + status)` och `app.js:4872, 4891, 5006, 5014` skriver det rakt in i `$("loginError").textContent`. Går nätet ner kastar `fetch` en `TypeError` — användaren ser bokstavligen **"Failed to fetch"** i en svensk app.

**Gör:** ett översättningslager likt `mailErrorText()` (`4691`). Nätfel → *"Ingen kontakt med Matjakt. Kolla nätet och försök igen."*

### E8 · Två flikar skriver över varandra tyst `Z-FRONT-CORE` · **HÖG**
Inget `window.addEventListener("storage", …)` finns någonstans. Varje flik håller `state` i minnet och skriver hela blobben vid varje `saveState()`. Bockar man av varor i flik A och byter recept i flik B försvinner A:s bockningar. Med konto debouncar båda mot `/account/state` och sista skrivningen vinner.

**Gör:** lyssna på `storage`; när `matjakt-state` ändras av en annan flik, visa *"Matjakt är öppen i en annan flik — ladda om för att se den senaste versionen."* Full CRDT behövs inte; ett besked gör det.

### E9 · Butiksvalet kör kombinatorik per butik, per tangenttryck `Z-FRONT-CORE` · **HÖG**
`app.js:1194-1218` (`cheapestBranch`), `1232-1237`, `891-913`, `3695`. `cheapestBranch()` gör en fullständig kombinationssökning **per närbutik** — koden kommenterar själv att en sjudagarsvecka ger 30–40k kombinationer; med tio filialer är det 300–400k, plus `shoppingListCost` per resultat. `branchCache`-nyckeln innehåller `state.budget`, och budgetfältets lyssnare kör hela sökningen **per tangenttryck**. `everydayRank` använder dessutom `Math.random()`, så samma nyckel kan ge olika "billigaste butik".

**Gör:** (a) debouncea budgetfältet 250 ms; (b) plocka ut receptvalet ur `cheapestBranch` — butiksvalet behöver inte en egen veckoplan per butik; (c) seeda slumpen per "skapa vecka"-tillfälle.

### E10 · Dubbelbundna lyssnare på "Ser något fel ut?" `Z-FRONT-VIEW` · **MEDEL**
`app.js:2985` binder `[data-report-price]` i `renderBasket()`, men knappen renderas in i `#chainListBody` av `chainShoppingListMarkup` (`2355`) — som `renderWeekOverview` inte ritar om. Varje `renderBasket()` (varje livepris-chunk, varje synksvar, varje avbockning) lägger på ännu en lyssnare på samma nod. Efter en stund skickar ett klick N stycken `prisfel_rapporterat`-events.

**Gör:** flytta bindningen in i `openChainShoppingList` efter `body.innerHTML = …`.

### E11 · Rader och total avrundas var för sig `Z-FRONT-VIEW` · **MEDEL**
`app.js:785` (`money = Math.round`), `2335-2337`, `2384`, `3203`. `chainShoppingListMarkup` summerar `item.totalCost` i fullt flyttal och rundar summan, men varje rad skrivs ut avrundad var för sig. Med tjugo rader kan raderna summera till 10 kr fel mot headern — trots att kommentaren på `2331-2334` uttryckligen lovar att de ska stämma.

**Gör:** öre-baserad summering (`Math.round(x*100)`) och summera de **avrundade** radbeloppen till headern.

### E12 · Provider-recept dubbelescapas `Z-FRONT-VIEW` · **MEDEL**
`app.js:755` gör `steg: (recipe.instructions || []).map(escapeHtml)` vid intag, `1500` gör `escapeHtml(step)` vid rendering. "salt & peppar" visas som "salt &amp;amp; peppar". Kommentaren precis ovanför förklarar varför rå text ska sparas i state. **Ta bort `.map(escapeHtml)` på rad 755.**

### E13 · Misslyckad butikshämtning ger permanent tomt tillstånd `Z-FRONT-VIEW` · **MEDEL**
`app.js:1079` kör `clearLocationDerivedState()` **före** anropet; vid nätfel är listan redan tömd och ingen retry schemaläggs. Användaren står kvar med "Hittade inga inlästa butiker nära 12345 ännu" tills hon råkar redigera postnummerfältet. Prisretryn har backoff; butikshämtningen har ingen alls.

**Gör:** samma `retryDelay(count)`-mönster, och rensa inte gammalt tillstånd förrän nytt anlänt.

### E14 · `aggregateShopping` muterar delat tillstånd under rendering `Z-FRONT-VIEW` · **MEDEL**
`app.js:3514-3543` ser ut som en ren beräkning men raderar ur `state.removedItems`, `state.avklarade` och `state.harHemma` — utan `saveState()`. Anropas från minst sex ställen. Följdfelet: namnlistan bygger på `aggregateIngredients`, som i den strukturerade grenen filtrerar bort `optional` (`calculations.js:57`) medan kort-projektionen behåller dem (`recipes.js:147`). När receptdetaljerna landar försvinner de valfria ingredienserna ur aggregatet — och deras "köpt"/"har hemma"-status raderas tyst.

**Gör:** bryt ut `prunePhantomItemNames()` som körs **en gång** när veckans recept är fullständigt laddade; låt `aggregateShopping` vara ren.

### E15 · Service worker + minneslläckor `Z-FRONT-CORE` · **MEDEL**
Tre saker i ett paket:
- **Offline fungerar inte för URL:er med query.** `sw.js:33-51` matchar på exakt URL. Alla djuplänkar bär query (`?recept=`, `?invite=`, `?verify=`, `?reset=`, `?billing=success`) och finns inte i cachen. Fall tillbaka på `caches.match("./")` för `mode === "navigate"`.
- **Versionsbumpen är trippelmanuell.** `sw.js:8` (`matjakt-shell-v42`), `index.html:39` och `:591` (`?v=42`). Tre handredigerade tal som måste vara lika. Generera från ett byggsteg och lås med test.
- **`createDebouncedSearch` lämnar promises som aldrig settlar.** `recipe-search.js:12-21` gör `clearTimeout` utan att resolva/rejecta den föregående — varje tangenttryck lämnar en hängande promise med closure. Rejecta med `AbortError` (anroparna ignorerar redan den).

**Mindre fynd att ta med i valfritt E-paket:** bilder utan `width`/`height` (10 st, ger layoutshift); selektorinjektion på `app.js:3825` (använd `CSS.escape` som `4456` redan gör); `RECEPT.push(...RECEPT.splice(0, 8))` på `5056` muterar den globala receptbanken; `state.pushDeviceToken` läses men sätts aldrig.

---

# VÅG F — Refaktorering av app.js

*Kräver E0 + E1. Därefter helt parallellt — varje agent äger sitt eget radintervall och sin egen nya fil.*

| ID | Ny modul | Flyttar (nuvarande rader) | Löser |
|---|---|---|---|
| **F1** | `src/pricing/sync.js` | `syncDatabasePricing`, `syncLivePrices`, `syncBranchComparison`, `fetchProductsBatch`, `syncExtraMatches`, `retryDelay` (`1536-1776`, `3383-3479`) | E5, E13 |
| **F2** | `src/api/http.js` | delad `request()` med timeout; `auth.js`/`household.js` går genom den | E6, E7 |
| **F3** | `src/views/shopping.js` | `shoppingRowMarkup`, `handledRowMarkup`, `wireShoppingRowActions`, `renderBasket`, `renderExtraItems`, `aggregateShopping` (`2517-2680`, `3134-3314`, `3514-3543`) | E10, E11, E14 |
| **F4** | `src/views/recipes.js` | `renderRecipes`, `renderRecipePage`, `renderRecipeShelves`, `recipePhoto`, `mapApiRecipe` (`1285-1534`, `3339-3355`) | E12 |
| **F5** | `src/views/account.js` | `renderAccount`, `renderHousehold`, `renderNotificationPrefs`, `wireHouseholdUi`, onboarding, paywall (`3902-4252`, `4605-5015`) | G8, G13 |
| **F6** | `src/data/legacy-catalog.js` | `PRODUCT_CATALOG`, `PACKAGE_INFO`, `RECIPE_QUANTITIES`, `RECIPE_DETAILS` (`613-783`) — **kräver F3 + F4** | — |

**Mål:** `app.js` blir en `main.js` med imports, uppstartssekvensen (`5175-5297`) och render-bussen — 300–400 rader.

---

# VÅG G — Utseende och UX

**Designunderlag:** `DESIGNSYSTEM.md` och `mockup.html` (medföljer). Palett, typografi, komponentspecar, alla kontrastvärden uträknade, plus en migreringstabell från nuvarande CSS-variabler.

### G1 · Designsystemet in i `styles.css` `Z-STYLE`
Riktningen är vald: **D — "Middagskortet"**, en mattidning i telefonformat. Sval pappersvit `#ECEEEF` (ingen cream), oxblod `#8A1F42` som **enda** accent, Newsreader som display mot Archivo i gränssnittet, etiketter i spärrade kapitäler. Inga kort, inga skuggor inuti appen, inga pillerformade chips — hierarkin bärs av hårfina linjer, luft och asymmetri. Priset sätts som en bildtext, inte som ett utrop.

Lägg in de nya tokens i `:root` med det aliasskikt som `DESIGNSYSTEM-D.md` §9 specificerar, så `styles.css` kan bytas i etapper utan att appen går sönder mitt i. Införandeordningen står i §11.

Designsystemet räknade om varje kontrastpar och rättade tre saker i riktningen: `--ink-3` på `--paper-2` ger 4,31:1 och byts mot `--ink-2`; betydelsebärande linjer (streckad prissiffra, ramen runt "pris saknas", teckenförklaringen, månadsstaplarna) ritades i `--rule-2` = 1,68:1 och måste vara `--ink-3` = 4,68:1; hjältetextens skärm specas till 0,78 vilket ger 10,23:1 mot ett helvitt foto. Bygg efter dokumentet, inte efter mockupens CSS.

### G2 · "Ikväll" överst på Hem `Z-STYLE` · **högsta UX-effekt**
`styles.css:451` sätter `.week-card` till `order:1` och `.next-meal-section` till `order:2` — tvärtemot kommentaren i `index.html:54` som säger "IKVÄLL FÖRST". Det största elementet på startsidan är `54px` med kronbeloppet (`styles.css:458`).

En trött förälder klockan 16:10 möts av en budgetmätare ovanför kvällens mat. Budgetverktyg öppnar man en gång i månaden; middagsappar öppnar man varje dag.

**Gör:** kasta om `order`. Kvällens rätt blir hjältekortet, budgeten en smal rad under (mätare + kronsiffra i brödtextstorlek). Döp om fliken till **Ikväll** så namnet är samma löfte som skärmen ger.

### G3 · Hela veckan synlig `Z-FRONT-VIEW`
`index.html:209`: `<div class="week-overview-section week-plan-section" hidden>` — "Veckans plan"-listan är permanent dold. Kvar är sju dagflikar och ett dagskort i taget. Kärnfrågan appen finns för — *vad äter vi i veckan* — går inte att besvara med ögonen. Och "✓ Lagad" / "✗ Hoppade över" (`app.js:2851-2852`) är oåtkomliga, för de finns bara i den dolda listan.

**Gör:** ta bort `hidden`, gör listan till standardvyn — sju rader, alla synliga. Koden finns redan (`app.js:2936-2940`).

### G4 · Kontrastfel gör de viktigaste siffrorna osynliga `Z-STYLE`
`styles.css:96`: `.stats-card.highlight strong{color:var(--primary)}` — `#146c43` på `linear-gradient(150deg, var(--primary-2), var(--primary) 70%)`. Mörkgrönt på mörkgrönt, kontrast ≈ **1:1**. Det gäller "Uppskattat sparat denna vecka" och "denna månad" — de två viktigaste siffrorna i hela appen. Samma fel i `.week-summary .remaining strong` och `.store-compare-upsell` (`styles.css:82`).

**Gör:** enligt designsystemet — siffrorna flyttas till mörk yta, 1,04:1 → 16,22:1.

**Acceptans:** ett kontrasttest som failar under 4,5:1 för brödtext och 3:1 för stor text.

### G5 · Träffytor under 44 px `Z-STYLE`
`.week-sheet-plus` 28×28 (`305`) / 32×32 (`455`) — **enda vägen till kost & allergier**, det mest säkerhetskritiska i appen. `.shopping-remove` 30×30 (`318`) sitter dessutom *inne i* raden bredvid priset, i tumzonen där man annars trycker "Köpt" — ett feltryck tar bort varan. Vidare: `.week-plan-menu summary` 28×28, `.extra-remove` 24×24, `.extra-qty button` 26×26, `.recipe-star` 30×30, `.pantry-item-controls button` 36×36, `.account-modal-close` 36×36, `.hero-meal-swap` 36 px.

**Gör:** 44 px minimum genomgående (rivningslistan med alla fjorton träffarna finns i `DESIGNSYSTEM.md`). Flytta "ta bort" ur tumzonen: svep vänster + Ångra-toast.

### G6 · Modaler saknar fokushantering `Z-FRONT-VIEW`
`app.js:3786` är enda `Escape`-lyssnaren i hela appen. Plan-, swap-, konto-, skafferi-, cook-, paywall- och onboardingmodalerna: ingen fokusflytt vid öppning, ingen fokusfälla, ingen Escape, ingen `overflow:hidden` på body (bara `openWeekSheet` gör det). Tab-ordningen fortsätter rakt ner i sidan bakom. Onboardingmodalen går inte att stänga med tangentbord alls.

**Gör:** en gemensam `openModal(el)`: flytta fokus till rubriken, `inert` på `.phone-shell`, Escape stänger, fokus tillbaka till knappen som öppnade.

### G7 · "Skapa min vecka" skapar ingen vecka `Z-FRONT-VIEW`
`index.html:73` + `app.js:5048`: knappen öppnar `openPlanComparison()`. En knapp som lovar ett resultat och levererar ett formulär är den klassiska tillitsläckan.

**Gör:** knappen skapar veckan direkt. "Välj veckotyp" blir en sekundär länk — den finns redan (`index.html:178`).

### G8 · Betalväggen ur första-värde-ögonblicket `Z-FRONT-VIEW` · **dyraste avhoppet**
Onboardingens sista knapp heter "Skapa min vecka" (`app.js:4660`) men öppnar plan-modalen där **sju av åtta** veckotyper är låsta för en gratisanvändare (`FREE_FEATURES`, `940-948`). Det första en ny användare ser av produkten är en hänglåsvägg — innan hon sett en enda måltid eller en enda prislapp.

**Gör:** hoppa över modalen vid första veckan. Kör `chooseMenu()` rakt till Vecka-vyn och lägg "Vill du ha en familjevecka i stället?" som en rad *ovanför* den färdiga veckan. Sälj efter leverans, inte före.

### G9 · Postnummer är en hård grind före första värdet `Z-FRONT-VIEW`
`app.js:4666` kräver `/^\d{5}$/` för att passera steg 4 av 4. "Hitta mig" (`4651`) sväljer alla fel tyst — nekad platsdelning ger ingen text alls. Ett integritetsmotstånd precis innan värdet levereras, plus en återvändsgränd.

**Gör:** valfritt steg — *"Hoppa över — vi visar riksgemensamma priser tills vidare"* (`FALLBACK_BRANCH` på `app.js:612` stödjer det redan). Fråga om postnummer först vid "Handla".

### G10 · Byten: ett tryck, obegränsat `Z-FRONT-VIEW`
`app.js:4275-4350`: "Byt" → modal → tryck på alternativet (markerar bara) → "Byt till denna rätt". Två tryck där ett räcker. Och `FREE_SWAP_LIMIT = 3` (`4274`) visas först när man slagit i taket.

Byte är den handling som gör veckan *till din*. Att strypa den efter tre gånger, utan förvarning, straffar precis det engagemang som bygger vana.

**Gör:** tryck på alternativet = byte, med Ångra i toasten (mönstret finns på `3611`). Obegränsade byten gratis; sälj i stället byten *med avsikt* ("Billigare", "Mer protein") som Premium.

### G11 · En Inställningar-skärm `Z-FRONT-VIEW`
Kost och allergier — det mest säkerhetskritiska i appen — bor i ett bottenark bakom ett omärkt "＋" på 28×28 px i hörnet av veckokortet (`index.html:66`). Konto, hushåll, lösenord, prenumeration och radera konto ligger i ett enda långt modalt scroll (`350-519`). Det finns ingen Inställningar-skärm.

**Gör:** en riktig skärm: Hushåll & personer · Kost och allergier · Budget · Butik & plats · Konto · Prenumeration · Notiser · Integritet.

### G12 · `alert()`, `confirm()` och falska handlingar `Z-FRONT-VIEW`
`app.js:4991` gör `alert(...)` mitt i ett betalflöde; `4125` och `4738` använder `confirm()` för att lämna hushåll och radera konto. Systemdialoger i en app som annars har välarbetade bottenark.

Dessutom: "Visa alla" på Veckans fynd (`4839`) scrollar bara raden till slutet, och "Byt förslag" (`5052`) roterar `RECEPT` åtta steg. Båda ser ut som navigering, båda är kosmetik.

**Gör:** egna dialoger; "Visa alla" → riktig fyndlista med filter per kedja; "Byt förslag" → slumpa ur `availableRecipes()` med en `seen`-lista.

### G13 · Handla börjar med listan, och hushållet blir synligt `Z-FRONT-VIEW`
`index.html:243-247`: Handla-vyn börjar med hushållsnot → kostnadsvarning → basvarufråga → priskällenot → "Var blir det billigast?" → butikskort → framstegsmätare → *sedan* listan. I butik, med varorna framför sig, ska listan vara det första. Flytta butiksvalet till Vecka.

Hushållet är samtidigt appens starkaste virala kanal och bästa retention-mekanik — och marknadsförs inte en enda gång. Vägen dit är sju–åtta steg som ingen föreslår. Lägg en rad överst i Handla när inget hushåll finns: *"Handlar ni ihop? Dela listan med den du bor med →"*.

### Texter att skriva om (ingår i G-vågen)

| Var | Nu | Ska bli |
|---|---|---|
| `auth.js:23` | "Failed to fetch" / "HTTP 500" | "Ingen kontakt med Matjakt just nu. Kolla nätet och försök igen." |
| `app.js:4572` | "Underlag saknas" | "Här dyker din första sparsumma upp" |
| `app.js:4598` | "Kan inte beräknas ännu – kräver två jämförbara butiker" | "Vi jämför så fort två butiker har priser på din lista" |
| `app.js:1885` | "Pris ej tillgängligt – för få varor prissatta" | "Vi kan inte prissätta din lista här än" |
| `app.js:2137` | "Bara en butik har tillräckligt med aktuella priser för en jämförelse" | "Bara en butik har priser på hela din lista den här veckan" |
| `app.js:3322` | "Uppskattat pris - hämtar priser hos Willys..." | "Hämtar priser hos Willys" |
| `app.js:234` | "Kunde inte synka - försöker igen" | "Kunde inte spara till ditt konto — vi försöker igen" |
| `app.js:3223` | "Listan väntar på din vecka" | "Ingen lista än. Skapa veckan så fylls den." |
| `index.html:81` | "Skapa en vecka först" | "Din lista fylls när veckan är klar" |
| `index.html:49` | "Du är offline - listan och veckan visas från senaste besöket." | "Du är offline. Listan och veckan funkar ändå — priserna kan vara gamla." |
| `index.html:284` | "Sparanderesultat" | "Vad du sparat" |
| `index.html:291` | "Skapa en vecka för att se detta" (som *värde* i ett `<strong>`) | Dölj kortet tills det finns data |
| `app.js:4294` | "Inga alternativ hittades som passar budget, butik och dina filter just nu." | "Inget alternativ passar dina val just nu. Prova en annan avsikt ovan." |

Genomgående: tankstreck (–) i stället för bindestreck i löpande text, och aldrig gemen mitt i en mening som börjar med versal ("Pris hämtas…", `app.js:2078`, `2199`, `3285`).

---

# VÅG H — Retention

*Det finns ingen retention-mekanik i appen idag. Noll. Ingen `push`-lyssnare i `sw.js`, `Notification` förekommer aldrig i `app.js`, och notisinställningarna i `index.html:457` styr bara en in-app-toast som syns om appen råkar vara öppen.*

### H1 · Söndagsnotisen `Z-FRONT-CORE` + `Z-GROCERY` · **störst effekt av allt i dokumentet**
Push i `sw.js` + `notificationclick` + backend-schema. Söndag 17:00: *"Dags att planera veckan. 4 middagar för 2 personer — vi har redan ett förslag klart."* Ett tryck → färdig vecka. `NOTIFY_LABELS.week` (`app.js:3964`) finns redan som begrepp.

Det här är den enda naturliga rytmen produkten har, och den är helt outnyttjad.

### H2 · Sparkvittot efter handlingen `Z-FRONT-VIEW`
`shoppingComplete` (`index.html:248`) säger idag bara "Allt handlat! Redo att planera nästa veckas meny?". Där ska stå vad veckan faktiskt kostade mot dyraste jämförbara butik, plus en löpande summa: *"Ni har sparat 612 kr sedan i september."* Datan finns i `state.savingsLog` och `state.dbComparison`.

Det är den enda siffran som gör en budgetapp värd att komma tillbaka till — och just nu är den gömd bakom ett kort som ofta visar "–".

### H3 · Veckohistorik `Z-FRONT-VIEW`
`state.weekHistory` sparar tolv veckor med totaler (`app.js:149`) och visas ingenstans utom som "Återställ förra veckan". "Så här har ni ätit i höst" är gratis innehåll som redan ligger i datan.

### H4 · Delbar sparbild `Z-FRONT-VIEW` · **högst avkastning av tillväxtloopar**
Rendera "Uppskattat sparat denna månad" som en 1080×1080-bild i canvas — *"Jag sparade 742 kr på maten i augusti · matjakt.store"* — med en Dela-knapp bredvid siffran. Det är den enda delning där avsändaren ser bra ut, vilket är hela skillnaden mellan en loop som snurrar och en som inte gör det.

### H5 · Hänvisning kopplad till Premium `Z-BILLING`
Premium-koder finns redan. Ge varje konto en personlig kod: den som bjuder in får en månad Premium när den inbjudna byggt sin **första vecka**, den inbjudna får en månad direkt. Villkora på `vecka_skapad`, inte på registrering, så ni inte betalar för tomma konton.

**Bygg detta ovanpå H6 (kodhantering):** dagens `MATJAKT_PREMIUM_CODE` är en enda evig sträng utan förbrukning, utgång eller räknare (`accounts/store.py:353-363`). Läggs den på Flashback blir varje konto som löser in den permanent Premium — och att byta env-variabeln återkallar **inte** redan inlösta konton. Inför `premium_codes(code_hash, label, max_uses, uses, expires_at)` och `premium_until` i stället för evig boolean.

---

# VÅG I — Marknadsföring

*Materialet finns redan byggt och obrukat. Det här är ett återkopplingsjobb, inte ett byggjobb.*

### I1 · Landningssidan tillbaka `Z-SITE` · **KRITISK**
`frontend/index.html` är **52 rader** och refererar varken `styles.css` eller `site-video.js` (verifierat: noll träffar). Live på matjakt.store finns alltså en rubrik, en mening och en knapp. Inget pris, ingen skärmbild, ingen film, inget socialt bevis.

Obrukat i repot ligger: en komplett landningssidas CSS (`frontend/styles.css`, hjälte, funktionsrutor, steg, prisplaner, FAQ, footer), en filmad presentation med sju klipp och lat inladdning (`site-video.js` + `frontend/site/video/*.mp4`, ~3,5 MB, hanterar redan Data Saver och `prefers-reduced-motion`), en OG-bild och en färdig Instagram-reel (12 MB). Spåret i git är tydligt: `e70a9a8` gjorde sajten till en låsskärm, `9c1898d` öppnade appen igen — men landningssidan återställdes aldrig.

**Ny struktur, sektion för sektion:**

1. **Topprad** — ordmärke, "Så funkar det / Pris / Vanliga frågor", knapp "Öppna appen".
2. **Hjälte med film.** Ögonbryn: RIKTIGA BUTIKSPRISER, INTE UPPSKATTNINGAR. H1: **"Säg vad maten får kosta. Matjakt planerar veckan och visar var den blir billigast."** Ingress: *Sju middagar, en inköpslista och ett verkligt pris hos Willys, Hemköp och City Gross. Du bestämmer budgeten – vi räknar.* Knappar: **Kom igång gratis** · Se hur det fungerar. Not: *Gratis att använda. Inget kort. Inget konto krävs för att prova.*
3. **Beviset direkt under vecket.** H2: **"Priserna kommer från butikerna, inte från en gissning."** *Matjakt läser in Willys, Hemköps och City Gross priser varje natt. Kan vi inte prissätta en vara säger appen det rakt ut – hellre inget pris än ett fel pris. Och en butik som inte går att jämföra rättvist märks aldrig som billigast.*
4. **Så fungerar det** (tre steg): *Sätt ramarna* — hur många ni är, vad veckan får kosta, var ni handlar. *Få veckan* — middagar som håller budgeten, byt de du inte gillar. *Handla* — listan är sorterad som hyllorna och räknar bort det du har hemma.
5. **Filmen** (sju scener; rubrikerna i `frontend/site/video/clips.json` är bra som de är). Avslutningsrad: *Matjakt gör jobbet åt dig.*
6. **Skillnaden mot att handla som vanligt** (saknas helt idag): *Du planerar inte i butiken* (impulsköpen är det dyra) · *Du vet vad veckan kostar innan du går* · *Kampanjerna hamnar i maten du faktiskt lagar* (ett fynd du inte använder är inget fynd).
7. **Pris.** Gratis för alltid vs Premium 59 kr/mån eller 399 kr/år. Knapp: **Börja gratis, uppgradera sen**.
8. **Vanliga frågor** (ger FAQPage-schema): Var kommer priserna ifrån? · Behöver jag konto? · Vad kostar det? · Vilka butiker stöds? · Kan familjen dela samma vecka? · Hur raderar jag mitt konto?
9. **Avslutning:** H2 *"Nästa vecka kan vara planerad om fem minuter."*
10. **Footer** — juridiklänkar, support@matjakt.store, *"Produktinformation delvis från Dabas. Klipp från Pexels."*

### I2 · SEO och delning `Z-SITE` · **HÖG**
- `<title>Matjakt</title>` (`index.html:8`) och `<h1>Matjakt.</h1>` (`:38`) bär inget budskap. Title: *Matjakt – veckans middagar efter din budget, till riktiga butikspriser*. H1 = löftet; ordmärket flyttas till toppraden.
- **Sitemapen är tom** — `<urlset>` utan en enda URL, medan `robots.txt:3` pekar sökmotorerna dit (verifierat). Lista `/`, `/integritetspolicy.html`, `/anvandarvillkor.html` med `lastmod`.
- **Ingen OG-bild i markup.** `og-image.svg` finns men refereras inte, och SVG fungerar inte som `og:image`. Rendera till 1200×630 PNG; lägg till `og:title`, `og:description`, `og:image`, `twitter:card=summary_large_image`. Varje delad länk är idag en tom grå ruta.
- **Ingen strukturerad data.** JSON-LD `SoftwareApplication` med pris + `FAQPage`.
- **Ingen webbanalys.** `<meta name="matjakt-traffic" content="">` — sätt `plausible:matjakt.store`. Kakfritt, redan i CSP:n, ingen samtyckesbanner.
- **Tre varumärken i samma domän:** `index.html:12` (Manrope/Bricolage, grönt `#146c43`) mot `404.html:10-14` och `integritetspolicy.html:8` (DM Sans/Fraunces, orange) mot `make_instagram_video.py:52-53` (BRAND_ORANGE). Ett par och en accent, ändrat på alla fem ställena — enligt G1.
- **Support är en privat iCloud-adress** (`index.html:41`). `support@matjakt.store`, vidarebefordrad.

### I3 · Juridiska platshållare live `Z-SITE` · **HÖG**
`integritetspolicy.html:31` innehåller `[FÖRETAGSNAMN / DITT NAMN]` och `[ORGANISATIONSNUMMER]`. Personuppgiftsansvarig är inte namngiven på en sida som säljer en betaltjänst. **ADAMS BESLUT** — men det blockerar en trovärdig Premium-försäljning.

### I4 · Mailen `Z-MAIL` · **HÖG**
`MATJAKT_MAILINGS_ENABLED=0` i `render.yaml:40` — noll marknadsmail går ut. Maskinen är byggd och säkrad (samtycke, HMAC-avregistrering, List-Unsubscribe, en gång per konto) och avstängd.

Mallarna i sig är torra nyhetsbrev: ingen preheader, CTA som textlänk i brödtexten (`mailings.py:189-199`, `232`, `297`), och ämnesrader som beskriver tidsförlopp i stället för värde ("En vecka med Matjakt", `:219`).

**Gör:** dold preheader överst i `_layout`, riktig table-baserad knapp (44 px hög), avsändarnamn **Matjakt** / `hej@matjakt.store`, `Reply-To: support@matjakt.store`. Full copy för alla tio mallarna ligger i **Bilaga 1**.

Konkret kodändring utöver copy: ämnesraden på `mailings.py:245` ska innehålla det bästa fyndets namn och pris, inte kedjornas namn. Ett pris i ämnesraden öppnas; en uppräkning av butiker gör det inte.

### I5 · App Store och Play `Z-SITE`
- **Inga skärmbilder finns** — `store/appstore/metadata/` innehåller bara textfiler. Skärmbilder är det enskilt mest konverterande i butiken. Sex bilder: veckokortet med budgetmätaren, inköpslistan, butiksjämförelsen, ett recept, skafferiet, "Du sparar"-kortet.
- **Titeln slösar 23 tecken** — `name.txt` innehåller bara "Matjakt". Titeln är den tyngsta ASO-signalen. → `Matjakt: matbudget & veckomeny` (30 tecken). Undertitel: `Riktiga matpriser, din budget`.
- **Nyckelorden saknar kedjenamn** — inga "willys", "hemköp", "city gross", "matkasse", "handla", "matkonto". Ta bort ord som redan står i titel/undertitel (Apple indexerar dem ändå).
- **Ingen `store/play/`-katalog** trots att `android/` är byggt. Spegla texterna som `short_description` (80 tecken) och `full_description` (4000).

### I6 · Kampanjtorget som publik sida `Z-SITE`
Veckans fynd finns redan strukturerade i mailet. Publicera samma data på `matjakt.store/fynd/vecka-{n}`. Det är den enda sidan på hela domänen som får nytt innehåll varje vecka, och den enda realistiska vägen till organisk sökning på "veckans erbjudanden Willys". Mailet blir då en utskickskanal för en sida som ändå indexeras.

### I7 · Mätning som når fram till kronor `Z-SITE`
`analytics/store.py:32` saknar `konto_skapat`, `premium_kop`, `inbjudan_skickad`, `inbjudan_accepterad`, `mail_klick` — och hela betalsteget: `checkout_startad`, `checkout_avbruten`, `betalning_genomford`, `plan_vald_manad/ar`, `uppsagning_paborjad`.

`funnel()` (`analytics/store.py:169-250`) är genuint bra — kohorter, betalande skilt från kompenserad, mognadsflagga. Men den räknar **konton, aldrig kronor**. Ingen MRR, ingen ARPU, ingen churn per kohort.

**De fem talen du ska se varje vecka:** nya konton · andel som skapar en vecka inom 48 h · andel tillbaka efter sju dagar · aktiva hushåll med fler än en medlem · betalande konton och MRR. Fyra av fem går att räkna idag om händelserna läggs till. Det är några rader kod och skillnaden mellan att gissa och att veta.

---

# VÅG J — Paketering och pris

### J1 · Tretton av sjutton premiumfunktioner är låsta med CSS `Z-BILLING` · **HÖG**
`accounts/features.py:50-77` mot kontrollpunkterna i `api_server.py:3214, 3238, 3288, 3389`. Server-side skyddas endast `all_store_prices`, `all_store_baskets`, `live_prices` och kampanjer. Oskyddade: alla sju veckotyper, `seven_dinners`, `advanced_nutrition`, `meal_prep`, `full_pantry`, `favorites`.

Verifierat: **`/api/v1/recipes/by-pantry` (`api_server.py:2378`) har ingen entitlement-kontroll alls** — hela "Laga med det jag har", som säljs som `full_pantry`. Och i devtools räcker `entitlements.isPremium = true` för att låsa upp familjevecka, budgetvecka, sju middagar och näringsfilter permanent i sessionen.

Kommentaren i koden — *"a paywall that only hides pixels is not a paywall"* — gäller alltså två av vägarna.

### J2 · Premiumlistan lovar saker som redan är gratis `Z-FRONT-VIEW` · **HÖG**
`index.html:495-496` säljer "Aktuella erbjudanden och kampanjer" och "Laga med det du redan har hemma". Båda är helt ogatade: `renderCampaignSection()` körs för alla, `cookFromPantryBtn` har ingen `can()`-kontroll. Samma lista säger "Obegränsade byten" (fritt = 3) och "Upp till 7 middagar" (fritt = 4) utan att säga vad fritt är.

Varje användare som testar och upptäcker att "Premium-funktionen" redan fungerar lär sig att listan ljuger.

**Gör:** en jämförelsetabell Gratis vs Premium med bara sanna rader.

### J3 · Ny paketering `Z-BILLING` — **min rekommendation**
Diagnosen: ni har paywallat fel saker. Bakom betalväggen ligger *prisjämförelse mellan butiker* — men Free får redan riktigt totalpris för billigaste butiken **och** prisspridningen. Free får alltså 90 % av värdet. Samtidigt är **hushållsdelning gratis för tolv personer med notiser** — den enda funktionen i produkten med äkta retention och nätverkseffekt.

Principen: sälj det som är dyrt för er och återkommande värdefullt för kunden — färsk prisdata och delning — inte det som är gratis att generera lokalt (och omöjligt att skydda).

| | Gratis | Premium |
|---|---|---|
| Veckoplanering | **Alla veckotyper, 1–5 middagar** | 6–7 middagar |
| Riktigt pris | Billigaste butiken, full lista | **Alla butiker + exakt jämförelse** |
| Live-priser per vara | – | ✓ |
| Kampanjbevakning | – | ✓ |
| Skafferi | Basskafferi + "Laga med det jag har" | Utgångsdatum, automatisk avdragning |
| Näringsfilter | Grundläggande | kcal/protein-mål, meal prep |
| **Hushåll** | **2 personer** | **Upp till 12 + notiser** |
| Sparhistorik | Senaste veckan | **Full historik + månadsrapport** |

**Flytta ner till gratis:** alla veckotyper, `full_pantry`, `advanced_nutrition`, `meal_prep`. De går inte att skydda och de är precis det som gör en ny användare beroende de första två veckorna. `FREE_MAX_DINNERS` 4 → **5** (en arbetsvecka är den naturliga enheten; fyra känns som en stympning).

**Flytta upp till premium:** hushåll bortom två personer, och sparhistorik/månadsrapport. Hushållet är den överlägset starkaste betalningsanledningen — en familj som lagt in skafferi och delar lista byter inte app — och det är omöjligt att kringgå från klienten eftersom varje rad går via servern.

**Ny premiumfunktion att bygga:** *"Du sparade 1 340 kr i september."* Den enda funktionen som **bevisar** att prenumerationen betalar sig. 59 kr mot 300 kr sparat är ett trivialt köpbeslut.

**Pris:** behåll 59/399. Men lägg till **sju dagars gratis Premium som triggas efter första skapade veckan**, inte vid registrering. Ni tog medvetet bort trial — det var rätt beslut på fel trial. En trial vid registrering testar nyfikenhet; en trial efter aktivering testar produkten på någon som redan har en vecka planerad och just sett att det skiljer 214 kr mellan butikerna. `trial_ends_at`/`trial_used` finns kvar och läsvägen respekterar dem redan — det är en beviljandeväg som saknas, inte infrastruktur.

### J4 · Entitlement uppdateras bara vid boot och inloggning `Z-FRONT-CORE` · **MEDEL**
`app.js:954`, anropad från `5252` och `4747`. `onAppResumed` (`5188-5191`) hämtar hushåll och notiser men **inte** entitlements. En PWA som legat öppen i tre veckor fortsätter visa Premium efter en uppsägning. Omvänt ser en som just betalat i Stripes portal inte sin uppgradering förrän omladdning (checkout-flödet har poll, portal-flödet inte).

**Gör:** `fetchEntitlements()` i `onAppResumed()` och efter återkomst från portalen. `Cache-Control: no-store` på `/api/entitlements`.

### J5 · Dunning, återbetalning och e-post `Z-BILLING` · **MEDEL**
- **Ingen respit vid `past_due`** (`accounts/store.py:29-30, 182`). Ett nekat kort släcker Premium i samma sekund, trots att Stripe Smart Retries ofta återhämtar betalningen på dag 3 av 21. Ofrivillig churn på ett problem som löser sig självt. → låt `past_due` behålla Premium i sju dagar med banner.
- **Inget dunning-mejl.** `invoice.payment_failed` hanteras inte alls (`api_server.py:1959-1960`). Det är typiskt 20–30 % av all churn i en konsumentprenumeration, och den billigaste att rädda.
- **Ingen hantering av `charge.refunded` / `charge.dispute.created`.** Återbetalar ni i god ton men glömmer säga upp prenumerationen behåller kunden Premium ett år gratis.
- **E-post går inte att byta.** Det finns ingen `change-email`-route i hela `api_server.py`. Någon som registrerar sig med `adam@gmial.com` och betalar 399 kr kan varken få kvittot, återställa lösenordet eller nå portalen. Enda vägen ut är radera kontot — vilket säger upp prenumerationen och kastar hushållet.
- **Ingen verifierad e-post krävs före köp** (`api_server.py:2757-2783`).
- **Ingen påminnelse före årsförnyelsen.** I Sverige förväntas det, och det förebygger chargebacks.
- **Ingen avstämningsrutin.** Något som varje timme jämför Stripes aktiva prenumerationer mot `subscription_status` och larmar vid avvikelse. Det är säkerhetsnätet under B1. Tar en kvart att skriva.

---

# VÅG K — CI och leverans

### K1 · Lint och typkontroll `Z-CI`
`ci.yml:47-50` kör `node --check` + `compileall` — det är syntax, inte semantik. Inget `ruff`, `eslint`, `mypy` eller `pyproject.toml` finns i repot. `tests/app-imports.test.js` finns just för att fånga en klass av fel som en linter fångar gratis. **Billigaste kvalitetsvinsten i hela dokumentet.**

### K2 · Pinnade beroenden och sårbarhetsskanning `Z-CI` · **HÖG**
`backend/requirements.txt` innehåller exakt en rad: `playwright>=1.45`. Basimagen är pinnad till `playwright/python:v1.62.0-jammy` — så `pip install` kan dra en Playwright vars Chromium **inte finns i imagen**, och en ombyggnad utan kodändring ger "Executable doesn't exist" i produktion.

Ingen `npm audit`, ingen `pip-audit`, ingen Dependabot (`.github/` innehåller bara två workflow-filer). Sju Capacitor-paket ligger i `dependencies` fast de bara behövs för native-bygget.

**Gör:** `playwright==1.62.0` med kommentar att raden ändras tillsammans med Dockerfile-taggen; `pip-compile` till låsfil med `--generate-hashes`; `npm audit --audit-level=high` + `pip-audit` i `security`-jobbet; `.github/dependabot.yml` (npm + pip + actions, veckovis).

### K3 · Deploy-race mellan frontend och backend `Z-CI` · **HÖG**
`ci.yml:115` fyrar Render-hooken när CI blir grön; `deploy.yml:27` startar Pages-jobbet av samma händelse. Pages är live på ~3 min, Render på ~5 → **det finns ett fönster där ny frontend talar med gammal backend**, och klienten har inget API-versionskontrakt.

**Gör:** backend först, sen en hälsokontroll som pollar `GET /api/health` tills `commit` matchar `GITHUB_SHA` (fältet finns redan, `api_server.py:2076`), sen Pages.

### K4 · Staging och rökprovning `Z-CI`
E2E körs bara mot en process i CI, aldrig mot något som liknar Render. Efter deploy är kontrollen en människa som läser `/api/health`.

**Gör:** `matjakt-staging` i Render (samma blueprint, egen disk, Stripe-testnycklar), deploy dit vid varje merge, E2E mot staging, och ett `smoke`-jobb efter produktionsdeploy: health `ok`, `commit == SHA`, `platform.active`, 200 på `/api/recipes`, 401 på `/api/account/state`, 404 på admin. Annars automatisk rollback.

### K5 · Versionskontrollen kontrollerar likhet, inte färskhet `Z-CI`
`check_frontend_version.py:47` kräver att `sw.js`, `app.js?v=` och `styles.css?v=` är **lika**, inte att de **höjts** när frontend ändrats. En PR som rör `frontend/app/app.js` utan bump är grön, och Pages HTTP-cache serverar gammal `app.js` under samma URL — precis felet som `sw.js:1-7` beskriver.

**Gör:** CI-steg som kräver höjt versionsnummer när `frontend/app/**` ändrats.

### K6 · Testluckor `Z-CI`
- **Bara en av fem collectors är testad.** `test_ica_collector.py` är ensam; `collectors/{willys,hemkop,citygross,axfood}.py` har ingen egen svit. Scraping är det som faktiskt går sönder i drift. → kontraktstest per collector mot sparade fixturer.
- **Ingen täckningsmätning.** 1 243 tester låter mycket, men ingen vet vad de rör. `app.js` är 5 297 rader och testas bara indirekt. → `coverage` med `--fail-under` som rapporteras första månaden, blockerar sedan på delta.
- **Tre villkorliga skip i varje körning** (`test_grocery_api.py:238`, `test_api_server.py:2687`, `test_site_video.py:106`) och ingen som märker om de blir trettio. → `MATJAKT_STRICT=1` i CI.
- **Manuell bakdörr förbi hela grinden:** `deploy.yml:10` `workflow_dispatch` publicerar till matjakt.store med bara `npm test` — ingen hemlighetsskanning, ingen versionskontroll, ingen E2E, och `github.sha` kan vara vilken gren som helst. → ta bort, eller kräv `environment: production` med reviewer.
- **Migrationer är ad hoc.** `ALTER TABLE` i try/except på fyra ställen, ingen `PRAGMA user_version`, ingen nedåtväg. Med rollback till föregående Render-commit efter en migration finns ingen definierad väg tillbaka. → `user_version`-stämplade steg och ett test per lager mot en fixtur-DB av föregående version.
- **Dubbelarbete:** `deploy.yml:44` kör hela backendsviten en gång till på exakt samma SHA som CI redan godkänt (~2,5 min). Grinden är redan passerad.

### Så bör CI se ut

```
Vid PR och push till main — parallellt, ~3 min:
  lint      ruff check backend + eslint frontend tests scripts        30 s
  backend   pip install -r requirements.lock → compileall
            coverage run backend/tests/run.py --exclude "*journey*"
            coverage report --fail-under=<dagens nivå>                60 s
  frontend  npm ci → node --check → node --test                       40 s
  security  secret_scan + gitleaks --log-opts=--all
            npm audit --audit-level=high + pip-audit
            check_frontend_version --require-bump-if-frontend-changed
            git ls-files: inga *.db, .env, genererade artefakter      30 s
  e2e       Playwright mot källor OCH dist-bygget (matris)            3 min

Grind: allt grönt → merge tillåten (branch protection + merge queue)

Efter merge:
  1. deploy-staging  → vänta på /api/health commit == SHA
  2. e2e mot staging → konsumentresan + hushållsresan över riktig HTTP
  3. deploy-backend  → Render prod-hook med ref = SHA
  4. health-gate     → polla tills commit == SHA (max 8 min), annars stopp
  5. deploy-frontend → Pages (först nu — K3)
  6. smoke           → recipes 200, account 401, admin 404, prisaudit grön
  7. vid fel i 4–6   → rollback: Render "deploy previous", Pages föregående SHA

Nattligt: hela sviten + pip-audit/npm audit, så beroendedrift upptäcks utan push.
```

---

## Vad som INTE ska göras

- **Bygg inte om det som är rätt.** Ingen IDOR finns (hushålls-id kommer alltid ur sessionen, `routes.py:52-65`). Ingen SQL-injektion finns (varje f-string bygger bara kolumnnamn från interna allowlists). Ingen CSRF-yta finns (Bearer, inte cookies). XSS-ytan är i praktiken täckt av `escapeHtml` + `safeHttpUrl`. Alla tretton admin-vägar går genom `_admin_ok()`. `data_guard.py` är genuint bra. Stripe-webhooken verifierar signatur före parsning och är idempotent. Hushållets inbjudningsflöde har inga säkerhetsfynd alls — `token_urlsafe(24)`, hashad, engångs, 72 h, återkallningsbar.
- **Rör inte prismotorns fail-closed-principer.** "Hellre saknat pris än gissat" är produktens moat. Alla C-paket ska göra den *striktare*, aldrig lösare.
- **Ingen React/React Native-migrering.** Inte i den här omgången.
- **Ingen Postgres-migrering ännu.** D8 räcker till ~1 000 användare. Vid 10 000 är det ett eget beslut.

---

## Bilaga 1 — Mailen, färdig copy

Genomgående: avsändarnamn **Matjakt**, adress `hej@matjakt.store`, `Reply-To: support@matjakt.store`. Dold preheader först i `_layout`. CTA som knapp, inte länk.

### 1. Verifieringsmejlet (dag 0) — *ersätter `api_server.py:2558-2566`*
Transaktionellt, ingen avregistrering. Men det är ditt mest öppnade mejl någonsin och ska bära första löftet.

**Ämnesrad:** Ett klick kvar – sen bygger vi din första matvecka
**A/B:** Välkommen till Matjakt. Bekräfta din adress så sätter vi igång · Din matvecka väntar – verifiera adressen först
**Preheader:** Klart på tio sekunder. Sen väljer du budget och Matjakt gör resten.

> Hej!
>
> Roligt att du är här. Klicka på knappen nedan så är din adress verifierad och kontot ditt.
>
> Sen är det tre steg till en färdig matvecka:
>
> **1. Säg vad veckan får kosta.** Och hur många ni är hemma.
> **2. Matjakt bygger veckan.** Middagar som håller budgeten, prissatta mot butikernas verkliga priser – inte uppskattningar.
> **3. Ta med listan.** Den är sorterad som hyllorna och räknar bort det du redan har hemma.
>
> Om du inte skapade kontot kan du strunta i det här mejlet. Då händer ingenting.

**Knapp:** Verifiera min adress

### 2. Välkomst dag 3 — *ersätter `mailings.py:209-217`*
**Ämnesrad:** Tre saker i Matjakt som sänker matkontot mest
**A/B:** Har du hittat fynden på Hem-fliken än? · De tre knapparna som gör störst skillnad på matkontot
**Preheader:** Kampanjpriserna uppdateras varje natt. De som hamnar i din vecka sänker totalen direkt.

> Du har haft Matjakt i tre dagar. Här är de tre sakerna som gör mest för matkontot – tar en minut var.
>
> **Lägg ett fynd i veckan.** På Hem-fliken ligger veckans kampanjpriser, hämtade från butikerna själva varje natt. Trycker du in ett i veckan räknas totalen om direkt.
>
> **Byt ut en middag du inte gillar.** Torsdagen känns fel? Ett tryck, ny rätt, nytt pris. Du behöver inte acceptera veckan som den kom.
>
> **Fyll skafferiet.** Lägg in ris, pasta och konserver du redan har. Matjakt räknar bort dem från både listan och priset – det är ofta där de första hundralapparna ligger.
>
> Ta två minuter i kväll. Nästa vecka går det på trettio sekunder.

**Knapp:** Öppna Matjakt

### 3. Välkomst dag 7 — *ersätter `mailings.py:218-226`*
**Ämnesrad:** Söndagskvällen är den billigaste stunden i veckan
**A/B:** En vecka in – så här får du ut mest av Matjakt · Planera på söndag, handla billigare på måndag
**Preheader:** Nya kampanjer varje vecka. Den som planerar innan de tar slut handlar billigast.

> En vecka har gått. Här är det som brukar avgöra om Matjakt fastnar eller inte.
>
> **Planera på söndagen.** Kampanjerna är som färskast då, och de flesta hinner planera innan de tar slut. Femton minuter i soffan blir en vecka du inte behöver tänka på.
>
> **Låt skafferiet jobba.** Ju mer du lägger in, desto mindre står på listan. Matjakt föreslår gärna rätter av det du redan har.
>
> **Se var veckan blir billigast.** Gratisversionen visar den billigaste kvalificerade butiken för just din vecka. Premium visar alla butikers priser sida vid sida, så du kan välja den som ligger på din väg hem.
>
> Har du redan en vecka igång? Då är du längre än de flesta.

**Knapp:** Planera nästa vecka

### 4. Kampanjtorget (veckobrevet) — *ersätter ämnesrad och ingress i `mailings.py:245-247`; behåll hjältefyndet och tabellerna, de är bra*
**Ämnesrad:** Veckans bästa fynd: {vara} för {pris} hos {kedja}
**A/B:** Kampanjtorget vecka {v}: {n} fynd värda att planera runt · −{procent} % på {vara} den här veckan
**Preheader:** Hämtat direkt från butikerna i natt. Lägg fynden i veckan så räknas totalen om.

> Veckans kampanjpriser, hämtade från butikerna själva i natt. Procenten är mot ordinarie pris, och "lägsta vi sett" betyder att varan inte varit billigare någon dag de senaste trettio dagarna.
>
> *(hjältefyndet, sedan kedjornas listor som idag)*
>
> Trycker du in ett fynd i veckan byter Matjakt ut en rätt mot en som använder varan – och räknar om vad hela veckan kostar.

**Knapp:** Lägg fynden i min vecka

### 5. SAKNAS — Söndagens veckoplanmejl *(det viktigaste av alla)*
**Ämnesrad:** Din matvecka är förberedd – vill du ha den?
**A/B:** Söndag. Ska vi göra klart veckan? · {n} middagar, {belopp} kr, femton minuter
**Preheader:** Vi har lagt ett förslag åt dig. Byt det du inte gillar, resten är klart.

> Hej {namn},
>
> Ny vecka, nya priser. Matjakt har ett förslag klart: **{n} middagar för ungefär {belopp} kr**, byggt på din budget och den här veckans kampanjer.
>
> Gillar du inte torsdagen byter du den. Vill du ha billigare drar du ner budgeten. Sen är listan klar.
>
> Femton minuter nu, och du slipper frågan "vad ska vi äta" sex kvällar i rad.

**Knapp:** Se veckans förslag

### 6. SAKNAS — "Du sparade {belopp} kr" (månadsrapport)
**Ämnesrad:** Du sparade {belopp} kr på maten i {månad}
**A/B:** {månad} i siffror: {belopp} kr kvar på kontot · Din matmånad: {belopp} kr billigare än vanligt
**Preheader:** Så här ser det ut när någon annan räknar åt dig.

> Hej {namn},
>
> Här är din {månad} med Matjakt:
>
> **{belopp} kr** sparat mot ordinarie pris
> **{antal} middagar** planerade
> **{fynd} kampanjvaror** som hamnade i dina veckor
>
> Siffran är en uppskattning – den jämför vad du handlade mot vad samma varor kostat till ordinarie pris. Ingen exakt vetenskap, men den pekar åt rätt håll.
>
> Vet du någon som suckar över matpriserna? Skicka den här länken. Matjakt är gratis att använda.

**Knapp:** Se hela {månad} · **Sekundärt:** Dela min månad

### 7. SAKNAS — Vinn tillbaka (14–30 dagar utan inloggning)
**Ämnesrad:** Priserna har ändrats sedan du var här sist
**A/B:** Vi har hållit koll medan du varit borta · {namn}, din budget står kvar – veckan är ny
**Preheader:** {antal} nya kampanjer sedan ditt senaste besök. Din budget och ditt skafferi finns kvar.

> Hej {namn},
>
> Det var ett tag sedan. Under tiden har vi läst in butikernas priser varje natt – **{antal} nya kampanjer** sedan du var här sist.
>
> Allt ditt står kvar: budgeten, skafferiet, rätterna du gillade och de du hoppade över. Du behöver inte börja om, bara trycka en gång.
>
> Om Matjakt inte var något för dig är det helt okej – då kan du avsluta utskicken längst ner, så hör vi inte av oss mer.

**Knapp:** Bygg veckan igen

### 8. SAKNAS — Övergiven vecka (skapad vecka, listan aldrig använd)
**Ämnesrad:** Din vecka ligger klar – listan är inte avbockad
**A/B:** {n} middagar väntar på en handlingsrunda · Glömde du inköpslistan?
**Preheader:** Listan är sorterad som hyllorna och vet vad du redan har hemma.

> Hej,
>
> Du byggde en vecka med {n} middagar men listan är fortfarande obockad. Den ligger kvar och är fortfarande prissatt mot dagens priser – **{belopp} kr hos {butik}**.
>
> Öppna den i butiken så bockar du av medan du går. Den är sorterad efter hyllorna, inte efter recepten, så du slipper springa fram och tillbaka.
>
> Handlade du redan? Markera varorna som köpta så flyttas de till skafferiet och räknas bort nästa vecka.

**Knapp:** Öppna inköpslistan

### 9. SAKNAS — Premium-uppgradering (efter tredje skapade veckan)
**Ämnesrad:** Du använder Matjakt varje vecka. Det finns mer att hämta
**A/B:** Sju middagar, alla butiker, alla veckotyper – 59 kr · Vad Premium hade gjort med dina senaste tre veckor
**Preheader:** 59 kr i månaden. Ungefär vad ett paket kaffe kostar.

> Hej {namn},
>
> Du har byggt {antal} veckor med Matjakt. Det betyder att du använder gratisversionen så långt den räcker – så här ser resten ut:
>
> **Alla butikers priser sida vid sida.** Idag ser du den billigaste. Med Premium ser du hela jämförelsen och kan välja butiken som ligger på vägen hem.
> **Sju middagar i stället för fem.** Hela veckan planerad, inte bara vardagarna.
> **Live-priser och kampanjbevakning.** Priset per vara hämtas i samma stund du tittar.
> **Hela hushållet.** Upp till tolv personer på samma lista, med notis när någon bockar av.
> **Månadsrapporten.** Svart på vitt vad Matjakt sparat åt dig.
>
> **59 kr i månaden, eller 399 kr för ett år.** Avsluta när du vill, direkt i appen.

**Knapp:** Testa Premium

### 10. SAKNAS — Hushållsinbjudan som inte accepterats
**Ämnesrad:** {namn} väntar fortfarande på dig i Matjakt
**A/B:** Din inbjudan till {hushåll} ligger kvar · Två personer, en inköpslista
**Preheader:** Samma lista i två telefoner. Den som handlar bockar av, den andra ser det direkt.

> Hej,
>
> {namn} bjöd in dig till **{hushåll}** i Matjakt men du har inte gått med än.
>
> När ni delar hushåll delar ni samma vecka och samma inköpslista. Den som står i butiken bockar av, den andra ser det hända. Ingen köper mjölk två gånger.
>
> Länken gäller fortfarande.

**Knapp:** Gå med i {hushåll}

### 11. SAKNAS — Dunning (betalningen gick inte igenom)
**Ämnesrad:** Betalningen gick inte igenom – Premium är kvar i sju dagar
**Preheader:** Uppdatera kortet så fortsätter allt som vanligt. Vi försöker igen automatiskt.

> Hej {namn},
>
> Din bank nekade den senaste dragningen på {belopp} kr. Det är oftast ett kort som gått ut, inget mer.
>
> **Premium ligger kvar till {datum}** medan vi försöker igen. Uppdaterar du kortet innan dess märker du ingenting.

**Knapp:** Uppdatera betalsättet

---

## Bilaga 2 — Designunderlag

Riktningen är vald: **D — "Middagskortet"**. Två filer följer med:

- **`DESIGNSYSTEM-D.md`** — 1 384 rader. Färgtokens för ljust och mörkt läge med varje kontrastpar uträknat, hela typografiska skalan, spacing och linjer, komponentspecar med mått och tillstånd (och minsta träffyta 44×44 genomgående), de tre prisreglerna med CSS, rörelse, textstilregler, ett aliasskikt som gör bytet av `styles.css` stegvis, en **rivningslista med 58 poster** och en införandeordning.
- **`matjakt-design-D.html`** — åtta skärmar: Ikväll, Veckan, Handla, Receptet, Sparat, Onboarding (med söndagsnotisen), Inställningar och Premium. Byggd på appens egna receptfoton.

**Rivningslistan innehåller mer än de fynd som redan står i det här dokumentet.** Utöver kontrastfelet på rad 96 och den omkastade ordningen på rad 451 hittade granskningen: `styles.css` saknar `:focus-visible` helt medan `:focus{outline:0}` står på rad 15, 64 och 513 — tangentbordsnavigering är alltså osynlig i hela appen; ytterligare 25 träffytor under 44 px utöver de nio som redan var kända; ett emoji-trafikljus på rad 183–187 där saknat pris visas i rött; `opacity:.55` som ger 2,13:1; och ett tankstreck satt i ramfärg på rad 814, 1,22:1.

**De tre prisreglerna** — kodade i form, inte bara färg, så de överlever gråskala och färgblindhet:

1. **Kontrollerat pris:** naken siffra. Det som inte är utsmyckat är det du kan lita på.
2. **Uppskattat pris:** "ca" i kapitäler plus streckad understrykning.
3. **Pris saknas:** öppen ram med tankstreck. **Aldrig rött** — ett saknat pris är ingen varning, det är ett tomt fack. Rött skulle lära användaren att systemets ärlighet är ett fel.

En teckenförklaring med de tre formerna ligger i foten på Handla, så de går att läsa utan att ha memorerat systemet.

Regeln att ett schablonpris aldrig får kröna sig "Billigast" är kvar från `cheapestBranch()`, nu visuellt uttryckt.

## Bilaga 3 — Fyndens ursprung

Nio parallella granskningsagenter läste appen ur nio vinklar (backend-säkerhet, prislogik, drift, frontend-kod, UX, marknadsföring, test/CI, affärslogik, design). Femton av de mest bärande fynden verifierades därefter mot koden — regexparsern kördes, receptbanken räknades, kontrastvärdena beräknades, radnumren kontrollerades.

**Femton av femton stämde. Tre var värre än beskrivet:**

- **Vitlöken:** granskningen sa "33× 2 st, 25× 3 st". Faktiskt: **80 recept** har vitlök i styck.
- **Auditens falsklarm:** granskningen misstänkte delsträngsmatchning. Faktiskt: **75 av 114** flaggor är samma falsklarm ("Penne Rigate Pasta").
- **Landningssidan:** granskningen sa "i praktiken bara en rubrik". Faktiskt: **52 rader totalt, noll referenser** till den färdiga CSS:en och filmen.

Inget fynd i det här dokumentet är gissat.
