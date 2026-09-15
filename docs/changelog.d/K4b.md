---
paket: K4b
titel: Rökprovet skiljer på driftfel och lanseringshinder
---

Ett rött rökprov mot produktion utlöser automatisk rollback. Men rollback
kan bara laga det som föregående kod gjorde rätt — och Stripe i testläge
fällde provet på en **frisk** release. Med rollbacknycklarna på plats hade
en fungerande backend kastats tillbaka för att betalningarna ännu inte var
live.

Proven är nu två sorter. **DRIFT** — backend nere, fel commit, recipes
trasig, authgräns bruten, adminväg exponerad, prisplattform helt av — ger
exit 1 och rollback. **LANSERING** — Stripe i testläge, prisauditen
`RÖD`/`INGEN DATA`/`FEL` — syns som `::warning:: NOT LAUNCH READY` men ger
exit 0. Orsaken är data eller konfiguration, inte koden som deployades.

Och en bugg: provet jämförde prisauditens gate mot `"red"`, testet skickade
`"red"` och `"green"` — värden ingen kod producerar. Produktionen stod på
`RÖD` och provet sa OK. Nu används de riktiga värdena `GRÖN`, `RÖD`,
`INGEN DATA`, `FEL`, ett okänt värde är aldrig grönt, och en spärr fäller
varje jämförelse mot ett engelskt ord.

Ingen ändring i `ci.yml`: rullbackjobbet lyssnar på exitkoden, och
exitkoden bär nu skillnaden.
