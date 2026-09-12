# Matjakt — vägen till lansering

Ett dokument. Ersätter inte `UPPDRAG-MATJAKT.md` — det är **kartan över vad
som återstår** av det. Mätt mot `origin/main` 2026-09-12. 62 paket mergade,
30 kvar.

## 0. Arbetsordningen gäller fortfarande

Från `UPPDRAG-MATJAKT.md` §0, oförändrad: fråga inte, varje beslut här är
fattat, det som är märkt **ADAMS BESLUT** hoppas över. En agent = ett paket =
en gren = en PR. **Zonregeln vinner över bedömningar av vad som "nog går bra
ihop"** — två paket i samma zon körs aldrig samtidigt.

Nya zoner i det här dokumentet: `Z-RECEPT`.

## 1. ICA upp — gör det först

D11 är färdigbyggd och ligger omergad på `paket/D11-ica-rikstackande`. Elva
filer, 74 rader nya tester, en changelog som förklarar varför. Den behöver
bara mergas.

**Vad den gör:** ICA hade den största katalogen av alla kedjor — 19 703
produkter, 18 990 priser — och var osynlig för kunder. Den kan inte släppas
som Willys och Hemköp, för de är centralt prissatta medan ICA är handlarägt
och priserna skiljer sig bevisat mellan butiker. Att hålla alla 463 aktiva
ICA-butiker butiksverifierade tar 91 dygn på dagens Primat-kvot, och då är
priserna 23 gånger för gamla.

Så ICA släpps på **referensnivå**: ett riktpris på kedjenivå ur Maxi ICA
Stormarknad Gävle, publicerat som `REFERENCE_PRICE`. Varje ICA-butik i landet
blir prissatt, och korgen märks `reference` så kunden ser vad "Billigast"
vilar på. Motorn säger "ungefär så här" i stället för att låtsas veta.
Uppgraderingsvägen finns: en ICA-handlare som tecknar partneravtal får
`VERIFIED_STORE_PRICE` för sin butik genom `partner_feed`.

**Ett verkligt fynd i samma paket:** stale-gränsen låg på 27 h, räknad när
bara tre kedjor var släppta. ICA kör 05:30 och en utebliven natt är bara
26,0 h gammal vid driftkollen 07:30 — den hade alltså inte upptäckts förrän
nästa morgon, vilket är precis det D4 byggdes för att förhindra.

Men fönstret blev trångt: under 25 h larmar en kedja som fungerar. Den rena
lösningen är att flytta ICA till **04:30** i schemat. Det ger 27,0 h och
gränsen kan gå tillbaka till 26 h med en timme åt båda håll.

**Gör:** merga D11. Flytta ICA till 04:30. Verifiera i produktion att
`RELEASED_CHAINS` svarar med fyra kedjor och att en ICA-korg märks
`reference`.

## 2. Det som återstår, i ordning

### Kedja 1 — `Z-GROCERY` (kan börja nu)

| Paket | Vad |
|---|---|
| **D11** | ICA släppt. Ligger klar. |
| **D10** | Backup-ålder i `/api/health` och som larmvillkor, återställningstest i CI, **canary per kedja** — ett känt GTIN med känt prisintervall efter varje import. Billigaste möjliga upptäckten av att en sajt ändrat sig. |
| **C11** | Fyndrankningen. Spec i `docs/PAKET-C11-fynd.md`. Rankar på sparade kronor × receptspridning i stället för rabattdjup, tak två per kategori, `recipeIds` i svaret. Utan den är Kampanjtorget en glasslista. |

### Kedja 2 — `Z-RECEPT` (ny zon, kan börja nu, krockar med ingen)

Spec: `docs/VAG-M-receptbanken.md`.

| Paket | Vad |
|---|---|
| **M1** | `mealType` på alla 240 recept. Roten till att risgrynsgröt hamnar i en middagsvecka — inget fält säger idag vad en rätt är till för. Veckoplaneraren filtrerar på middag. |
| **M2** | 31 recept utan bild. Kritiskt sedan design D valdes: Ikväll är ett helbleed-foto. Reservkort för dem som inte får foto — aldrig en grå ruta. |
| **M3** | Sex ingredienser utan mängd: ägg, vetemjöl, lök, socker, ättika, nio vitlöksrader. |
| **M4** | `categories` och `tags` gör samma jobb med olika versalisering. `Kött` mot `kott`. |
| **M5** | Två soppor på 6–7 g protein som huvudrätt. |

**M1 först och ensam, M2 parallellt, resten efter.**

### Kedja 3 — `Z-FRONT-CORE` / `Z-FRONT-VIEW` (efter F)

| Paket | Vad |
|---|---|
| **E16** | Kontosynken skriver över det användaren just gjort — budgeten, veckan, den betalda prisbilden. Ligger klar på gren. **Merga före allt annat i kedjan.** |
| **F6** | `legacy-catalog.js`. Kräver F3 + F4, båda mergade. |
| **G3** | Hela veckan synlig — `week-plan-section[hidden]` bort. |
| **G6** | Modaler: fokusflytt, fokusfälla, Escape, `inert` bakom. Idag finns **en** Escape-lyssnare i hela appen. |
| **G7** | "Skapa min vecka" ska skapa en vecka, inte öppna ett formulär. |
| **G9** | Postnummer blir valfritt i onboarding. |
| **G10** | Byten med ett tryck, obegränsat. |
| **G11** | Inställningsskärm. |
| **G12** | `alert()`/`confirm()` bort, "Visa alla" blir en riktig fyndlista. |

### Kedja 4 — våg L, skärmarna (efter kedja 3)

Spec: `docs/VAG-L-skarmarna.md`. **L0 är mergad.** L1–L7 kan köras parallellt
av sju agenter, en per vy, med `docs/matjakt-design-D.html` som facit. L8
sist, L9 före L1–L7.

Det här är den våg som faktiskt bygger design D. **G-vågen målade om den
gamla appen; L bygger skärmarna.**

### Kedja 5 — `Z-BILLING`

| Paket | Vad |
|---|---|
| **J2** | Premiumlistan lovar saker som redan är gratis. Jämförelsetabell med bara sanna rader. |
| **J3** | Ny paketering. Grandfathering krävs, plus en regel för vad som händer när ett gammalt gratishushåll med fler än två medlemmar bjuder in en till. |
| **J4** | Entitlement vid `onAppResumed` och efter Stripe-portalen. |
| **J5** | Dunning, `past_due` med sju dagars respit, återbetalning, byte av e-post, avstämningsrutin. |
| **B2b** | Larm när en betalande kund har adress utanför Sverige (OSS). Kort paket, sist i kedjan. |

### Kedja 6 — våg H, retention

**Ingenting av H är byggt. Noll paket.** Det är den enda vågen som inte rört
sig alls, och den avgör om lanseringen betyder något.

| Paket | Vad |
|---|---|
| **H1** | Söndagsnotisen. Push i `sw.js` + backend-schema. Söndag 17:00: *"Dags att planera veckan. 5 middagar för 4 personer — förslaget är redan klart."* |
| **H2** | Sparkvittot efter handlingen. *"Ni har sparat 612 kr sedan i september."* |
| **H3** | Veckohistorik — `state.weekHistory` sparar redan tolv veckor och visas ingenstans. |
| **H4** | Delbar sparbild, 1080×1080. |
| **H5** | Hänvisning kopplad till Premium. Villkorad på `vecka_skapad`, inte på registrering. Bygg efter J3 och med belöningens längd som **en konstant på ett ställe**. |

## 3. Lanseringsgrinden — vad som måste vara sant

Appen är idag mätbart bättre och **fortfarande inte värd att lansera brett**.
Inte för att något är trasigt, utan för att det inte finns någon anledning att
öppna den en andra gång. Ingen notis. Ingen veckorytm. Sparsumman syns först
när man letar. Ingen delning. H-vågen är noll paket.

En lansering mot en app utan retention betyder att du bränner din enda
första-gången-publik på en produkt som inte kan behålla dem. Lanseringsmåttet
i `CHECKPOINT.md` säger det själv: 100 personer som planerat en vecka, 10
tillbaka vecka två, 1 betalande. Tio procent tillbaka är optimistiskt utan en
enda krok.

**Minimum innan du berättar för någon:**

1. **D11** — ICA. Utan Sveriges största kedja är prisjämförelsen inte trovärdig för de flesta.
2. **M1 + M2** — inga frukostar i middagsveckan, inga grå rutor där maten ska vara.
3. **H1** — söndagsnotisen. Den enda rytm produkten har.
4. **H2** — sparkvittot. Den enda siffran som gör en budgetapp värd att komma tillbaka till.
5. **L1 + L2 + L3** — Ikväll, Veckan och Handla som i design D. De tre skärmar en användare faktiskt är i.
6. **J2** — premiumlistan slutar ljuga.
7. Dina fyra punkter i §4.

**Kan vänta till efter:** L4–L7, G6/G9–G12, H3–H5, J5, C11, D10, M3–M5, F6,
L8. Alla är riktiga förbättringar. Ingen av dem avgör om någon kommer tillbaka
på tisdag.

**Ett mjukt släpp först.** Tjugo personer du känner, en vecka, innan något
publiceras brett. Kontrollrummet mäter redan tratten per registreringsvecka —
registrerade → skapade en vecka → tillbaka efter sju dagar → Premium. Tjugo
personer ger dig den kurvan på riktigt, och det är billigare att upptäcka ett
hål med tjugo än med tusen.

## 4. ADAMS BESLUT — det ingen agent kan göra

1. **Git-historiken.** Kontodatabasen med e-post och lösenordshashar låg i ett publikt repo 31 aug–7 sep. `git filter-repo` kräver force-push. Bedömningen av anmälningsplikt enligt GDPR art. 33 kräver dig: 198 användarrader, varav 11 adresser inte ser ut som testkonton. **Detta är den enda punkten med en rättslig tidsfrist.**
2. **Stripe.** Legal entity på Adam From, 199511045651. Stripe Tax på med svensk momsregistrering. Kvitton på. Koden slår på sig själv i samma sekund du är klar. Stegen står i `docs/RELEASE.md`.
3. **Biträdesavtal** hos Render, Stripe och Resend. Några klick per leverantör. Från I3 står ditt namn som personuppgiftsansvarig.
4. **Support-adressen.** `adamfrom@icloud.com` står nu på landningssidan, i policyn och i villkoren. Fungerar, men GDPR ger dig en månad att svara på ett raderingsärende och de mejlen hamnar nu i din privata inkorg. En vidarebefordran från `support@matjakt.store` hos Loopia tar två minuter.

## 5. Sammanfattning i tre rader

**Klart:** 62 paket. Betalningen är säker, priserna stämmer, driften larmar,
deployordningen är rätt, landningssidan är uppe, juridiken är ifylld, appen
har bytt palett.

**Nästa:** D11 idag. Sedan M1–M2 och H1–H2 parallellt med att L bygger
skärmarna.

**Inte än:** lansera brett. Appen är bra men har ingen anledning att öppnas
två gånger, och det är fem paket bort.
