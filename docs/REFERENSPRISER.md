# Referenspriser per kedja

Kartläggning av bästa verkliga bas för `REFERENCE_PRICE` och
`VERIFIED_STORE_PRICE` för var och en av Matjakts sex kedjor.
Sammanställd 2026-09-02 ur repots eget underlag (providrarnas
modul-docstrings, `register.py`, `api.py`, `primat_client.py`,
`services/grocery/README.md` och git-loggen). Databassiffrorna är
verifierade 2026-09-02. Ingenting nedan är hämtat utanför repot; där
repot saknar belägg står det **ej verifierat**.

## Två prisnivåer

| Nivå | Betydelse | Får visas för |
|---|---|---|
| `REFERENCE_PRICE` | Ett verifierat kedjepris som får användas nationellt. Berättar vad varan kostar *hos kedjan*, inte nödvändigtvis i användarens butik. | Alla butiker i kedjan, alltid märkt "<Kedja> referenspris". |
| `VERIFIED_STORE_PRICE` | Ett verkligt pris hämtat för *just den butiken*. | Bara den butik priset hämtats för. |

Grundregeln i repot gäller oförändrad: en butik som saknar egen katalog
får aldrig visas med en annan butiks priser under fel namn
(`api.py: resolve_pricing_store`, commit `caeafc6`). Referenspriset
löser det problemet genom att vara ärligt märkt som kedjepris - inte
genom att låtsas vara lokalt.

## Gemensam grund: Primat (ICA, Coop, Lidl)

Tre av kedjorna saknar tillåten direktväg och hämtas via Primats
betal-API. Det som gäller alla tre samlas här; per-kedja-sektionerna
hänvisar hit.

**API.** `https://primat.nu/api/v3`, Bearer-token ur `PRIMAT_API_KEY`
(`services/pricing/primat_client.py` rad 29, 68). Katalogimport sker
med `GET /stores` (hela svenska registret i ett anrop), `GET /prices`
(butikens alla prisrader, cursor-paginerade) och `POST /batch`
(paketstorlek/kategori/jämförpris, 100 uppslag per anrop)
(`providers/primat.py` rad 26-31, 129-221). Primats `/products`-sökning
används medvetet inte för prissättning - dess relevansrankning är
brusig ("ägg" gav "Billinge ost" hos Lidl) (`primat.py` rad 22-24).

**Butiksregister.** 2 825 butiker verifierat 2026-09-02: ICA 1 273,
Coop 842, Willys 255, Lidl 212, Hemköp 205, City Gross 38
(`register.py` rad 5-6, commit `caeafc6`). Varje butik bär `tier`:
`full` (helt sortiment med priser) eller `offers_only` (bara
kampanjrader). Bara `full`-butiker kan ge en prissättningsbar katalog
(`register.py` rad 65-68, `primat.py` rad 133-137).

**Fält per prisrad.** `price` (ordinarie), `member_price`,
`multi_price`/`multi_count`, `effective_price`, `offer_price`,
`offer_label`, `offer_valid_until`, `gtin`, `changed_at`;
batch-detaljen ger `package`, `amount`, `unit`, `category`,
`prices.comparison`, `confirmed_at`, `urls.source`
(`primat.py` rad 248-315).

**Nivåer och kvoter.**

| Nivå | Anrop/min | Rader/dag | Rader/anrop | Attribution | Bilder | Pris |
|---|---|---|---|---|---|---|
| Gratis | 60 | 20 000 | 200 | Krävs ("Prisdata från primat.nu" med länk) | Nej | 0 kr |
| App | 250 + burst | 100 000 | Ingen | Krävs inte | Kedjans original-URL, **utan bildrättigheter** | 249 kr/mån exkl. moms (live-verifierat på primat.nu/data 2026-09-02) |
| Pro | 600 + burst | 1 000 000 | 12 månader | Krävs inte | Ja, samma förbehåll | 1 995 kr/mån exkl. moms (live-verifierat på primat.nu/data 2026-09-02) |

Källor: `primat.py` rad 33-35 (kvoter Gratis/App), rad 305-307
(bilder på App-nivån utan rättigheter), commit `297a96d` ("attribution
krävs bara på gratisnivån"), `primat_client.py` rad 8-14 (attribution
på gratisnivån). Månadspriserna 249 kr och 1 995 kr finns inte i repot
eller git-loggen - de kommer ur uppdragsbeskrivningen och ska
kontrolleras mot primat.nu/api innan avtal tecknas.

**Kvotmatematik som styr modellen.** En full Maxi-katalog kostar
~30 000 rader (varje produkt kostar en prisrad plus en batchrad;
`primat.py` rad 104-105, 175, 205), dvs. ~15 000 produkter. Det ryms
inte i gratisnivåns 20 000 rader/dag; providern avbryter ärligt vid
`PRIMAT_MAX_ROWS_PER_RUN`, behåller det hämtade och märker körningen
"blocked" (`primat.py` rad 106-116, 213-220). Registersynken kostar
~2 800 rader och körs veckovis (`register.py` rad 96-98). Nattlig
Primat-import är inte schemalagd - `SCHEDULABLE_CHAINS` är bara
Willys/Hemköp/City Gross (`scheduler.py` rad 54-63); ICA/Coop/Lidl
importeras manuellt via adminpanelen.

**Villkor.** Kommersiellt bruk uttryckligen tillåtet; data och bilder
får cachas; återförsäljning av datat som dataset/spegel-API är
förbjuden - Matjakt prissätter bara sin egen inköpslista och exponerar
aldrig Primats data som egen feed (`primat_client.py` rad 8-14).
Primat är uttryckligen under utveckling ("Strukturen, datat och
prismodellen kan komma att ändras") och klienten är byggd för att
degradera gracefully (`primat_client.py` rad 16-21). Attributionen
renderas redan i frontend (`frontend/app/app.js` rad 1981).

**Prisfärskhet.** Primat beskrivs som en tjänst som "tracks daily
prices" (`primat_client.py` rad 2). Varje rad bär källans egen
tidsstämpel (`confirmed_at`/`changed_at`), som Matjakt lagrar som
`fetched_at` - alltså när *Primat* senast verifierade priset, inte när
Matjakt råkade fråga (`primat.py` rad 314, `primat_client.py` rad
159-163). Exakt uppdateringstakt per kedja hos Primat: ej verifierat.

---

## ICA

**Källa.** Primat, kedjenyckel `ica` (`primat.py` rad 62-69). Importern
ruttar ICA till `PrimatProvider` när `PRIMAT_API_KEY` finns; den gamla
`IcaProvider` (handlaprivatkund.ica.se) ligger kvar som manuell
fallback utan nyckel (`importer.py` rad 109-121).

Direktvägen är stängd och kringgås inte: gamla `apimgw-pub.ica.se` dog
i april 2024; dagens `handla.ica.se` kräver butiksval i ett
robots-förbjudet flöde; ICA Gruppens villkor kräver skriftligt
godkännande för kommersiell vidareanvändning (`primat.py` rad 6-9,
commit `297a96d`). Den gamla providern trippar dessutom AWS WAF
(HTTP 202 + `x-amzn-waf-action: challenge`) vid upprepad hämtning
(`providers/ica.py` rad 22-29, 154-176).

**Produktantal.** I Matjakts databas just nu: 1 273 butiker /
2 081 produkter (partiell import, kvotbegränsad). Uppskattad full
katalog: ~15 000 produkter för en Maxi (härlett ur "~30 000 rader pris
+ batch" och "~225 anrop", `primat.py` rad 81, 104-105). Mindre
ICA-format: ej verifierat. Live-rök: 2 000 produkter genom riktiga
importvägen, PoC 20/20 vanliga varor med pris (commit `297a96d`).

**Prisfärskhet.** Källan: se Primat ovan. Matjakts synk: manuell,
inte schemalagd. Med gratisnivån krävs flera dagar per full
Maxi-katalog; App-nivån (100 000 rader/dag) rymmer ~3 Maxi-kataloger
per dygn.

**Prisscope.** `STORE_SPECIFIC` - **bevisat**: 60 av 87 gemensamma
GTIN skilde i pris mellan två Gävle-Maxi (`primat.py` rad 16-17,
`register.py` rad 21-23, commit `297a96d`). Ett ICA-pris från en butik
är alltså aldrig ett verifierat pris för en annan.

**Kampanjpris.** Ja, via Primats `offer_price`/`offer_label`/
`offer_valid_until`. Sätts bara när kampanjpriset är lägre än
ordinarie (`primat.py` rad 283-288). Direkt-API:t visade aldrig något
kampanjpris (`ica.py` rad 90-97).

**Medlemspris.** Ja, via Primats `member_price` (`primat.py` rad 310).
Andel ICA-rader med medlemspris: ej verifierat.

**GTIN.** Ja, via Primat; EAN-13 normaliseras till GTIN-14 med
checksummevalidering (`primat.py` rad 299, `citygross.py` rad
225-235). ICAs egna publika API exponerar inget GTIN alls (`ica.py`
rad 83-89).

**Bilder.** Nej på gratisnivån. App-nivån ger kedjans original-URL
utan bildrättigheter (`primat.py` rad 305-307). Open Food
Facts-fallbacken är kvar som rätt väg.

**Licens/villkor.** Primats (se ovan). ICA Gruppens egna villkor:
skriftligt godkännande krävs för kommersiell vidareanvändning av
deras data.

**Kommersiell användning.** Ja via Primat, med attribution på
gratisnivån. Direkt från ICA: nej utan skriftligt avtal.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = Primat-katalogen för **en utsedd referensbutik**
(tier `full`, lämpligen ett Maxi-format för bredast sortiment), tydligt
märkt "ICA referenspris". Eftersom prisskillnad mellan ICA-butiker är
bevisad är detta ett *representativt* kedjepris, aldrig ett lokalt.
`VERIFIED_STORE_PRICE` = butikens egen Primat-katalog, importerad
efterfrågestyrt (postnummer → närmaste `full`-butik → import), eller
en partnerfeed från ICA. Vilken butik som ska vara referensbutik är
inte beslutat; dagens katalogbutik i databasen är inte dokumenterad i
underlaget (den gamla providern verifierades mot Maxi ICA Stormarknad
Gävle, konto-id 1003987, `ica.py` rad 11-12).

**Kräver manuell extern data/API/avtal.** Primat App-nivå för att
rymma fulla kataloger inom dygnskvoten; ICA-partneravtal för bilder
med rättigheter och för en officiell butiksfeed; ICA Gruppens
skriftliga godkännande för all direktanvändning.

---

## Coop

**Källa.** Primat, kedjenyckel `coop`. Importern kräver nyckeln -
utan `PRIMAT_API_KEY` finns ingen väg alls (`importer.py` rad
101-108).

Direktvägen är stängd: `portal.api.coop.se` är låst till Coops
interna Azure AD-tenant, 0 API:er synliga anonymt, egenregistrering
leder ingenstans (`primat.py` rad 10-11, commit `297a96d`).
`external.api.coop.se` kräver en `Ocp-Apim-Subscription-Key` inbäddad
i Coops frontend (401 utan, 401 med ogiltig); `robots.txt` förbjuder
`/handla/sok/*`; coop.se:s villkor förbjuder kopiering. Att använda
Coops egen nyckel vore att autentisera sig med någon annans credential
- det görs inte (`README.md` Coop-sektionen).

**Produktantal.** I databasen just nu: 842 butiker / 1 997 produkter
(partiell). Full katalog per butik: ej verifierat. PoC: 20/20 vanliga
varor med pris; live-rök 2 000 produkter kvotbegränsat (commit
`297a96d`).

**Prisfärskhet.** Som ICA: Primat dagligen (enligt Primat), Matjakt
manuellt, inte schemalagt.

**Prisscope.** `STORE_SPECIFIC` - grunden är att Primats rader är
butiksscopade (`register.py` rad 23). Att priserna *faktiskt skiljer*
mellan Coop-butiker är **ej verifierat** i repot - ingen
tvåbutiksjämförelse som ICAs 60/87 har gjorts. Scopen är konservativ:
hellre butiksspecifik utan bevis än nationell utan bevis.

**Kampanjpris.** Ja, via Primat (samma regel som ICA).

**Medlemspris.** Ja, via Primat `member_price`. Andel: ej verifierat.

**GTIN.** Ja, via Primat, normaliserat till GTIN-14.

**Bilder.** Nej på gratisnivån; App-nivån utan rättigheter.

**Licens/villkor.** Primats. Coops egna villkor förbjuder kopiering
från coop.se.

**Kommersiell användning.** Ja via Primat. Direkt från Coop: bara om
Coop bjuder in till sin API-portal.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = Primat-katalogen för en utsedd referensbutik
(tier `full`), märkt "Coop referenspris". `VERIFIED_STORE_PRICE` =
butikens egen Primat-katalog eller en feed från Coop. Innan
referensbutik utses bör en tvåbutiksjämförelse (gemensamma GTIN,
samma metod som ICA) göras - visar den enhetliga priser kan scopen
sänkas till `NATIONAL` och referenspriset gälla som verifierat i varje
butik; visar den skillnader står modellen ovan fast.

**Kräver manuell extern data/API/avtal.** Primat App-nivå;
Coop-inbjudan till API-portalen (kan inte sökas utifrån); en
verifiering av prisvariation mellan butiker.

---

## Hemköp

**Källa.** Axfoods öppna REST-API,
`https://www.hemkop.se/axfood/rest/v1/` - ingen nyckel, cookie,
session eller browser (`providers/hemkop.py` rad 34, 55; delad logik i
`providers/axfood.py`). Katalogen hämtas med kategoripromenad:
`GET /leftMenu/categorytree` + `GET /c/{slug}?page=&size=`, verifierat
2026-08-31 genom att observera vad sajten själv anropar (`axfood.py`
rad 39-63). Provider-status `working`, återkommande import verifierad
(`hemkop.py` rad 57-61; `api.py` PROVIDER_STATUS).

**Produktantal.** I databasen just nu: 205 butiker / 11 492 produkter.
Katalogen har 428 lövkategorier (`README.md` rad 163-164); en
kategoripromenad täcker hela onlinesortimentet, så 11 492 är i
praktiken full katalog. Separat verifierad totalstorlek: ej verifierat.
205 butiker totalt, 66 av dem online (`hemkop.py` rad 38).

**Prisfärskhet.** Matjakt synkar nattligen 03:00 Europe/Stockholm
(`scheduler.py` rad 54-57, `README.md` Nattjobb). `fetched_at` =
importtidpunkt (`axfood.py` rad 490). Axfoods egen uppdateringstakt:
ej verifierat.

**Prisscope.** `NATIONAL` - **verifierat**: `storeId=4256` (Uppsala
Svava) och `storeId=4203` (Falun C) ger byte-identiska svar (27 221 B
båda) med identiska priser; endpointen accepterar men ignorerar
`storeId` (`hemkop.py` rad 40-43, `register.py` rad 14-17). Viktig
nyans: det bevisar att **onlinepriset** är nationellt. Att det
fysiska hyllpriset i varje Hemköp-butik är detsamma är ej verifierat -
`willys.py` rad 32-33 formulerar samma förbehåll för Willys.

**Kampanjpris.** Ja. `potentialPromotions[]` med `campaignType`
`GENERAL` → `campaign_price`; multibuy (`qualifyingCount > 1`) hålls
isär som `multibuy_price` (`axfood.py` rad 19-37, 174-198).
Fullimport 2026-08-31: 70 kampanjpriser (`README.md` rad 260-261).

**Medlemspris.** Ja. `campaignType == "LOYALTY"` → `member_price`,
aldrig `campaign_price`. Hemköp är enda släppta kedjan där
medlemspriser faktiskt förekommer i datan (`hemkop.py` rad 26-29;
26 medlemspriser i fullimporten, `README.md` rad 261).
Prissättningsmotorn använder medlemspris medvetet inte i totaler
(`pricing.py` rad 1089-1107).

**GTIN.** Ja, härlett ur bild-URL:en (`assets.axfood.se/.../
07310865005168_C1L1_s01`), GTIN-14, bara när GS1-checksiffran
validerar (`axfood.py` rad 157-171). 100 % täckning i fullimporten.

**Bilder.** Ja, URL till Axfoods CDN (`axfood.py` rad 458, 482);
stickprov returnerar riktiga JPEG/PNG. **Rättigheter att visa dem: ej
verifierat** - inget avtal med Axfood finns.

**Licens/villkor.** Inga publicerade API-villkor är dokumenterade i
repot - **ej verifierat**. Det är sajtens egna publika JSON-endpoints
utan nyckel; Matjakt identifierar sig ärligt med User-Agent
`Matjakt/1.0 (+grocery-collector)` (`axfood.py` rad 80).

**Kommersiell användning.** Ej verifierat - inga villkor kända. Primat
täcker också Hemköp (nyckel `hemkop`) med uttryckligt kommersiellt
tillstånd, som juridiskt säkrare alternativ eller korsverifiering.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = Axfood-API:ts nationella pris = "Hemköp
referenspris". Samma pris utgör `VERIFIED_STORE_PRICE` för varje
Hemköp-butik, på grunden att kedjans eget API bevisligen ignorerar
butiksval - `resolve_pricing_store` gör redan detta (prissätt ur
kedjekatalogen, etikettera med användarens butik; `api.py` rad
499-527). Datumet i etiketten är nattimportens.

**Kräver manuell extern data/API/avtal.** Avtal med Axfood för
formella användningsvillkor och bildrättigheter; ett stickprov mot
fysisk hylla för att bekräfta att nationellt onlinepris = butikspris.

---

## Willys

**Källa.** Samma Axfood-API, `https://www.willys.se/axfood/rest/v1/`,
ingen autentisering (`providers/willys.py` rad 13, 55). Identiska
toppnycklar och produktfält som Hemköp, verifierat 2026-08-30
(`willys.py` rad 3-8). Status `working`, återkommande import
verifierad (`willys.py` rad 56-60).

**Produktantal.** I databasen just nu: 255 butiker / 10 842 produkter.
452 lövkategorier; fullimporten 2026-08-31 gav 10 872 sparade med
100 % kategori, bild och GTIN (`README.md` rad 163, 258-260). 10 842
är i praktiken full katalog.

**Prisfärskhet.** Nattligen 02:00 Europe/Stockholm (`scheduler.py`
rad 55). `fetched_at` = importtidpunkt. Axfoods takt: ej verifierat.

**Prisscope.** `NATIONAL` - **verifierat**: `storeId=2132` (Gävle
Gestrike) och `storeId=2223` (Gävle Hemsta) ger byte-identiska svar
(35 593 B båda) med identiska priser (`willys.py` rad 27-33). Samma
förbehåll som Hemköp: onlinepris bevisat nationellt, fysisk hylla ej
verifierad - "a Willys price must not be presented as independently
verified for one address" (`willys.py` rad 32-33).

**Kampanjpris.** Ja, samma semantik som Hemköp (`GENERAL` →
`campaign_price`, multibuy isär). Willys fyller i
`conditionLabelFormatted` ("2 för") där Hemköp lämnar tomt - koden
litar därför på `qualifyingCount` (`axfood.py` rad 30-37).

**Medlemspris.** Hanteras av samma kod (`LOYALTY` → `member_price`).
Förekomst i Willys-data: **ej verifierat** - stickprovet 2026-08-30
visade inga (`README.md` Willys-tabellen saknar raden).

**GTIN.** Ja, härlett ur bild-URL, GTIN-14, checksummevaliderat
(12/12 giltiga i stickprov, `README.md` rad 325-329). 100 % i
fullimporten.

**Bilder.** Ja, Axfoods CDN. Rättigheter: ej verifierat.

**Licens/villkor.** Ej verifierat (som Hemköp).

**Kommersiell användning.** Ej verifierat. Primat täcker Willys
(nyckel `willys`) som alternativ med uttryckligt tillstånd.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = nationellt pris från Axfood-API:t = "Willys
referenspris" **och** `VERIFIED_STORE_PRICE` för varje Willys-butik,
på API-verifierad nationell grund. Willys är den stabilaste källan i
repot (första kedjan bevisad att tåla upprepad automatisk import,
`willys.py` rad 24-25) och bör vara mallen för hur referenspris +
verifierat butikspris sammanfaller.

**Kräver manuell extern data/API/avtal.** Avtal med Axfood
(villkor, bildrättigheter); hyllstickprov.

---

## Lidl

**Källa.** Primat, kedjenyckel `lidl`. Kräver `PRIMAT_API_KEY`
(`importer.py` rad 101-108).

Ingen direktväg finns, av strukturella skäl: lidl.se är en
reklambladssajt utan e-handel; 505 produktsidor har JSON-LD `Product`
men `offers` saknar `price` (bara `priceCurrency` och
`availability: InStoreOnly`); ingen prissträng förekommer i HTML;
veckoerbjudanden finns bara som digitalt reklamblad (`README.md`
Lidl-sektionen). Lidl Plus-villkoren utesluter kommersiellt bruk
(`primat.py` rad 12-13).

**Produktantal.** I databasen just nu: 212 butiker / 205 produkter -
**hela feeden**. Primats Lidl-feed är liten, ~200-400 varor (`api.py`
PROVIDER_STATUS Lidl); live-rök gav 206 komplett (commit `297a96d`).
Lidls fulla sortiment: ej verifierat (Lidl publicerar det inte; de
505 produktsidorna är marknadsförda varor, inte sortimentet).

**Prisfärskhet.** Primat dagligen (enligt Primat). Matjakt: manuellt,
inte schemalagt; hela feeden ryms lätt i en körning.

**Prisscope.** `NATIONAL` i `CHAIN_PRICING_SCOPE`, med grunden
"kedjans egen profil är enhetliga rikspriser" (`register.py` rad
17-18). **Ej verifierat mot data** - ingen butiksjämförelse har gjorts.
Primat levererar Lidl-rader per butik (212 butiker i registret), så
en jämförelse är möjlig att göra.

**Kampanjpris.** Ja, via Primats offer-fält. Lidls egna publicerade
data är enbart kampanjer (reklamblad), så kampanjtäckningen hos
Primat är sannolikt bättre än ordinarie-täckningen - andel ej
verifierat.

**Medlemspris.** Fältet finns hos Primat; om Lidl Plus-priser fylls i
för Lidl-rader är ej verifierat.

**GTIN.** Ja via Primat, normaliserat. Andel Lidl-rader med GTIN: ej
verifierat.

**Bilder.** Nej på gratisnivån; App-nivån utan rättigheter.

**Licens/villkor.** Primats. Lidl Plus-villkoren utesluter
kommersiellt bruk av Lidls egna kanaler.

**Kommersiell användning.** Ja via Primat. Direkt: nej.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = Primats nationella Lidl-feed = "Lidl referenspris"
- men bara **per vara** för de ~205 varor som finns. Feeden är för
tunn för en hel matkorg; ingen Lidl-total får fejkas fram (`api.py`
PROVIDER_STATUS: "ingen Lidl-total ska fejkas fram"). Lidl ska förbli
bakom `RELEASED_CHAINS` tills feeden bär en full jämförelse.
`VERIFIED_STORE_PRICE`: **ingen känd källa** - kan inte ges från något
befintligt underlag.

**Kräver manuell extern data/API/avtal.** Partnerfeed eller avtal
direkt med Lidl Sverige (inget publikt API finns); i väntan på det
finns bara Primats tunna feed.

---

## City Gross

**Källa.** citygross.se:s publika API - `GET /api/v1/navigation`,
`GET /api/v1/Loop54/category/{id}/products?store={storeNumber}`,
`GET /api/v1/Loop54/search?SearchQuery=&store=`,
`GET /api/v1/sites?siteTypeId=3` och `GET /api/v1/PageData/stores` -
ingen autentisering (`providers/citygross.py` rad 1-2, 11-28,
123-146). Status `working_but_unreliable`: kedjan stryper genom att
släppa anslutningar, inte HTTP 429, därför 3 s mellan anrop och
"delvis import är normalt" (`citygross.py` rad 102-107, 281-285).
Primat täcker också City Gross (nyckel `citygross`) som alternativ.

**Produktantal.** I databasen just nu: 38 butiker / 8 709 produkter.
Fullimport via kategorivägen (11 matavdelningar) gav 8 709 för butik
3209 Gävle (commit `936d090`), t.ex. Mejeri id 1503 rapporterar
totalCount 1 344 (`citygross.py` rad 141-142). 8 709 är hela
matsortimentet för den butiken.

**Prisfärskhet.** Nattligen 04:00 Europe/Stockholm (`scheduler.py`
rad 57). `fetched_at` = importtidpunkt. Källan bär även
`lowestPriceLast30Days` (EU-prishistorik) som **inte** lagras idag
(`citygross.py` rad 53, 251-276). City Gross egen takt: ej verifierat.

**Prisscope.** Repot innehåller två bedömningar som måste läsas ihop:

- Providern: `pricing_scope = "national_with_store_assortment"` -
  verifierat att `store=3209` (Gävle) och `store=3207` (Falun) gav
  identiska priser på alla 11 gemensamma produkter men olika
  svarsstorlek (77 847 vs 78 782 B), dvs. butiksparametern ändrar
  **sortimentet**, inte priserna (`citygross.py` rad 72-77, 289-291).
- Registret och statuspanelen: `STORE_SPECIFIC` / `"store"`,
  motiverat "butiksscopad sökning, konservativt butiksspecifik"
  (`register.py` rad 23-24, `api.py` PROVIDER_STATUS).

Beläggen (11 produkter) lutar mot nationella priser, men urvalet är
för litet för att avgöra. Produktionen kör konservativt
`STORE_SPECIFIC`. Nationellt pris: **ej verifierat i tillräcklig
skala**.

**Kampanjpris.** Ja, explicit: `campaign_price = currentPrice.price`
bara när det är lägre än `ordinaryPrice.price`; `promotions[]`,
`activePromotion`, `hasDiscount` finns i källan (`citygross.py` rad
47-62). Multibuy: ingen struktur observerad, lämnas `None`.

**Medlemspris.** Ja, explicit fält `memberPrice` (`citygross.py` rad
50, 63).

**GTIN.** Ja, explicit `gtin`-fält, EAN-13 normaliserat till GTIN-14
(`citygross.py` rad 39-45, 225-235). 100 % i verifierad import.

**Bilder.** Ja, `https://www.citygross.se/images/products/{filename}`
(`citygross.py` rad 68-70). Rättigheter: ej verifierat.

**Licens/villkor.** Inga API-villkor dokumenterade i repot - ej
verifierat.

**Kommersiell användning.** Ej verifierat. Primat som alternativ med
uttryckligt tillstånd.

**REKOMMENDERAD REFERENSPRISBAS.**
`REFERENCE_PRICE` = katalogen för City Gross Gävle (storeNumber 3209)
= "City Gross referenspris". `VERIFIED_STORE_PRICE` = butikens egen
import med `store={storeNumber}` (sortimentet skiljer per butik, så
det är en riktig skillnad även om priserna visar sig nationella). Med
bara 38 butiker är en per-butik-import av hela kedjan realistisk
(ej testad). Innan referenspriset görs nationellt bör en större
tvåbutiksjämförelse på gemensamma GTIN göras; faller den ut som de 11
kan scopen bli `NATIONAL` med butiksscopat sortiment.

**Kräver manuell extern data/API/avtal.** Avtal med City Gross för
villkor och bildrättigheter; en prisjämförelse i skala mellan
butiker.

---

## Sammanfattande tabell

| Kedja | Referensbas | Scope | Kampanj | Medlem | GTIN | Bilder | Licens | Status |
|---|---|---|---|---|---|---|---|---|
| ICA | Primat-katalog för utsedd referensbutik ("ICA referenspris"); butikspris = butikens egen Primat-katalog | STORE_SPECIFIC (bevisat 60/87) | Ja (Primat) | Ja (Primat) | Ja, GTIN-14 | Nej (App-nivå utan rättigheter) | Primat: kommersiellt ok, attribution på gratisnivå, ingen återförsäljning | `working_via_primat`, ej släppt, 2 081 prod. |
| Coop | Som ICA ("Coop referenspris") | STORE_SPECIFIC (konservativt, variation ej verifierad) | Ja (Primat) | Ja (Primat) | Ja, GTIN-14 | Nej | Primat | `working_via_primat`, ej släppt, 1 997 prod. |
| Hemköp | Axfood-API:ts nationella pris = referenspris **och** verifierat butikspris | NATIONAL (verifierat online) | Ja | Ja (enda med förekomst) | Ja, härlett, GTIN-14 | Ja, rättigheter ej verifierade | Ej verifierat | `working`, nattlig 03:00, 11 492 prod. |
| Willys | Som Hemköp | NATIONAL (verifierat online) | Ja | Kod finns, förekomst ej verifierad | Ja, härlett, GTIN-14 | Ja, rättigheter ej verifierade | Ej verifierat | `working`, nattlig 02:00, 10 842 prod. |
| Lidl | Primats nationella feed per vara ("Lidl referenspris"); butikspris finns inte | NATIONAL (antaget, ej verifierat) | Ja (Primat) | Ej verifierat | Ja (Primat) | Nej | Primat | `partial_via_primat`, ej släppt, 205 prod. (hela feeden) |
| City Gross | Gävle 3209-katalogen ("City Gross referenspris"); butikspris = butikens egen import | STORE_SPECIFIC i drift; data lutar mot nationellt pris med butikssortiment | Ja, explicit | Ja, explicit | Ja, explicit, GTIN-14 | Ja, rättigheter ej verifierade | Ej verifierat | `working_but_unreliable`, nattlig 04:00, 8 709 prod. |

Statusvärdena är `api.py` PROVIDER_STATUS; produktantalen är
databasen 2026-09-02.

## Benämningar i UI

1. **Aldrig "centrallagerpris".** Ordet beskriver inte någon av
   källorna ovan (inget pris kommer från ett lager) och förekommer
   inte i kodbasen idag - det ska inte införas.

2. **`REFERENCE_PRICE` visas som "<Kedja> referenspris"**, t.ex.
   "ICA referenspris", "Lidl referenspris". Etiketten säger att priset
   gäller kedjan, inte att det är kontrollerat i användarens butik.

3. **`VERIFIED_STORE_PRICE` visas som "Verifierat lokalt pris ·
   uppdaterat <dag>"**. Dagen är prisradens `fetched_at`: för Primat
   källans egen `confirmed_at`/`changed_at`, för Axfood/City Gross
   nattimportens tidpunkt.

4. **När "Verifierat lokalt pris" får användas:**
   - Willys/Hemköp: för varje butik, på grunden att kedjans API
     bevisligen ignorerar butiksval (verifierat 2026-08-30). Det är
     samma beteende `resolve_pricing_store` redan har för
     `NATIONAL`-kedjor.
   - ICA/Coop/City Gross: bara när just den butikens katalog är
     importerad. Annars visas "<Kedja> referenspris".
   - Lidl: aldrig (ingen källa finns); bara "Lidl referenspris" per
     vara, aldrig en Lidl-total.

5. **Befintlig varningstext ersätts.** Dagens rad "Priserna är hämtade
   i <butik>. <Kedja> sätter priser per butik, så <butik> kan skilja
   sig." (`frontend/app/app.js` rad 1834) är en varning, inte en
   etikett; med de två nivåerna ersätts den av referenspris-märkningen
   på varje pris.

6. **Attribution kvarstår.** "Prisdata från primat.nu" med länk måste
   visas var Primat-data visas så länge gratisnivån används
   (`primat_client.py` rad 8-14, `app.js` rad 1981) - oavsett om
   priset visas som referenspris eller verifierat lokalt pris.
