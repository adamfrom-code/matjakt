# Matjakt — kravmatris

Beständig arbetslista från ägarens masterinstruktion 2026-09-07. **Inget krav
får försvinna härifrån.** Nästa session fortsätter i den här filen i stället
för att börja om.

## Statusord

| Status | Betyder |
|---|---|
| `verifierat` | Byggt, testat OCH kontrollerat i den miljö som räknas |
| `klart att testa` | Kod finns och är mergad, men effekten är inte kontrollerad |
| `pågår` | Påbörjat i en gren/PR |
| `att göra` | Inventerat, inte påbörjat |
| `behöver verifieras` | Fanns redan i koden; effekten är inte bekräftad av mig |
| `blockerat` | Kräver åtkomst, betalning eller beslut jag inte har |

**Färdig kod ≠ mergad kod ≠ driftsatt kod ≠ verifierad produktion.** Kolumnen
Bevis säger vilket av dem som faktiskt gäller.

---

## Kända begränsningar i min verifiering

Det här gäller allt nedan och ska inte behöva upprepas per rad:

- **Ingen ICA- eller Coop-import har någonsin körts.** Basket coverage, gate-%
  och canonical match för dem är därför `ej verifierat`, aldrig uppskattat.
- **Admin-token hanterar jag inte.** Manuella importer via
  `/api/admin/grocery-import` kan jag inte starta.
- **Primats kvot** kan bara läsas om deras API exponerar den. Tills det är
  bekräftat står `ej tillgängligt` — ingen egen räknare presenteras som deras.
- Backendsviten körs lokalt med Python 3.12 (`backend/venv`) sedan 2026-09-07.

---

## F — fynd att revalidera och rätta (Fas 1)

| ID | Krav | Status | Bevis / nästa steg |
|---|---|---|---|
| F1 | Ofullständig kasse får inte krönas billigast | **pågår** | Revaliderat mot `235958a`: felet fanns kvar. Fix + regressionstest i PR #9, 1142 tester gröna lokalt |
| F2 | Veckoval ska prissättas med riktig prismotor, inte ungefärlig kostnad | att göra | `comboEstimatedCost` summerar separata inköpspriser och skalar linjärt. Kräver kandidatval → riktig prissättning av ett fåtal hela kassar |
| F3 | Färskhet per prisrad, även referenspriser | att göra | `_chain_age_seconds` använder senaste tidsstämpeln i kedjan; en färsk rad kan dölja gamla |
| F4 | Skilj möjlig / planerad / genomförd besparing | att göra | `savingsLog` skrivs vid val, inte vid handling. Flera val ger flera poster |
| F5 | Osäker enhetsgenväg får inte räknas som exakt | att göra | `price_item` kan sätta exakt ett paket vid misslyckad omräkning |
| F6 | Databasincidenten i git-historiken | **blockerat** | Kräver force-push mot delad historik = ägarbeslut. Ingen destruktiv sanering utan uttryckligt godkännande |
| F7 | Skilj CI, merge och deploy | verifierat | Kontrollerat 2026-09-07: `main` `235958a` live på backend, webben v34. Den misslyckade Pages-körningen följdes av en lyckad |

---

## O — Operations (Fas 2)

| ID | Krav | Status | Bevis / nästa steg |
|---|---|---|---|
| O1 | Driftstatus som adminförstasida | att göra | Datan finns i `provider_status()`; renderingen i `admin.html` saknas |
| O2 | Rad/kort per kedja med health, released, scope, snapshot, ålder, gate | **pågår** | `chain_health()` byggd med 9 tester (PR #8). UI saknas |
| O3 | ICA/Coop: visa ej släppt, schema, ingen verifierad snapshot | **pågår** | Schema dagligen 05:30/06:30 mergat (#5). Coverage `ej verifierat` |
| O4 | Lidl som Limited med orsak | **pågår** | `limited` finns i statusmodellen och larmar aldrig |
| O5 | Aktiva incidenter med kundpåverkan | delvis | Incidenter finns i `alerts.py`; adminvyn som visar dem saknas |
| O6 | Incidenthistorik, persistenta ID, dedupe | **pågår** | Dedupe + recovery byggt och testat (PR #8). Historikvy saknas |
| O7 | Admin-mail: skilj mottagare/transport/försök/leverans | delvis | `MATJAKT_ADMIN_EMAIL` optional, tyst utan den. De fyra nivåerna särskiljs inte än |
| O8 | Primat: configured JA/NEJ, kvot endast från verklig API-data | **blockerat** | Ingen dokumenterad kvot-endpoint hittad. Står `ej tillgängligt` tills motsatsen bevisas |
| O9 | Scheduler: schema, faktiska körningar, nästa körning | delvis | Operations-koll 07:00 inkopplad med test som kräver att den ligger efter alla importer |
| O10 | Pricing audit med definierade nämnare | behöver verifieras | Audit finns och är GRÖN i produktion. Live-parsningsvägen granskas INTE av den |
| O11 | Deploy: commit, tider, avvikelse | delvis | `health.commit` finns; jämförelse mot förväntad deploy saknas |
| O12 | Skyddat admin-API, inte bara dold knapp | behöver verifieras | `_admin_ok()` finns på endpointerna; negativa tester för household-medlem saknas |
| O13 | Mobilanpassad admin | att göra | |
| O14 | Testlista för Operations | delvis | 21 av testerna finns (chain_health 9, alerts 12) |
| O15 | Active stores + kvotmonitorering | att göra | De fyra definitionerna (register / valda / färska / kundtillgängliga) ska hållas isär |

---

## U — konsumentappen (Fas 4–6)

Samtliga 80 krav är inventerade. Ingen är påbörjad; de kräver Operations
först enligt ägarens egen faseordning.

| Grupp | ID | Status |
|---|---|---|
| Första användningen | U01–U06 | att göra |
| Veckoplanering | U07–U18 | att göra |
| Pengar | U19–U30 | att göra (U19 = F1, **pågår**) |
| I butiken | U31–U42 | att göra |
| Matlagning | U43–U52 | att göra |
| Skafferi och rester | U53–U60 | att göra |
| Utseende och känsla | U61–U70 | att göra |
| Teknik | U71–U80 | att göra (U72 delvis: cacheversion mergad i PR #7; U80 = F6, blockerat) |

## X — ytterligare produktflöden

`X01`–`X17` inventerade, alla `att göra`. X16 (köp hela listan) är
**blockerat** av avtal/åtkomst: tidigare granskning visade tomt
providerregister och hemsidefallback, inte färdig korgöverföring.

## A — ägarpanelen utöver Operations

`A01`–`A09` inventerade, alla `att göra`. A06 (ekonomi) kräver verifierad
betaldata; ingen intäktssiffra får härledas ur antal Premium × pris.

---

## Gjort i den här sessionen

| Vad | PR | Verifiering |
|---|---|---|
| Jämförpris räknades som förpackningspris (Hemköp 6–18× fel) | #4 mergad | Bekräftat på 16 varor i produktion; fixen live-verifierad |
| Publiceringsgrindens 95 %-gräns testad vid kanten | #6 mergad | 94,9 % nekas, 95,0 % publiceras, last-good behålls |
| Cachade priser bär tolkningens version | #7 mergad | Gamla felpriser serveras inte längre i sex timmar efter en fix |
| ICA/Coop dagligen via Primat | #5 mergad | `RELEASED_CHAINS` orörd — kedjorna blir inte publika av sig själva |
| Driftstatus + larm med dedupe och recovery | #8 öppen | 21 tester; ett av dem hittade att en API-nyckel kunde mejlas i klartext |
| F1: ofullständig kasse krönas inte | #9 öppen | Regressionstest med exakt scenariot ur granskningen |

## Kvar för ägaren

1. **`MATJAKT_ADMIN_EMAIL`** i Render — utan den är driftlarmen tysta.
2. **Merga #8 och #9** när du granskat dem.
3. **Primat App-nivå** — betalbeslut. Gratisnivån räcker inte för ICA och
   Coop samma natt.
4. **F6 databasincidenten** — kräver ditt godkännande för historikrensning.
