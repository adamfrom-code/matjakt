# Staging och rökprovning

Hela kodsidan av K4 är byggd och mergad. Det som återstår är fyra saker som
bara du kan göra, Adam, eftersom de kräver ditt Render-konto och repots
hemligheter. **Tills de är gjorda ändras ingenting i hur produktionen
deployas** — stagingjobbet skriver en notis i loggen, blir grönt, och
kedjan fortsätter precis som i dag.

---

## Varför

E2E kördes bara mot en process i CI, aldrig mot något som liknar Render.
Efter en deploy var kontrollen en människa som öppnade `/api/health` i en
flik. Det fångar "servern svarar inte" och ungefär inget annat.

Det som *inte* går att se i en testsvit är exakt det staging finns för: en
image som inte startar, en migration som stannar på en disk med data, en
miljövariabel som saknas, ett beroende som inte finns i imagen. Samma bygge
går nu upp i staging först, rökprovas där, och först när det provet är grönt
fyras produktionens hook.

---

## De fyra stegen

### 1. Skapa tjänsten

`render.yaml` innehåller redan hela definitionen — samma Dockerfile, samma
kontext, egen disk (`matjakt-staging-data`), `autoDeploy: false`,
`healthCheckPath: /api/health`.

I Render: **Blueprints → matjakt → Sync**. Tjänsten `matjakt-staging` skapas
med allt ovan. Kontrollera efteråt att **Auto-Deploy är Off** i tjänstens
inställningar, precis som på produktionen; blueprinten säger det, men
dashboardens egen inställning är den som gäller i tveksamma fall.

### 2. Sätt hemligheterna på stagingtjänsten

Alla `sync: false`-variabler måste fyllas i Renders dashboard. De ska
**inte** vara samma värden som produktionens:

| Variabel | Värde i staging |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_…` — **aldrig** en live-nyckel |
| `STRIPE_WEBHOOK_SECRET` | testlägets webhook-secret |
| `STRIPE_PRICE_MONTHLY` / `_YEARLY` | pris-id:n ur Stripes testläge |
| `MATJAKT_ADMIN_TOKEN` | en **egen** token, inte produktionens |
| `MATJAKT_BACKUP_TOKEN` | en egen token, eller lämna tom (då finns vägen inte) |
| `MATJAKT_BACKUP_PUBLIC_KEY` | kan lämnas tom i staging |
| `PRIMAT_API_KEY` | lämna **tom** — se nedan |
| `MATJAKT_ADMIN_EMAIL`, `SMTP_*` | lämna tomma; utskick är avstängda |

Samma admin-token i två miljöer betyder att den som får tag i stagings token
är inne i produktion också. Det är hela skälet till att de ska skilja sig.

`MATJAKT_GROCERY_SCHEDULE_ENABLED=0` och `MATJAKT_MAX_SCRAPES=0` står redan i
blueprinten. Det är inte en detalj: schemaläggaren hade annars bränt Primats
**dygnskvot** en gång till varje natt — samma kvot som produktionen delar. En
staging som kostar produktionen dess prisdata är värre än ingen staging.

### 3. Lägg in hemligheterna i GitHub

**Settings → Secrets and variables → Actions → New repository secret**

| Hemlighet | Var den kommer ifrån |
|---|---|
| `RENDER_STAGING_DEPLOY_HOOK` | Renders dashboard → `matjakt-staging` → Settings → Deploy Hook |
| `RENDER_API_KEY` | Render → Account Settings → API Keys |
| `RENDER_SERVICE_ID` | id:t i produktionstjänstens URL, `srv-…` — **produktionens**, inte stagings |

De två sista är för den automatiska återställningen. Utan dem blir
`rollback`-jobbet rött med en instruktion i stället för att tiga — "kunde
inte rulla tillbaka" ska aldrig se ut som "rullade tillbaka".

Blir stagings URL en annan än `https://matjakt-staging.onrender.com`, sätt
också repo-**variablerna** `MATJAKT_STAGING_HEALTH_URL` och
`MATJAKT_STAGING_API_URL` (Variables-fliken, inte Secrets — de är inte
hemliga).

### 4. Se en körning gå hela vägen

Nästa merge till main ska visa den här kedjan i Actions:

```
backend · frontend · security · e2e          (parallellt)
        ↓
deploy-staging      Render-hook mot matjakt-staging
        ↓
smoke-staging       väntar tills staging kör committen, kör sedan åtta prov
        ↓
deploy-backend      Render-hook mot produktion
        ↓
health-gate         pollar tills produktionen kör committen (max 8 min)
        ↓
smoke-prod          samma åtta prov mot produktionen
        ↓
deploy.yml          Pages — startar först när HELA CI-körningen är klar
```

Blir `smoke-staging` rött fyras produktionens hook aldrig, CI blir röd på
main, och eftersom `deploy.yml` kräver en grön CI-körning publiceras ingen
frontend heller. **Ett trasigt bygge stannar i staging.**

---

## De åtta proven

`backend/scripts/smoke.py` kör mot vilken miljö som helst:

    python backend/scripts/smoke.py --url https://matjakt.onrender.com/api \
        --commit <sha> --stripe-lage live

| Prov | Vad det fångar |
|---|---|
| `health` svarar 200 och `ok` | processen lever |
| `commit` == deployad SHA | provet gick mot den NYA processen, inte den gamla som överlevde |
| `platform.active` | prisplattformen har referenspriser och butiker — annars servas tomma veckor |
| `pricingAudit` inte röd | prisauditens gate |
| `/api/recipes` → 200 | receptbanken byggdes vid start (har uteblivit på tom disk förut) |
| `/api/account/state` utan token → 401 | någons sparade vecka ligger inte öppen |
| adminvägen utan token → 404 | adminytan syns inte ens |
| `stripe.mode` == miljöns läge | staging med `sk_live_` debiterar riktiga kort; produktion med `sk_test_` tar inte emot en enda betalning och säger inget om det |

Stripe-provet faller bara på ett **missmatch**, aldrig på att Stripe saknas
helt. Skillnaden är avsiktlig: ett rött rökprov mot produktion utlöser en
automatisk återställning, och att rulla tillbaka en release för att en nyckel
aldrig sattes hade varit värre än felet.

`/api/account/state` och adminvägen är säkerhetsgränser, inte hälsa. De står i rökprovet därför att
det är **efter en deploy** de kan ha flyttat sig, och därför att provet är det
sista som körs innan frontenden släpps på.

---

## Det som fortfarande inte går, och varför

**Browser-E2E mot staging** (Playwright-resorna över riktig HTTP) kräver en
sak som inte finns: resorna körs mot `backend/tests/e2e/fixture.py`, som
skriver syntetisk prisdata **direkt i en lokal `GroceryStore`** — tre butiker
i Gävle och en produkt per ingrediensnamn, med kedjespecifika priser så att en
"Billigast" går att kröna. Mot en fjärrbackend finns ingen sådan väg in.

För att resorna ska kunna köras mot staging behövs ett av två:

1. **En seedningsväg på staging** — en admin-skyddad endpoint som laddar
   e2e-fixturen i stagings egen databas, tillgänglig bara när miljön är
   staging. Det är backend-zon (`Z-GROCERY`/`api_server.py`), inte `Z-CI`.
2. **Att resorna accepterar en fjärrbas-URL** och kör mot stagings *verkliga*
   data. Det gör dem beroende av vad nattens import råkade hämta, och en resa
   som ibland hittar tre butikskort och ibland ett är värre än ingen resa —
   den lär folk att ignorera rött.

Rökprovets åtta punkter är därför det som körs mot staging i dag. De svarar på
"kom bygget upp och fungerar gränserna", vilket är precis den frågan en
testsvit inte kan svara på. Konsumentresan svarar på en annan fråga, och den
frågan ställs redan av `e2e`-jobbet mot källor **och** mot dist-bygget.
