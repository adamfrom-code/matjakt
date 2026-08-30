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

## Produktmatchning (prioritetsordning)

1. **GTIN**
2. **EAN**
3. Kedjans eget stabila `external_product_id` (via `grocery_product_external_ids`)
4. `brand + normaliserat namn + storlek`, **exakt** match

Steg 4 är avsiktligt *inte* fuzzy. En felaktig sammanslagning (två olika
produkter blir en) är värre än en missad (samma produkt får två rader tills
ett GTIN dyker upp).

## Providerstatus

| Kedja | Status | Återkommande import verifierad? |
|---|---|---|
| **Willys** | `working` (nationell prissättning) | ✅ **Ja** |
| **ICA** | `working_but_rate_limited` | ❌ Nej — AWS WAF |
| **Coop** | `blocked_requires_vendor_credential` | ❌ Nej — API kräver Coops egen nyckel |
| Hemköp | ej byggd | – |
| City Gross | ej byggd | – |
| Lidl | ej byggd | – |

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
