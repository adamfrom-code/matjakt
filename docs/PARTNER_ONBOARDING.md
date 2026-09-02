# Partnerbutik — onboarding (backend)

Så ansluts en butik som levererar **verifierade lokala priser** till Matjakt.
Ingen frontend krävs: allt sker via admin-API:t och partnerns egen feed-endpoint.
Priset per paket (**Matjakt Butik, 1 495 kr/mån**) ligger i tabellen
`grocery_partner_plans` — ändras med data, inte kod.

Grundregel som aldrig förhandlas: **betalning påverkar aldrig rankingen.**
En partner får rätten att *leverera* priser. Om butiken är dyrare blir den inte
"Billigast". Partnerpriser blir aldrig kedjans referenspris.

## 1. Skapa butiken (finns oftast redan)

Alla ~2 800 svenska butiker ligger i `grocery_stores` via det nationella
registret (`POST /api/admin/store-register-sync`). Slå upp butiken på kedja +
butikens eget id (ICA: t.ex. `1003987`, Coop: `206403`, Lidl: `SE0128`,
Willys/Hemköp: butiksnummer). Saknas butiken: kör registersynken.

Ägarform styr partnermodell (`register.CHAIN_PARTNER_MODEL`):

| Kedja | Modell | Vem tecknar |
|---|---|---|
| ICA, Hemköp (handlarägda), Tempo, Handlar'n, Matöppet | `PER_STORE` | butiken själv |
| Coop | `PER_GROUP` | föreningen — en partner, många `store_ids` |
| Willys, Lidl, City Gross | `PER_CHAIN` | centralt — `chain_partner_id` aktiverar alla butiker |

## 2. Teckna partnern och utfärda API-nyckel

```bash
curl -X POST https://matjakt.onrender.com/api/admin/partner \
  -H "X-Admin-Token: $MATJAKT_ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"create","kind":"PER_STORE","name":"ICA Maxi Gävle","chain":"ICA","storeIds":["1003987"],"contactEmail":"butik@example.se"}'
```

Svar: `{"partnerId": 7, "apiKey": "mjp_…", "storeIds": [123], "status": "PENDING"}`.

**API-nyckeln visas exakt en gång** — bara hashen lagras hos oss. Ge den till
butiken via säker kanal. Tappad nyckel = ny partnerpost.

Grupp: samma anrop med `"kind":"PER_GROUP"` och flera `storeIds`.
Kedja: `"kind":"PER_CHAIN","chain":"Willys"` utan `storeIds`.

## 3. Aktivera

```bash
curl -X POST …/api/admin/partner -H "X-Admin-Token: …" \
  -d '{"action":"activate","partnerId":7}'
```

Status: `PENDING → ACTIVE`. Först nu tas feeds emot. Andra åtgärder:
`pause` (PAUSED), `cancel` (CANCELLED), `pending`.

**Paus/avslut tar bort partnerns publicerade priser omedelbart** — utan aktiv
leverantör finns ingen som går i god för dem — och appen faller tillbaka på
kedjans referenspris ("ICA referenspris"). Inget annat ändras.

## 4. Feedformat

Butiken skickar hela sitt sortiment eller en delmängd; varje leverans slås
ihop (merge) med tidigare — rader som inte skickas behåller sitt senaste
pris tills det är äldre än **4 dygn**, då referenspriset tar över.

### CSV (rekommenderat — Excel "Spara som CSV" fungerar)

Semikolon eller komma, UTF-8 eller Windows-1252, svenska decimaler (`19,90`).
Rubrikerna är skiftlägesokänsliga och accepterar svenska eller engelska namn:

```
GTIN;Produktnamn;Märke;Storlek;Ordinarie pris;Kampanjpris;Medlemspris;Giltig från;Giltig till
7310865093530;Standardmjölk 3%;Arla;1000 ml;18,90;;;2026-09-01;
7310865001115;Färsk lättmjölk 0,5%;Arla;1000 ml;16,90;14,90;;2026-09-01;2026-09-07
```

Fullt exempel: [docs/exempel/partnerfeed.csv](exempel/partnerfeed.csv).

| Kolumn (alias) | Krav |
|---|---|
| `GTIN` (`EAN`, `Streckkod`) | 8/12/13/14 siffror med giltig GS1-kontrollsiffra. Bästa nyckeln — samma GTIN = samma produkt i hela Matjakt. |
| `Artikelnummer` (`SKU`) | valfritt, butikens eget id (används när GTIN saknas) |
| `Produktnamn` (`Namn`) | krävs om GTIN saknas |
| `Märke` (`Brand`) | valfritt |
| `Storlek` (`Förpackning`, `Size`) | t.ex. `500 g`, `1,5 l`, `6-pack` — **utan storlek kan raden aldrig ingå i en säker totalsumma** |
| `Ordinarie pris` (`Pris`) | kr, > 0 |
| `Kampanjpris` | kr, måste vara **lägre** än ordinarie — annars ignoreras |
| `Medlemspris` | kr, visas men räknas aldrig som kassapris |
| `Giltig från` / `Giltig till` | ISO-datum (`2026-09-07`) eller `7/9 2026`; "till" gäller kampanjen |
| `Kategori` | valfritt |

### JSON / API

`POST /api/partner/feed` med header `X-Partner-Key: mjp_…`:

```json
{"storeId": 123, "format": "API", "rows": [
  {"gtin": "7310865093530", "namn": "Standardmjölk 3%", "storlek": "1000 ml", "pris": "18,90"},
  {"gtin": "7310865001115", "namn": "Färsk lättmjölk 0,5%", "storlek": "1000 ml",
   "pris": 16.90, "kampanjpris": 14.90, "giltig_till": "2026-09-07"}
]}
```

`storeId` är Matjakts interna butiks-id (fås vid teckningen). CSV/XLSX kan
även lämnas via admin: `POST /api/admin/partner-feed` med `format: "CSV"` och
filinnehållet i `payload`.

Svar: `{"received": 2, "parsed": 2, "staged": 2, "published": 2, "gatePercent": 100.0, "publishedOk": true, "rowErrors": []}`.

## 5. Kvalitetskrav — samma gate som kedje-API:erna

Varje rad passerar `publish.gate_row`; körningen som helhet `publish_run`:

- pris > 0 och ≤ 30 000 kr; jämförpris ≤ 5 000 kr/enhet
- kampanjpris lägre än ordinarie, annars nollas det
- produkt måste ha namn; ogiltig GTIN → raden behålls utan GTIN (matchas på artikelnummer/namn)
- **minst 95 % av raderna måste godkännas** — annars publiceras ingenting och senaste godkända priser behålls
- inga negativa priser, inga 0-priser, inga extrema priser — sådana rader blir aldrig synliga

Osäker rad = `PRICE_MISSING`. Ingen gissning. Radfel rapporteras i
`rowErrors` (radnummer + orsak) så butiken kan rätta sin fil.

## 6. Vad butiken får

- **"✓ Verifierat lokalt pris · uppdaterat idag"** i stället för "ICA referenspris"
- butikens namn på priskortet, egna kampanjer med giltighetsdatum
- anonym statistik (`POST /api/admin/partner-stats {"storeId": 123}`): visad, jämförd,
  billigast, erbjudande visat/sparat — per dag, aldrig per användare

## 7. Adminöversikt

`POST /api/admin/partner-overview` → per butik: partnerstatus, antal priser,
senaste synk, quality gate-procent för senaste körningen, senaste feed.

## 8. Testa flödet utan en riktig butik

Skapa en isolerad testbutik (kedja + `external_store_id` `TEST-…`, utan
koordinater så den aldrig dyker upp i närhetssök), teckna, aktivera, skicka
`docs/exempel/partnerfeed.csv`, verifiera `VERIFIED_STORE_PRICE`, pausa,
verifiera fallback till referens — och radera testdatan (partner, feeds,
statistik, priser, butik). Backendprovet 2026-09-02 gjorde exakt detta.
