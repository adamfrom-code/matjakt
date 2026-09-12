---
paket: B2b
titel: Momskontrollen läste priserna men aldrig kunderna
---

B2 kontrollerade prisobjekten (`tax_behavior: inclusive`) och kontots
skatteinställningar (Stripe Tax aktivt). Den läste aldrig **kundernas
adresser**.

Prenumerationen går att köpa från vilket EU-land som helst, och då gäller
köparlandets momssats via One Stop Shop. Stripe Tax räknar rätt sats av sig
självt — men OSS-registreringen görs hos Skatteverket, och den finns inte
förrän någon gjort den. Utan den här kontrollen hade den första tyska kunden
varit osynlig tills en granskning hittade henne, med retroaktiv moms i ett
land vi inte var registrerade i.

`/api/admin/stripe-check` frågar nu Stripe vilka **betalande** kunder som har
en adress utanför Sverige, och larmar på den första. Sammanfattningen — länder
och antal, aldrig kundlistan, för den bär e-postadresser — ligger också i
`/api/health`, som de andra Stripe-kontrollerna.

Tre beslut som är medvetna:

**Bara betalande kunder räknas.** En avslutad prenumeration i Tyskland är
ingen pågående OSS-skyldighet. Statusmängden är densamma som avstämningen i B1
använder.

**Okänd adress är inte ett larm.** Vi kan inte påstå att en kund är utländsk
för att fältet är tomt. Den räknas i `unknownCountry` i stället — en växande
siffra där betyder att `customer_update[address]=auto` inte fungerar, och det
är en annan sak att åtgärda.

**Larmet gör kontrollrummet gult, inte rött.** Momsen blir rätt ändå; det som
saknas är en registrering. `ok` fortsätter handla om konfigurationen, och
skillnaden syns på statuskoden: 200 när allt är svenskt, 409 när någon inte
är det, 502 när konfigurationen faktiskt är trasig.

Landet läses ur tre källor i sanningsordning: kundens faktureringsadress,
leveransadressen (för kunder skapade före B2), och sist Stripes egen
`tax.location` — den bedömning som faktiskt avgjorde momssatsen på fakturan.

Ett nätfel mot Stripe larmar inte. Det är inte en tysk kund, och svaret säger
att kontrollen inte kördes i stället för att låtsas att listan är tom.
