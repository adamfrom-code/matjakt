# Grocery Price Backend

Matjakts egen produkt-/prisdatabas. Frontend pratar **aldrig** direkt med
butikernas API:er — bara med Matjakts egen backend.

```
BUTIKSKÄLLOR → COLLECTORS/PROVIDERS → NORMALISERING → MATJAKT DATABASE → MATJAKT API → FRONTEND
```

## Struktur

| Fil | Ansvar |
|---|---|
| `models.py` | Normaliserade datatyper (`RawProduct`, `Product`, `Store`, `CurrentPrice`, `PriceHistoryEntry`, `CollectorRun`) |
| `base.py` | `GroceryProvider` — interfacet varje kedja implementerar |
| `store.py` | `GroceryStore` — SQLite-lagret (`backend/data/grocery.db`, gitignorerad) |
| `providers/` | En fil per kedja. All kedjespecifik kod bor här och ingen annanstans. |
| `collectors/` | CLI-skript som kör en import och skriver rapport |

## Vägen ut till appen

```
BUTIKSKÄLLOR → PROVIDERS → grocery.db → pricing.py → api.py → /api/pricing/* → matjakt.store/app/
```

| Endpoint | Ger |
|---|---|
| `POST /api/pricing/week` | Veckans lista prissatt mot varje kedja, plus en jämförelse som får förbli oavgjord |
| `POST /api/pricing/list` | En kedjas butiksspecifika inköpslista med riktiga produkter |
| `GET /api/grocery/status` | Vad databasen faktiskt innehåller, plus providerstatus |
| `POST /api/admin/grocery-import` | Startar en import (admin-token, bakgrundstråd) |
| `GET /api/admin/grocery-import` | Importförlopp, schema och providerstatus |

Båda `pricing`-endpointsen svarar i **samma form**, så ingen vy behöver
härleda ett tal själv:

```json
{ "store": {...}, "totalCheckoutCost": 276.0, "coveragePercent": 90,
  "realPriceItems": 18, "estimatedItems": 6, "missingItems": 2,
  "missingItemNames": ["Curry & grönsaker", "Kycklinglårfilé"],
  "savings": null, "updatedAt": 1756..., "comparable": true, "items": [...] }
```

`items[]` innehåller **både** prissatta och saknade varor. Med separata
arrayer tvingades varje vy att slå ihop dem själv, och en vy som glömde det
tappade tyst de oprissatta varorna ur inköpslistan.

Varje rad bär `priceStatus`:

| | Betydelse |
|---|---|
| 🟢 `current` | Riktigt pris på en riktig produkt |
| 🟡 `estimated` | Priset är riktigt, men PAKETANTALET fick gissas (receptets enhet gick inte att räkna om till förpackningens) |
| ⚪ `missing` | Ingen produkt kunde matchas. Raden bär inget pris alls |

### "Billigast" får bara visas när jämförelsen bär

`compare_chains()` utser en billigaste kedja bara när underlaget håller.
Fyra saker spärrar var för sig, och var och en har producerat ett felaktigt
påstående i den här appen förut:

1. Färre än två jämförbara kedjor.
2. En kedja täcker under 60% av listan — dess total är låg för att varor
   SAKNAS, inte för att butiken är billig. Det är det värsta felläget,
   eftersom det får den sämst täckta kedjan att se bäst ut.
3. Alla totaler identiska ("Coop 351 / Willys 351 / ICA 351, en märkt
   billigast").
4. Data för gammal för att ställas mot färsk.

En kedja med noll riktiga träffar totalar 0 kr och spärras av kravet på minst
en träff. Totalerna visas ändå — de är riktiga — men utan badge och med ett
skäl. **Frontend härleder inte om detta**: när billigaste raden kommer från
databasen är serverns dom den enda auktoriteten.

## Nattjobb (Europe/Stockholm)

| Kedja | Tid | Varför |
|---|---|---|
| Willys | 02:00 | verifierad återkommande import |
| Hemköp | 03:00 | verifierad återkommande import |
| City Gross | 04:00 | verifierad, men konservativt (3 s, delvis körning är normal) |
| ICA | — | AWS WAF vid upprepad hämtning. Uppdateras **manuellt** via adminpanelen |
| Coop | — | kräver Coops egen credential |
| Lidl | — | publicerar inga priser |

Tiderna är spridda: tre parallella kategoripromenader hade tredubblat
anropstakten mot tre sajter under samma minut. Att tidszonen är
Europe/Stockholm är poängen — ett "03:00" som i tysthet betyder UTC glider en
timme två gånger om året mot de hyllpriser det ska spegla.

Avstängt som standard. `MATJAKT_GROCERY_SCHEDULE_ENABLED=1` slår på,
`MATJAKT_GROCERY_SCHEDULE` sätter tider. Kedjor utanför tabellens tre kan
**inte** schemaläggas ens av en felskriven variabel.

**En misslyckad körning raderar aldrig något.** Importen gör bara upsert —
det finns ingen raderingsväg. En blockerad körning behåller det den hann
samla och skriver varför den stannade.

## Produktionspersistens

Render-disken monteras på `/app/backend/data`, vilket är exakt dit både
collectorns `DB_PATH` och api_serverns datakatalog löser ut i imagen.
Verifierat praktiskt mot en tom monterad katalog: schemat skapas automatiskt,
och produkt, kategori och pris finns kvar efter omstart.

`backend/data/` är gitignorerad, så **ingen databas följer med imagen** — en
deploy kommer upp med en tom disk och måste fyllas av nattjobbet eller av
`POST /api/admin/grocery-import`.

## Adminpanel

`/app/admin.html`. Per kedja: status, produkter, priser, GTIN-, bild- och
kategoritäckning, senaste **lyckade** import, senaste **försök**,
felmeddelande och nästa nattkörning. De två sista är olika frågor: en kedja
vars senaste försök blockerades kan fortfarande leverera bra data från en
lyckad körning två dagar tidigare.

Admin-token hålls bara i minnet i fliken — aldrig i localStorage. En
admin-nyckel som ligger kvar på disk i en webbläsare är en nyckel som läcker.

## Kategoridata (insamling per kategori)

Kedjorna samlas i första hand in genom att **gå igenom kategoriträdet**, inte
genom att söka på en handskriven ordlista. Det ger två saker på en gång: hela
sortimentet i stället för vad ordlistan råkar träffa, och en **verklig
kategori** på varje produkt.

Endpointarna är verifierade live 2026-08-31 genom att observera vad sajten
själv anropar — inte gissade. (Flera rimliga gissningar —
`/products/category/{code}`, `/category/{slug}`, `?categoryPath=` — svarar
404, 500 eller med en tom träfflista och är alltså inte den riktiga vägen.)

| Endpoint | Ger |
|---|---|
| `GET /axfood/rest/v1/leftMenu/categorytree` | Hela trädet, rekursivt (`id`, `category`, `title`, `url`, `valid`, `children`) |
| `GET /axfood/rest/v1/c/{slug}?page=0&size=30&sort=` | **Samma svarsform som `/search`** (`results[]` + `pagination{}`) plus `categoryInfo` |

Eftersom svarsformen är identisk med sökningens gäller varje befintlig
fältmappning oförändrat — bara URL:en och det faktum att vi nu *vet*
kategorin skiljer.

**Kategorin kommer från anropet, inte från produkten.** Verifierat: varje
produkt i ett kategorisvar har `googleAnalyticsCategory == ""` och svarets
`breadcrumbs` är `[]`. Det finns alltså inget kategorifält att läsa på
produkten. Vi vet kategorin för att vi frågade efter just den kategorin —
exakt och ärligt, inte härlett ur produktnamnet. Insamling via textsökning
lämnar därför `category = null` i stället för att gissa.

**Kategorikoder delas INTE mellan kedjorna** och får aldrig användas som
cross-chain-nyckel: "Färsk fågel" är `N010101` hos Willys och `N010403` hos
Hemköp. Bara den läsbara sökvägen är jämförbar.

Bara **lövkategorier** hämtas — en förälders lista är unionen av barnens, så
att gå båda nivåerna hade hämtat varje produkt två gånger. Kategorier med
`valid: false` hoppas över i stället för att efterfrågas.

```bash
python -m backend.services.grocery.collectors.willys --store 2132 --categories
python -m backend.services.grocery.collectors.hemkop --store 4256 --categories
# Delmängd, för test: --category mejeri --per-category 20
```

Storlek på träden (verifierat 2026-08-31): **Willys 452 lövkategorier,
Hemköp 428**.

### Enhetligt kategoriformat över alla kedjor

Alla providers skriver nu hela sökvägen, bredast först, separerad med `" > "`:

| Kedja | Källa | Exempel |
|---|---|---|
| Willys / Hemköp | kategoriträdets sökväg | `Mejeri, ost & ägg > Mjölk > Lättmjölk` |
| City Gross | `superCategory > category > bfCategory` | `Mejeri, ost & ägg > Mjölk & dryck > Mellanmjölk` |
| ICA | hela `categoryPath` | `Mejeri & Ost > Mjölk > Mellanmjölk > Mellanmjölk, laktos` |

Lövet ensamt räcker inte: matchningen behöver **avdelningen** för att kunna
avvisa fel hylla, och den bär bara förfäderna. "Mellanmjölk" säger inte
"mejeri" — det gör "Mejeri, ost & ägg".

### Avdelningsmatchning i pricing-motorn

`grocery/pricing.py` avvisar en produkt vars avdelning inte kan vara
ingrediensen. Ordningen är:

1. Produkten saknar kategori → **oavgjort**, namnreglerna avgör som förut
   (ICA har inget användbart träd, och äldre rader är textinsamlade).
2. Avdelningen är en som ingen matlagningsingrediens kommer från — djurmat,
   barnmat, godis/snacks, non-food → **avvisas för varje ingrediens**. Det är
   den enskilt bredaste precisionsvinsten: den fångar hela den klass av fel
   som namnreglerna tidigare fick bekämpa en i taget.
3. Ingrediensen har en tillåten avdelningslista → produktens avdelning måste
   ligga i den.

En ingrediens utan lista begränsas bara av regel 2. Lagret är alltså
**additivt**: det kan avvisa en felaktig match, aldrig hitta på en riktig.

## Nästa förbättring: butiksspecifika priser (EJ GJORD)

Willys och Hemköp är **verifierat nationella** — samma fråga med två olika
`storeId` ger byte-identiska svar. Deras priser gäller alltså i varje butik,
och den kedja användaren klickar på spelar ingen roll för priset.

**City Gross och ICA prissätter per butik.** Idag importeras City Gross från
Gävle (`3209`) och ICA från Maxi Gävle (`1003987`), så en användare i
Stockholm som öppnar City Gross Häggvik ser Gävlepriser. Frontend säger det
rakt ut (`pricingScope` i pricing-svaret ger varukorgen en tydlig rad om
det), men det är en varning, inte en lösning.

**Rätt modell är efterfrågestyrd, inte uttömmande.** Att importera alla
Sveriges butiker skulle multiplicera importvolymen mot kedjor som redan
stryper oss, för data ingen efterfrågat. I stället:

```
användarens postnummer
  → närmaste butiker (finns redan, /api/stores)
  → importera/cacha PRECIS de butikerna
  → prissätt mot den butik användaren faktiskt valt
```

Det som redan finns och bär modellen:

- `grocery_current_prices` är nycklad på `(product_id, store_id)`, så flera
  butikers priser för samma produkt ryms redan utan schemaändring.
- `GroceryStore.upsert_store` och providerarnas `get_stores()` löser vilken
  butik som helst.
- Collectorerna tar redan `--store`, och importern tar `store_id`.
- `pricing.price_list(..., store_id=...)` prissätter redan mot en specifik
  butik.

Det som saknas: en per-butik-TTL och en kö som importerar en butik första
gången någon frågar efter den, i stället för att alla butiker importeras i
förväg. **Blockerar ingenting annat** — nationellt prissatta kedjor är redan
korrekta, och de per-butik-prissatta är korrekta för den importerade butiken
och ärligt märkta för övriga.

## Produktmatchning (prioritetsordning)

1. **GTIN**
2. **EAN**
3. Kedjans eget stabila `external_product_id` (via `grocery_product_external_ids`)
4. `brand + normaliserat namn + storlek`, **exakt** match

Steg 4 är avsiktligt *inte* fuzzy. En felaktig sammanslagning (två olika
produkter blir en) är värre än en missad (samma produkt får två rader tills
ett GTIN dyker upp).

## Providerstatus

| Kedja | Status | Återkommande import | Produkter i db | Insamling |
|---|---|---|---|---|
| **Willys** | `working` (nationell prissättning) | ✅ **Ja** | **10 842** | kategoripromenad |
| **Hemköp** | `working` (nationell prissättning) | ✅ **Ja** | **2 982** | kategoripromenad |
| **City Gross** | `working_but_unreliable` | ✅ Ja (men se nedan) | ~100+ | sökord (54) |
| **ICA** | `working_but_rate_limited` | ❌ Nej — AWS WAF | 100 | sökord, manuellt |
| **Coop** | `blocked_requires_vendor_credential` | ❌ Nej — API kräver Coops egen nyckel | 0 | — |
| **Lidl** | `not_available_no_public_prices` | ❌ Nej — publicerar inga priser alls | 0 | — |

Siffrorna är från fullimporterna 2026-08-31. Willys: 452 lövkategorier,
10 872 sparade (10 077 nya, 795 uppdaterade), 100% med kategori, bild och
GTIN, 0 fel. Hemköp: 428 lövkategorier, 2 982 sparade, 100% med kategori,
bild och GTIN, 70 kampanjpriser, 26 medlemspriser, 0 fel.

### Gemensamt Axfood-lager

Willys och Hemköp kör samma Axfood-plattform. Det **verifierades** (inte antogs)
genom att jämföra fullständiga svar från båda värdarna: identiska toppnycklar
och identiska produktfält. All request-/parse-/normaliseringslogik ligger
därför en gång i `providers/axfood.py`; `willys.py` och `hemkop.py` är tunna
subklasser som bara sätter värd och metadata. Samma sak för collectorn
(`collectors/axfood.py`).

**Kampanj / medlemspris / multibuy hålls isär** — de tre är genuint olika och
skulle felrapportera pris om de slogs ihop:

| Signal | Betydelse | Fält |
|---|---|---|
| `campaignType == "LOYALTY"` | Bara medlemmar betalar detta | `member_price` |
| `qualifyingCount > 1` | Styckpris vid köp av N ("2 för 40 kr" → 20,00/st) | `multibuy_price` |
| annars | Rakt kampanjpris alla får | `campaign_price` |

En tidigare version använde `conditionLabelFormatted` för att hitta multibuy.
**Det var fel över kedjegränsen:** Hemköp lämnar det fältet tomt på riktiga
multibuys (t.ex. Bryggkaffe: ordinarie 66,20, `qualifyingCount` 2,
`rewardLabel` "129 kr", styckpris 64,50) medan Willys fyller i "2 för".
`qualifyingCount` sätts korrekt av båda och är därför det koden litar på.

### Cross-chain-matchning fungerar ⭐

Eftersom både Willys och Hemköp nycklar sina produktbilder på GTIN-14 kan
samma fysiska produkt matchas över kedjorna. Efter import av 100 produkter
per kedja: **300 externa produkt-ID mappade till 231 unika produkter — 69
matchade över kedjegränsen**, med riktiga prisskillnader:

| Produkt | GTIN | Willys | Hemköp |
|---|---|---|---|
| Ayran Turkisk Yoghurtdryck | 07350056796000 | 15,90 | 17,93 |
| Blåbär Filmjölk 3,5% | 07310861012504 | 23,50 | 26,80 |
| Cappuccino Iskaffe | 05710326016788 | 21,67 | 25,50 |
| Currysoppa Kokosmjölk | 05711953212802 | 24,90 | 27,89 |

ICA matchar inte in i detta, eftersom ICA inte exponerar något GTIN alls.

### Willys ⭐ (mest stabil hittills)

**Verifierad import (2026-08-30)** — Willys Gävle Gestrike, storeId `2132`.
Två fulla körningar i rad, ingen blockering:

| | Körning 1 | Körning 2 |
|---|---|---|
| Produkter hittade | 2054 | 2054 |
| Sparade (`--limit 100`) | 100 | 100 |
| Nya / uppdaterade | 100 / 0 | **0 / 100** |
| Med GTIN/EAN | 100 | 100 |
| Med bild | 100 | 100 |
| Med ordinarie pris | 100 | 100 |
| Med jämförpris | 100 | 100 |
| Med kampanjpris | 1 | 1 |
| Med multibuy | 1 | 1 |
| Fel | 0 | 0 |

```bash
python -m backend.services.grocery.collectors.willys --store 2132 --limit 100
```

**GTIN härleds från bild-URL:en** — Willys har inget `gtin`-fält, men bilderna
är nycklade på GTIN-14 (`.../07310865005168_C1L1_s01`). Provider sätter bara
`gtin` när GS1-checksiffran validerar (12/12 giltiga i stickprov); en kod som
inte validerar behandlas som "ingen GTIN" i stället för att gissas, eftersom
fel GTIN skulle slå ihop två olika produkter i tier 1-matchningen.

**Kampanj vs multibuy hålls isär.** `potentialPromotions[].conditionLabelFormatted`:
tom sträng = rakt kampanjpris (145 → 129 kr); `"2 för"` / `"3 för"` = multibuy
(styckpriset när man köper N). Att lagra multibuy som kampanjpris skulle
överdriva rabatten för den som köper en vara.

**Begränsning — priserna är NATIONELLA, inte per butik.** Verifierat: samma
sökning med `storeId=2132` och `storeId=2223` ger byte-identiska svar
(35593 B båda) med identiska priser. Endpointen accepterar men *ignorerar*
`storeId`. Det är konsekvent med att Willys är en centralstyrd lågpriskedja,
men ett Willys-pris får inte presenteras som verifierat för just den adressen.

### Hemköp

**Verifierad import (2026-08-30)** — Hemköp Uppsala Svava C, storeId `4256`.
Det finns ingen Hemköp-butik i Gävle; 4256 är närmaste onlinebutik (~95 km).
205 butiker totalt, 66 online.

| | Körning 1 | Körning 2 |
|---|---|---|
| Produkter hittade | 2217 | 2216 |
| Sparade (`--limit 100`) | 100 | 100 |
| Nya / uppdaterade | 100 / 0 | **0 / 100** |
| Med GTIN/EAN | 100 | 100 |
| Med bild | 100 | 100 |
| Med ordinarie pris | 100 | 100 |
| Med jämförpris | 100 | 100 |
| Med kampanjpris | 3 | 3 |
| **Med medlemspris** | **5** | **5** |
| Med multibuy | 3 | 3 |
| Fel | 0 | 0 |

```bash
python -m backend.services.grocery.collectors.hemkop --store 4256 --limit 100
```

Ingen blockering. Bilder stickprovsverifierade (riktiga JPEG/PNG, HTTP 200).
Hemköp är den enda kedjan hittills där **medlemspriser** faktiskt förekommer
i datan — de lagras som `member_price`, aldrig som `campaign_price`.

Prissättningen är **nationell**, verifierat på samma sätt som Willys:
`storeId=4256` (Uppsala Svava) och `storeId=4203` (Falun C) ger byte-identiska
svar (27221 B båda) med identiska priser.

### Coop

**Kan inte byggas utan Coops egen API-nyckel.** All produkt-/prisdata ligger
bakom `external.api.coop.se`, som kräver en Azure APIM-nyckel
(`Ocp-Apim-Subscription-Key`) inbäddad i Coops frontend. Verifierat: utan
nyckel → **HTTP 401**, med ogiltig nyckel → **HTTP 401**. Sökresultatsidans
HTML innehåller noll produktdata (allt renderas klientsidan), det finns inga
serverrenderade produktsidor, och `robots.txt` förbjuder uttryckligen
`/handla/sok/*` och `/handla/search*`.

Att plocka ut Coops nyckel ur deras frontend och använda den i vår collector
vore att autentisera oss med någon annans credential. Det gör vi inte.

### ICA

**Verifierad förstaimport (2026-08-30)** — Maxi ICA Stormarknad Gävle,
store/account ID `1003987`:

- 262 produkter hittade, 100 sparade (`--limit 100`)
- **100/100** med bild-URL (stickprov verifierade: riktiga JPEG, HTTP 200)
- **100/100** med ordinarie pris
- **100/100** med jämförpris (unit price)
- **0/100** med GTIN/EAN — *ICA exponerar det inte alls i de endpoints som hittats*
- **0/100** med kampanjpris eller medlemspris — inget observerat på någon stickprovad produkt
- 0 fel, 81,2 s

```bash
python -m backend.services.grocery.collectors.ica --store 1003987 --limit 100
```

**Känd begränsning — upprepad hämtning utlöser AWS WAF challenge.**
Efter en full collector-körning slutar ICA svara med data och returnerar
istället `HTTP 202` + headern `x-amzn-waf-action: challenge` med tom body.
Det är volymbaserat: det släpper efter några minuters tystnad och återkommer
så snart en ny körning startar. Både `curl` och Python behandlas identiskt,
så det är inte ett klientkonfigurationsproblem.

Vi försöker **inte** lösa eller kringgå den utmaningen. Konsekvens: ett
nattligt ICA-jobb måste förvänta sig att bli utmanat partway och behandla en
delvis import som normalt, inte som ett fel.

## Regler för nya providers

1. **Gissa aldrig endpoints.** Verifiera mot riktiga live-responses och
   dokumentera vad du faktiskt hittade — inklusive fält som *saknas*.
2. **Hitta aldrig på GTIN/EAN.** Saknas det ska det vara `null`.
3. **Kringgå aldrig CAPTCHA, WAF, inloggning eller rate limits.** Blockerar
   en kedja automatisk hämtning: dokumentera det och sätt providerns
   `status`, precis som för ICA.
4. Använd vanlig HTTP/JSON om det fungerar — Playwright bara om det är
   bevisat nödvändigt.
5. En misslyckad körning får **aldrig** radera befintliga priser.


### City Gross

**Verifierad import (2026-08-30)** — City Gross Gävle, `storeNumber` **3209**.
Notera: söknings-endpointen accepterar bara `storeNumber`, inte butikens `id`
(3136) eller `siteId` (35) — verifierat genom att de senare ger tomma
träfflistor.

| | Körning 1 | Körning 2 |
|---|---|---|
| Produkter hittade | 1705 | 229 ⚠️ |
| Sparade | 100 | 100 |
| Nya / uppdaterade | 100 / 0 | **0 / 100** |
| Med GTIN | 100 | 100 |
| Med bild | 100 | 100 |
| Med ordinarie pris | 100 | 100 |
| Med jämförpris | 100 | 100 |
| Fel | 0 | 0 |

```bash
python -m backend.services.grocery.collectors.citygross --store 3209 --limit 100
```

**Rikast data av alla kedjor:** explicit `gtin`-fält (inte härlett), explicit
`ordinaryPrice`/`currentPrice`/`memberPrice`/`promotions`, `lowestPriceLast30Days`
och riktiga kategorinamn (`bfCategory`).

**GTIN normaliseras till 14 siffror.** City Gross returnerar EAN-13
(`7340083443893`) medan Axfood-kedjorna ger GTIN-14 (`07340083443893`) för
samma vara. Utan nollutfyllnad hade cross-chain-matchningen tyst misslyckats.

**`campaign_price` sätts bara när `currentPrice` faktiskt är lägre än
`ordinaryPrice`** — annars hade ordinarie pris speglats som en rabatt som inte
finns.

⚠️ **Mindre pålitlig än Axfood-kedjorna.** City Gross stryper genom att *släppa
anslutningar*, inte genom HTTP 429. Vid 1 s mellan anrop misslyckades 13/14
sökord med `URLError` (därav 229 mot 1705 i körning 2); ett kontrollerat
omtest vid 3 s lyckades på varje anrop. Fördröjningen är därför 3 s. En
körning bör förvänta sig att vissa sökord faller bort och behandla en delvis
import som normalt.

### Lidl — inte möjlig

**Lidl Sverige publicerar inga produktpriser online.** Detta är en strukturell
egenskap hos deras affärsmodell, inte ett blockerings- eller
credential-problem, och går därför inte att lösa tekniskt.

Verifierat:
- `lidl.se` är en marknadsförings-/reklambladssajt utan e-handel.
- Produktsidor **finns** (505 st via `product_sitemap.xml.gz`) och har
  JSON-LD `Product`-markup med `sku`, `name`, `image` och `brand`.
- Men `offers`-blocket innehåller **inget `price`-fält** — bara
  `priceCurrency: "SEK"` och `availability: "InStoreOnly"`.
- Ingen prissträng (`XX,XX kr`) förekommer någonstans i sidans HTML.
- `matriket.lidl.se` är också en varumärkessida, inte en butik.

Veckoerbjudanden finns bara som digitalt reklamblad, inte som strukturerad
per-produkt-prisdata.
