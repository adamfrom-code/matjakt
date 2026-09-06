# Datakarta – vilken personlig data Matjakt hanterar, var och varför

*Uppdaterad 2026-09-06. Grund för integritetspolicyn och App Store-etiketterna. Retentionstider i `docs/RETENTION.md`.*

## Principer

- Matjakt samlar in det som behövs för att planera en vecka, jämföra butiker och sköta ett konto. Inget mer.
- Inga tredjeparts-SDK:er, ingen reklam, ingen spårning över sajter. Analytics är egna, namngivna räknare utan identitet.
- Lösenord och sessionstoken lagras bara hashade. Reset- och verifieringstoken likaså.
- Betalkortsuppgifter når aldrig Matjakt – de hanteras helt av Stripe.

## Personuppgifter per lagringsplats

| Uppgift | Var | Varför | Vem ser den | Rättslig grund (förslag, juridisk kontroll krävs) |
|---|---|---|---|---|
| E-postadress | `matjakt.db` → `users.email` | inloggning, verifiering, lösenordsåterställning, kvitto från Stripe | Adam (drift), Stripe (som kund-e-post), Resend (som mottagare) | avtal |
| Lösenord | `users.password_hash`, `users.salt` (PBKDF2-HMAC-SHA256, 200 000 iterationer, 16 byte salt) | inloggning | ingen – hash | avtal |
| Sessionstoken | `sessions.token` (SHA-256 av token), `expires_at` (30 dygn) | hålla användaren inloggad, flera enheter | ingen – hash | avtal |
| Verifierings-/reset-token | `users.verification_token` (hash, 7 dygn), `users.reset_token` (hash, 1 timme) | bevisa adress, byta lösenord | ingen – hash | avtal |
| Synkat tillstånd | `users.synced_state` (JSON) | samma vecka på alla enheter: hushåll, budget, postnummer, ev. position (lat/lon från "Hitta mig"), vald butik, veckans recept, inköpslista, skafferi, favoriter, kostpreferenser, allergener, ogillade råvaror, näringsmål | Adam (drift) | avtal; allergener/kost är känsliga uppgifter i GDPR:s mening – kräver uttryckligt samtycke i policyn |
| Premiumstatus | `users.premium`, `subscription_*`, `stripe_customer_id`, `stripe_subscription_id`, `stripe_event_created` | låsa upp Premium, sköta prenumerationen | Adam, Stripe | avtal |
| Provperiodsfält (`trial_*`) | `matjakt.db` | historik för två gamla konton; ingen ny trial ges | Adam | – (utfasas) |
| Feedback (fritext + skärm) | `matjakt.db` → `feedback` | produktförbättring; ingen koppling till konto | Adam | berättigat intresse |
| Klient-IP | bara i processminne för rate limit (`services/accounts/ratelimit.py`); Renders åtkomstlogg | skydd mot missbruk | Render, Adam | berättigat intresse |
| Analytics-händelser | `prices.db` (KV-cache) – bara räknare per händelsenamn (`view_home`, `cta_logga_in` …) | förstå användning | Adam | berättigat intresse; ingen identitet |
| Serverlogg | Render (stdout) | felsökning | Adam | berättigat intresse; innehåller e-post vid vissa varningar (verifieringsmejl), aldrig lösenord/token/nycklar |

### Hos tredje part

| Part | Data | Varför | Avtal/plats |
|---|---|---|---|
| Stripe (Irland/USA, DPF) | e-post, kund-id, prenumeration, betalkort (aldrig hos oss) | betalning | Stripes DPA; Stripe är personuppgiftsbiträde för kortdata, självständigt ansvarig för bedrägeriskydd |
| Resend (USA, EU-region valbar) | e-post, mejlinnehåll (verifierings-/återställningslänk) | transaktionsmejl | Resends DPA – välj EU-region för domänen |
| Render (USA, region Frankfurt valbar) | all serverdata | drift | Renders DPA |
| GitHub Pages | inga personuppgifter (statiska filer); IP i GitHubs loggar | frontend-hosting | GitHubs villkor |
| Loopia | inga användardata | DNS | – |
| Primat, Dabas, Axfood, City Gross | inga användardata – bara produkt- och prisdata hämtas | prisunderlag | respektive villkor |
| Pexels | inga användardata – receptbilder hämtas av servern | bilder | Pexels-licens |

## Vad som INTE samlas in

- Inga betalkortsnummer, inga personnummer, inga namn (bara e-post).
- Ingen platshistorik: "Hitta mig" sparar en position i profilen tills användaren byter postnummer.
- Ingen enhetsidentifierare, inga reklam-id, inga cookies utöver `localStorage` för egen sessionstoken och lokalt tillstånd.

## Användarens rättigheter – hur de uppfylls i dag

| Rättighet | Hur |
|---|---|
| Radering | "Radera konto" i appen: sessioner, konto och synkat tillstånd raderas; Stripe-prenumerationen sägs upp först och Stripe-kunden raderas (`POST /api/auth/delete-account`) |
| Tillgång/export | Synkat tillstånd hämtas som JSON via `GET /api/account/state` med sessionstoken. En knapp i UI saknas – se `docs/RETENTION.md` |
| Rättelse | E-post kan inte bytas i UI ännu; lösenord kan bytas |
| Invändning mot analytics | Räknarna bär ingen identitet – inget att invända mot per person |
