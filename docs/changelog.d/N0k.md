---
paket: N0k
titel: Integritetsmanifestet beskriver det appen faktiskt samlar in
---

`PrivacyInfo.xcprivacy` deklarerade **exakt plats** som insamlad och kopplad
till användaren. Den är ingetdera: *Hitta mig* ger koordinater till
`state.position`, som används till avståndsberäkning och sedan nollställs —
den ingår inte i `buildSyncPayload()`, och kontotabellen har ingen
lat/lon-kolumn. Koordinaterna lämnar aldrig telefonen.

Att överdeklarera är inte den säkra sidan. Det ger *"Precise Location —
linked to you"* på butikssidan, och det motsäger integritetspolicyn som
(korrekt sedan I3) säger att positionen inte sparas. Apple jämför manifest,
etikett och policy mot varandra.

Två saker som verkligen samlas in saknades: **produktinteraktion** (namngivna
händelser räknas per konto och dygn) och **hälsouppgifter** (allergier ligger
i hushållsprofilen på servern och styr vilka recept som får föreslås — GDPR
artikel 9).

Testerna läser koden, inte manifestet mot sig självt. Börjar positionen
synkas, eller slutar allergierna lagras, faller de och pekar på manifestet.
