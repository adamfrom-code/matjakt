# Dabas — produktmasterdata (inte priser)

**Dabas = vad produkten ÄR. Prisproviders/partnerbutiker = vad produkten KOSTAR.
Matjakt kopplar ihop produkt + recept + mängd + pris + butik.**

Adapter: `backend/services/grocery/providers/dabas.py` · Berikning:
`backend/services/grocery/enrichment.py` · Tester: `backend/tests/test_dabas.py`.

## 1. Endpoints (Dabas WebApi v1, OpenAPI 3.0.1, `https://api.dabas.com/swagger/v1/swagger.json`)

| Använd | Endpoint | Varför |
|---|---|---|
| ✅ primär | `GET /DABASService/V2/article/gtin/{gtin}/{JSON\|XML}` | fullständig artikel (147 fält) per GTIN |
| ✅ vid multipack | `GET /DABASService/V2/completearticlehierarchy/gtin/{gtin}/{format}` | konsument-/DFP-enhet, `AntalEnheter` |
| ✅ delta | `GET /DABASService/V2/articles/datetime/{datetime}/{format}` | ändrade artiklar sedan datum — omprövning utan att slå upp allt |
| ✅ versioner | `GET /DABASService/V2/articleversions/gtin/{gtin}/{format}` | `dabas_source_version` |
| ⏸ senare | `/categorytree`, `/articles/{format}` (alla GTIN), `/articles/searchparameter/…` | kategoriträd och fritextsök behövs inte för GTIN-berikning |

Autentisering: `?apikey=` (query). Svar: JSON eller XML (adaptern tolkar båda).
Statuskoder: 200, 401 (fel nyckel → stoppar körningen), 404 (ingen artikel →
`not_found`), 500 (retry med backoff 0,5/1,5/4 s), 429 (backa av, ingen retry-storm).
**Rate limits är inte dokumenterade** — adaptern håller ≥ 0,25 s mellan anrop och
max 300 uppslag per körning tills gränserna är kända (§7).

## 2. Fältmappning → `grocery_products`

| Matjakt | Dabas (T-kod) | Merge |
|---|---|---|
| `gtin` | `GTIN` (T0154) → 14 siffror, GS1-kontroll | nyckel — svar med annat GTIN avvisas |
| `name` | — (kedjans hyllnamn behålls) | Dabas namn i `dabas_name`; fyller bara en **namnlös** produkt |
| `dabas_name` | `Produktnamn` (T3337) → `RegleratProduktnamn` (T4800) → `Artikelkategori` | Dabas |
| `brand` | `Varumarke.Varumarke` (T0143), `Undervarumarke` (T2230) | **Dabas > provider** |
| `manufacturer` | `Varumarke.Tillverkare.Namn` (T3811) → `Uppgiftslamnare.Foretagsnamn` | Dabas |
| `dabas_category`, `dabas_gpc` | `Artikelkategori` (T0018), `GPCKod` (T0280), `KompletterandeProduktklass` | Dabas — extra REJECT-signal i matchningen |
| `category` | — | providerns behålls; fylls från Dabas bara om tom |
| `quantity`/`unit`/`size` | `Nettoinnehall[]` (`Mängd` T0082, `EnhetKod` T0311, `Typ`), `T4330_Nettovikt`, `Variabelmattsindikator` (T0186) | se §3 |
| multipack | `Forpackningar[].Antalenheter`, hierarkins `AntalEnheter`, `Komponenter[]` | `package.multipack_count` |
| `ingredients` | `Ingredienser[].Beskrivning` (T4094) → `Komponenter[].Ingrediensforteckning` | Dabas |
| `allergens` (JSON) | `Allergener[]` (`Allergen`, `Nivakod` T4079: innehåller / kan innehålla / fri från) | Dabas |
| `nutrition` (JSON) | `Naringsinfo[]` → `Naringsvarden[]` (`Benamning`, `Mangd` T4074, `Enhet` T5101) per `Basmangdsdeklaration` (T3824) | Dabas |
| `description` | `KortMarknadsbudskap` → `Marknadsbudskap` → `Variantbeskrivning` | fyller bara tom |
| bilder | `Bilder[]`/`MediaFiler[]` (`Lank` T3405, `Filformat` T2238) | **läses, sparas INTE** (bara format/typ) — se §9 |
| `dabas_source_version` | `SenastAndradDatum` → `SkapadDatum` | metadata |
| `dabas_data` | normaliserat utdrag (JSON, utan bild-URL:er) | metadata |

Enhetskoder som förstås: GRM/g/kg/hg/mg → g; MLT/ml/cl/dl/l → ml; st/stk/H87/PCE → st.
Okänd enhet → mängd okänd (aldrig gissad).

## 3. Paketverifiering (hög prioritet)

Providerns tolkning (`effective_package`) jämförs med Dabas nettoinnehåll
(**avrunnen vikt före nettovikt före volym före antal**, tolerans 2 %):

| Provider | Dabas | `package_source` | `package_confidence` | Effekt |
|---|---|---|---|---|
| 450 g | 450 g | `DABAS_VERIFIED` | `high` | mängd bekräftad |
| saknas | 450 g | `DABAS_VERIFIED` | `high` | luckan fylls |
| 450 g | 500 g | `PROVIDER_DATA` | `conflict` + `package_conflict`-text | **mängden används inte** — `effective_package` → okänt → raden osäker, aldrig i säkra totaler |
| 450 g | saknas | `PROVIDER_DATA` | `provider` | som förut |
| ca 750 g | variabelmått | `PROVIDER_DATA` | `provider` | lösvikt — cirkavikten får stå |

## 4. Kanonisk matchning

`_dabas_category_allows()` i `pricing.py` prövar produktens Dabas-kategori genom
samma avdelningsvakt som kedjornas kategorier. `Kanel` mot Dabas-kategori
`Knäckebröd` → REJECT även om namnet leder med "Kanel". Dabas stärker reglerna;
alla befintliga regressionstester (release gate, kanonisk matris) passerar oförändrade.

## 5. Berikningsflöde och cache

`enrichment.run_enrichment()` — nattjobb 05:00 (efter prisjobben) + admin
`POST /api/admin/dabas-enrich {"limit": N}`; aldrig i en app-request.

1. produkt med GTIN? annars ingen berikning
2. `dabas_status = ok` och kontrollerad < 30 dagar → **inget anrop**
3. `not_found` omprövas efter 30 dagar, `error` efter 6 timmar
4. svar → `normalize_article` → validering (GTIN måste stämma) → fältvis merge → `apply_product_fields`
5. metadata: `dabas_status` (ok/not_found/error), `dabas_last_checked`, `dabas_last_success`, `dabas_error`, `dabas_source_version`

Aktivering kräver **både** `DABAS_API_KEY` och `MATJAKT_DABAS_ENRICHMENT_ENABLED=1`.
Nyckeln läses bara ur miljön; `_redact()` tar bort den ur felmeddelanden; testerna
låser att den aldrig syns i fel eller produktdata. `.env` är gitignorerad.

## 6. Villkor (läst 2026-09-02)

**"Allmänna villkor för Dabas Webservice API"** (PDF, dabas.blob.core.windows.net) —
hela texten är fyra meningar:

> Dabas Webservice erbjuder fri användning av våra uppgiftslämnares artikelinformation. Observera dock att Delfi vid varje tillfälle äger oinskränkt rätt att stänga av en användare från informationsflödet, om Delfi anser att informationen eller nyttjande av tjänsten missbrukas. […] Delfi tar vidare inget ansvar för datainnehåll […]. **Om man publicerar information från Dabas måste källan (Dabas) anges.**

"Allmänna villkor för avtal om Dabas" (användardelen) säger samma sak, och
nämner uttryckligen **kostplaneringsprogram** som avsedd användartyp. §5
(uppgiftslämnardelen): rätten till databasen tillkommer Delfi; rätten till
den enskilda produktinformationen stannar hos leverantören.

| Fråga | Villkoren säger |
|---|---|
| kommersiell användning | "fri användning" — inget förbud, kostplaneringsprogram nämns som användare; **inte uttryckligen "kommersiellt"** |
| lokal cache / permanent lagring / lagringstid | **nämns inte** |
| vidarevisning i konsumentapp | "Om man publicerar information från Dabas måste källan (Dabas) anges" → tillåtet med **källangivelse** |
| attribution | **krävs**: källan "Dabas" ska anges där informationen publiceras |
| bilder | **nämns inte**; leverantören behåller rätten till sin produktinformation |
| prishistorik/produktversioner | nämns inte (Dabas har inga priser) |
| uppsägning | Delfi får stänga av när som helst utan motivering |
| kostnad | gratis (dabas.com/onboard) |

Slutsats: modellen är **inte uttryckligen täckt** för lagring/cache och bilder.
Berikningen är därför byggd men **inte aktiverad**, och bilder cacheas inte.

## 7. Mejl att skicka till Dabas/Delfi (info@delfi.se)

> **Ämne:** Matjakt – bekräftelse av användningsmodell för Dabas Webservice API
>
> Hej,
>
> Vi bygger Matjakt (matjakt.store), en svensk konsumentapp som hjälper barnfamiljer att planera veckans mat och jämföra vad matkassen kostar i butiker nära dem. Vi har fått tillgång till Dabas Webservice API och vill innan vi tar det i drift få er skriftliga bekräftelse på att vår användning stämmer med era villkor.
>
> Så vill vi använda Dabas:
> 1. **Produktmasterdata, inte priser.** Vi slår upp artiklar per GTIN (namn, varumärke, tillverkare, kategori, nettoinnehåll, ingredienser, allergener, näringsvärden) och använder det för att verifiera förpackningsstorlekar och koppla produkter till recept. Priser kommer från andra källor.
> 2. **Lokal lagring.** Vi sparar den normaliserade produktinformationen i vår egen databas och slår upp varje GTIN på nytt högst en gång per 30 dagar (ändrade artiklar via `articles/datetime`). Är det förenligt med villkoren, och finns någon längsta lagringstid?
> 3. **Vidarevisning till konsument.** Produktnamn, varumärke, förpackning, ingredienser och allergener visas för appens användare, med källangivelsen "Produktinformation från Dabas". Räcker den formuleringen som källhänvisning?
> 4. **Visning för butiker (B2B).** Vi planerar en butikstjänst där anslutna butiker ser sina egna produkter med samma masterdata. Omfattas det av "fri användning"?
> 5. **Produktbilder.** API:t returnerar bildlänkar (`Bilder`/`MediaFiler`). Får vi visa och cachea dessa bilder i appen, och i så fall med vilken attribution? Vi använder dem inte förrän vi fått besked.
> 6. **Kommersiell tjänst.** Matjakt är en kommersiell konsumentapp (gratis + betald nivå). Vi vill bekräfta att det ryms inom "fri användning".
> 7. **Volym och takt.** Vi räknar med initialt cirka 20 000 GTIN-uppslag och därefter några hundra per dygn. Finns rate limits eller takt ni vill att vi håller?
>
> Tack på förhand – vi vill göra rätt från start.
>
> Vänliga hälsningar
> Adam From, Matjakt

## 8. Kostnad

Gratis (Dabas: "Att använda och ansluta sig till tjänsten är gratis"). Ingen
prislista finns; artikelavgifter betalas av uppgiftslämnarna, inte användarna.

## 9. Bildrättigheter

Villkoren säger ingenting om bilder. Leverantören behåller rätten till sin
produktinformation (§5). Därför: bild-URL:er **läses inte in i `dabas_data`**,
inga Dabas-bilder hämtas, visas eller cacheas i produktion förrän Delfi svarat
på fråga 5 ovan. Open Food Facts-fallbacken är kvar för bilder.

## 10. Aktiveringschecklista (produktion)

- [ ] `DABAS_API_KEY` satt i Render (aldrig i repo/frontend/loggar)
- [ ] riktiga testuppslag via `POST /api/admin/dabas-lookup {"gtin": …}` för mjölk, ägg, köttfärs, fiskpinnar, persilja, kanel, yoghurt, pasta, multipack, avrunnen vikt — provider vs Dabas vs normaliserad produkt
- [ ] rate limits kända (ur svaren/beskedet från Delfi)
- [ ] villkor för lagring/cache/bilder bekräftade skriftligt (mejlet i §7)
- [ ] tester gröna (`backend/tests/test_dabas.py`)
- [ ] `MATJAKT_DABAS_ENRICHMENT_ENABLED=1` i Render → nattjobb 05:00
- [ ] källangivelse "Produktinformation från Dabas" där masterdata visas
