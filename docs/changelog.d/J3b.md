---
paket: J3b
titel: Ingen automatisk trial — aktiveringstrialen borttagen, signalen kvar
---

Affärsbeslut 2026-09-19: **ingen automatisk trial**, varken vid
registrering (borta sedan 2026-08-31) eller efter första skapade veckan
(J3:s sju dagar). Premium är Free / Premium månad / Premium år.

`ACTIVATION_TRIAL_DAYS` och `AccountStore.grant_activation_trial` finns
inte längre; `on_first_week` bär bara signalen som hänvisningskroken (H5)
hänger på. Trialer som redan delats ut läses tills de löper ut — ingen
demoteras av en refaktor, men ingen ny kan skrivas: metoden som skrev dem
är borta, och regressionsvakten
`TheActivationTrialIsGone.test_nothing_in_the_code_can_write_a_trial`
faller på konstanten, metoden eller en `UPDATE` som sätter `trial_ends_at`
till något annat än `NULL`.

Reviewnoterna nämner ingen gratisperiod längre (test: inga fraser om
trial/provperiod/introductory offer). `docs/IAP_COMPLIANCE.md` bär beslutet
där frågan ställdes (A6, BLOCKED – ADAM 10 → svar C).
