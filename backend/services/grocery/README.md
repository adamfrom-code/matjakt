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
| **ICA** | `working_but_rate_limited` | ❌ Nej — se nedan |
| Coop | ej byggd | – |
| Willys | ej byggd | – |
| Hemköp | ej byggd | – |
| City Gross | ej byggd | – |
| Lidl | ej byggd | – |

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
