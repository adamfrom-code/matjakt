---
paket: AA1
titel: Rester — kokta minus ätna, en dag i taget (grunden, bakom vecka.rester)
---

Roadmapens AA: ingen restportion fanns. `src/services/rester.js` räknar
vad som blir över när färre äter än det lagas för — listan och priset
räknas för hela hushållet, T1 vet hur många som äter hemma per dag, och
skillnaden är rester: `over = kokta − ätna`, förda till **nästa** dag och
inte längre. `resterDagar()` pekar ut dagar där gårdagens rester räcker
till alla som äter (kandidater för en "resterdag"); `resterText()` säger
"2 portioner över" eller "Rester från igår räcker".

Ingen gissning om hållbarhet eller om vad som brukar bli över. Modulen
rör inget tillstånd och ritar inget; AA2 kopplar den till Veckan bakom
flaggan `vecka.rester` (och till planeraren när T2 låter prissättningen
räkna per dag).
