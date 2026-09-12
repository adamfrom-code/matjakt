# Retention – hur länge Matjakt sparar vad

*Uppdaterad 2026-09-06. Hör ihop med `docs/DATA_MAP.md`. "Automatiskt" = koden gör det; "manuellt" = kräver ett beslut.*

| Data | Sparas | Rensas | Hur |
|---|---|---|---|
| Konto (e-post, lösenordshash, synkat tillstånd) | tills användaren raderar kontot | vid radering | automatiskt, `delete_account` |
| Sessionstoken | 30 dygn från inloggning | utgångna rader raderas vid nästa inloggning | automatiskt, `_create_session` |
| Verifieringstoken | 7 dygn | vid verifiering eller ny token | automatiskt |
| Reset-token | 1 timme | vid användning eller ny begäran | automatiskt |
| Stripe-händelse-id (`stripe_events`) | tills vidare | – | manuellt: tabellen är liten (en rad per webhook); rensa rader äldre än 90 dygn vid behov |
| Stripe-referenser på kontot | så länge kontot finns | vid radering (kunden raderas hos Stripe) | automatiskt |
| Inaktiva konton | tills vidare | – | **beslut saknas**: förslag 24 månader utan inloggning → mejl → radering efter 30 dygn. Kräver SMTP och en policytext |
| Web Push-prenumeration (`push_subscriptions`) | så länge kontot finns och veckonotisen är påslagen | vid utloggning, vid avstängd veckonotis, vid raderat konto, och när push-tjänsten svarar 404/410 | automatiskt, `services/push/store.py` |
| Skickade veckonotiser (`push_log`) | tills vidare | – | manuellt: en rad per konto och söndag; rensa rader äldre än 90 dygn vid behov. Raden bär ingen text och inget klockslag, bara att notisen gick ut |
| Feedback (fritext) | tills vidare | – | manuellt; förslag 12 månader |
| Analytics-räknare | tills vidare, utan identitet | – | inget personuppgiftsskäl att rensa |
| Rate limit-räknare | i processminne, max 1 timme | vid omstart | automatiskt |
| Serverlogg | Renders logglagring (7 dygn på starter-planen) | av Render | automatiskt |
| Backupset på servern | 7 dygn | äldre set rensas nattligen | automatiskt, `services/backup.py` |
| Off-site-backup | 30 dygn (`--keep 30`), månadskopior 12 | av `pull_backup.py` | automatiskt/manuellt, se `docs/BACKUP.md` |
| Prisdata, produkter, butiker | inga personuppgifter | prishistorik växer; ingen rensning | manuellt vid behov |
| Testkonton (`*@example.com`) | – | e2e-skripten städar sina egna | automatiskt |

## Radering i praktiken

När ett konto raderas försvinner det ur `matjakt.db` direkt. Det finns kvar i backupset upp till 7 dygn på servern och upp till 30 dygn off-site; det ska stå i integritetspolicyn. En återställning från backup skulle återskapa raderade konton – efter en återställning ska raderingsbegäranden från perioden efter backupens stämpel köras om (loggen visar `delete-account`-anrop).

## Öppna beslut för Adam

1. Retention för inaktiva konton (förslag ovan).
2. Retention för feedback-fritext.
3. Om `trial_*`-kolumnerna ska tas bort när de två gamla provperioderna gått ut (se `services/accounts/store.py`).
