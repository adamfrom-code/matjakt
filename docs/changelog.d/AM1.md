---
paket: AM1
titel: Boot, inloggning och uppvaknande delar en spärr mot /api/entitlements
---

Mätt i webbläsaren mot dev-servern: appens första sekund skickade
`/api/entitlements` **två gånger**. Modulens sista rad (boot) och
`refreshUser()` (kontot) anropade `fetchEntitlements()` var för sig, innan
något av dem svarat. J4:s spärr fanns — men bara uppvaknandet gick genom
den; boot och inloggning gick förbi.

`refreshNow()` är samma `run()` som uppvaknandet använder: ett anrop i
luften delas av alla som frågar. Båda direktanropen i `app.js` går nu den
vägen, och ett källtest vägrar att ett nytt direktanrop smyger in.
