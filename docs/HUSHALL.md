# Hushåll, delning och notiser

Skriven 2026-09-06. Beskriver vad som FINNS, inte vad som är tänkt. Allt
under "Förberett men inte byggt" är arkitektur utan funktion - det står
här så nästa pass inte bygger om det, och så ingen tror att det redan går.

## Modellen

Fyra saker hålls isär, och blandas de ihop går prisjämförelsen sönder (§32
i uppdraget):

| Begrepp | Vad det är | Var det bor |
|---|---|---|
| ingredient | receptets behov, "mjölk 5 dl" | receptbanken |
| product | en riktig vara i en butik, "Arla Mellanmjölk 1,5 l" | `grocery_products` |
| inventory item | vad hushållet har hemma, "ca 1 liter, i kylen" | `inventory_items` |
| shopping list item | vad som ska handlas, "0 - vi har den" | `shopping_items` |

Ett shopping item **pekar på** en produkt (en ögonblicksbild för visning).
Det **är** inte produkten, och snapshotet får aldrig påverka prissättning:
priset räknas alltid av prismotorn ur den egna databasen.

## Ett hushåll äger

Vecka (`household_docs.week`), inköpslista, skafferi/kyl/frys, hushållets
inställningar och basvaror. Medlemmarna delar allt detta. Personligt inuti
hushållet är bara profilen: visningsnamn, kosttyp, styrka, allergier.

En användare hör till **högst ett** hushåll. Två hushåll hade betytt två
veckor, två listor och ett val i varje vy - precis den administration
appen ska ta bort.

## Behörighet

`household_id` kommer **aldrig** från klienten. Det slås upp ur sessionens
användar-id (`AccountStore.identity_for_token` →
`HouseholdStore.household_id_for_user`), så det finns ingen parameter att
manipulera. `_require_member` är den enda dörren till hushållets data.

Den som inte är medlem får **404, inte 403** - ett 403 hade svarat på
frågan "finns det här hushållet?".

Radernas id är globala i tabellerna. Varje uppslag filtrerar därför på
hushållet, så att känna till ett id från ett annat hushåll räcker inte.
Detta testas i `HorizontalEscalationTest` (lagret) och
`HorizontalEscalationApiTest` (över HTTP).

## Inbjudan

`POST /api/household/invite` (admin) ger en engångslänk som gäller 72
timmar. Token:en returneras **en gång**; databasen håller bara SHA-256 av
den. `GET /api/household/invite?token=...` är den enda vägen som fungerar
utan inloggning, och den lämnar bara ut hushållets namn och vem som bjöd
in - aldrig veckan, listan eller skafferiet.

En medlem som tas bort får sina öppna inbjudningar återkallade, så
bakvägen in stängs samtidigt som framdörren.

## Statusmodellen

`NEED_TO_BUY` · `ALREADY_HAVE` · `PURCHASED` · `REMOVED`

"Köpt" och "har hemma" är **inte** samma sak: den som redan hade ketchup
har inte köpt något och får inte räknas som ett köp. Båda tar bort raden
ur det aktiva behovet; bara `PURCHASED` är ett köp.

En statusändring **raderar aldrig raden** - den byter status och behåller
sitt id, så "Ångra" alltid har något att gå tillbaka till.

`POST /api/household/shopping/at-home` gör två saker i ett anrop: sätter
statusen och lägger varan i skafferiet. Svaret bär en `undo`-beskrivning
som säger om skafferiraden **skapades** av handlingen. Bara då tar en
ångra bort den igen - familjens riktiga ketchup ska inte försvinna för att
någon tryckte fel i Handla.

## Synk

En räknare per hushåll (`households.revision`). Varje skrivning ökar den
och stämplar den ändrade **raden**. Klienten frågar
`GET /api/household/sync?since=N` och får bara de raderna.

Två personer i samma butik kan därför ändra varsin vara utan att den enes
svar skriver över den andres lista. Klienten avvisar dessutom rader med
äldre revision än den redan har, så ett fördröjt svar i mobilnätet inte
kan backa ett "köpt" till "behöver köpa".

Hämtningen sker när appen är synlig (20 s), efter varje egen ändring, och
när telefonen kommer tillbaka från bakgrunden. **Ingen WebSocket** - se
§25: enklaste robusta lösningen, inte den coolaste tekniken.

## Notiser

Ett gemensamt eventlager i `services/household/notifications.py`, med
samma modell för PWA idag och Capacitor/APNs/FCM sedan. Backend avgör vem
som ska veta och formulerar texten; transporten är ett utbytbart sista
steg.

Händelser: `household.shopping_item_added`, `...item_purchased`,
`...item_at_home`, `...inventory_changed`, `household.week_changed`,
`household.week_ready`, `household.member_joined`, `household.price_drop`.

Tre regler:

1. **Aldrig till den som gjorde ändringen.**
2. **Debounce 20 s + gruppering.** Tio varor blir "Sara lade till 10 varor
   i inköpslistan", inte tio pushar.
3. **Användaren bestämmer.** Fem kategorier plus en huvudbrytare, under
   Konto → Hushåll → Notiser.

`household.member_joined` ligger avsiktligt utanför de fem kategorierna:
den är sällan och viktig, och bara huvudbrytaren stänger av den.

Säkerhet: push-token lagras hashad, byter ägare när ett nytt konto loggar
in på samma enhet, glöms vid utloggning (`deviceToken` följer med
`POST /api/auth/logout`), och köade notiser om ett hushåll städas när
någon lämnar det.

## Vad som händer med data

| Handling | Personlig data | Gemensam hushållsdata |
|---|---|---|
| Medlem lämnar | medlemsrad + profil raderas | stannar hos de andra |
| Admin tar bort medlem | samma | stannar |
| Sista medlemmen lämnar | raderas | raderas med hushållet |
| Konto raderas | medlemskap, profil, notisinställningar, enheter | stannar hos de andra |

## Förberett men inte byggt

### Köp hela listan (§22)

`services/grocery/cart.py`. Fyra nivåer i fallande ordning:
`FULL_CART_API` → `BULK_LIST_IMPORT` → `PRODUCT_DEEPLINK` →
`STORE_HOMEPAGE_FALLBACK`.

**Status: ingen kedja har en avtalad väg in.** `PROVIDERS` är tomt med
flit, och `capability_for()` svarar `STORE_HOMEPAGE_FALLBACK` för alla -
det testas i `test_cart.py` så en provider inte kan glida in obemärkt.

Inga DOM- eller browser-hack. En layoutändring hos butiken dödar sådant, och
för butiken ser det ut som automatiserad trafik. Willys är tänkt POC när
frågan om villkor är löst.

`HandoffResult.unmatched` är obligatorisk: en överföring som tappade sex av
tjugo varor **måste** säga vilka. En tyst tappad vara är värre än ingen
överföring.

### Kvittoskanning (§21)

Inte byggd. Flödet ska bli: fota → identifiera produkter → matcha mot
GTIN/produkt → registrera faktiskt pris → föreslå att varorna läggs i
skafferiet. Osäkra matchningar **ska bekräftas av användaren** innan de
rör prisdatabasen; en OCR-gissning får aldrig bli ett verifierat pris.

Delarna som redan finns och ska återanvändas: `item_key()` (GTIN-först),
`upsert_inventory_item` och produktögonblicksbilden.

### Prisbevakning (§19)

`state.foljdaVaror` finns i appen och händelsen `household.price_drop` med
inställningen `price` finns i notislagret. Det som saknas är jobbet som
jämför dagens pris mot historiken och avgör vad "faktiskt bra pris"
betyder. Bygg inte notissystemet igen - publicera bara händelsen.

### BankID (§23)

Bygg inte. Matjakt kräver ingen juridisk identifiering för sina
kärnfunktioner. Prioritetsordning för inloggning: e-post (finns),
Apple-inloggning, Google-inloggning. BankID dokumenteras här som en
möjlighet om ett faktiskt användningsfall uppstår - inte som en plan.

## Release-härdning 2026-09-06

Vad som verifierades innan hushållet gick vidare mot release, och vad som
hittades på vägen.

**Trasig ramning tappade sitt svar.** När `Content-Length` inte gick att
tolka lästes kroppen aldrig, och anslutningen stängdes med den datan kvar i
mottagningsbufferten. Windows skickar RST i stället för FIN i det läget, och
en RST kastar bort svaret även när det redan lämnat servern - ~1 av 30
begäranden fick aldrig sitt 400. `ApiHandler._abandon_body` tömmer bufferten
och markerar anslutningen för stängning innan svaret går ut.

**Fem recept-id kunde planeras men aldrig öppnas.** `chili`, `fiskgratang`,
`kottbullar`, `kycklingwok` och `lax` fanns i klientens medföljande bank men
i inget av backendens 241 recept. Alla fem mappades till motsvarigheten med
samma rätt. `test_recipe_identity.py` är grinden: varje id i den
medföljande banken måste finnas i den canonical banken.

**404-loopen.** `loadRecipe` svalde alla fel och gav `null`, så ett
permanent "finns inte" gick inte att skilja från ett nätfel - och anroparen
försökte om på varje omritning. Nu är `null` definitivt och frågas aldrig om
igen; nätfel kastas vidare och släpper id:t fritt.

**Prisgaten var röd av fel skäl.** Auditen flaggade 317 rader som "kilopris
visat som paketpris". Samtliga hade `perKg=True` - motorn hade räknat
kr/kg × behovet, alltså rätt. Regeln undantog `weightPriced` men inte
lösviktsvägen som kom senare. Med undantaget på plats: **gate GRÖN**,
4 614 kontroller mot 17 849 riktiga produkter. Auditen vägrar numera köra
mot en tom prisdatabas - "0 kontroller, allt grönt" är ingen granskning.

**Spärr på varje utgående anrop.** Stripe och SMTP var spärrade; de sex
providervägarna var det inte, och ett brett test hittade dessutom
receptbilds- och videonedladdningen. `guard_outbound_http` släpper förbi en
redan utbytt `urlopen` men stoppar en glömd mock. Ett test letar igenom hela
`services/` så nästa provider som glömmer spärren fastnar direkt.

**En patchläcka mellan testfiler** täpptes till: en klass i
`test_citygross_provider.py` patchade `urlopen` utan tearDown, så fejken låg
kvar resten av sviten.

Testtäckning efter passet: **1069 backend-tester** och **103 node-tester**,
körda två gånger i rad med produktionsdatabaserna verifierat orörda
(sha256 före/efter). Två-telefonersplanen ligger i
`docs/TVA_TELEFONER_TEST.md`.

## Premium

Ingen ny funktion i det här passet är Premium-låst. Familjedelning är
avsiktligt fri: den är lätt att använda och hjälper spridningen (§27-§28).
Entitlement-systemet (`services/accounts/features.py`) finns kvar, så ett
senare beslut om t.ex. större hushåll är en rad i `FEATURES` - inte en
omskrivning. **59 kr/mån och 399 kr/år är oförändrade.**
