---
paket: T5b
titel: En veckomutation tömmer hela prisbilden — även de låsta kedjorna
---

`clearPriceSnapshots` tömde livepriser, totaler och jämförelsen vid varje
veckomutation men lämnade `dbLockedChains` kvar. Butikskorten ritas ur
båda: när "Skapa min vecka" tömde totalerna stod förra svarets två låsta
kedjor ensamma kvar, och korten ritades ur resterna — två hänglås och
inget öppet kort — tills den nya prissättningen landat. På en lastad
CI-maskin var det bildrutan G8-testet läste (`2 != 0`); din E2E-session
(T5) fann orsaken och lämnade produktfixen hit.

Rensningen bor nu i `src/state/app-state.js` (`clearPriceSnapshots`),
tömmer låsen med, och prövas i node; `app.js` delegerar. Ett lås är ett
löfte om att Premium visar ett pris — ett lås utan den hämtning det hörde
till lovar ingenting.
