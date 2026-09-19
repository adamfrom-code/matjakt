---
paket: AN2
titel: Reservbanken förhandscachas — recepten finns offline
---

Reservbanken (`data/recipes.json`, 230 recept, ~90 KB gzippat) är vad
appen visar när backenden inte svarar — men offline hade den aldrig
hunnit cachas: den hämtas först när API:t redan fallit. Service workern
förhandscachar den nu vid install, under skalets versionerade cache
(`CACHE_NAME` ur bygget), så en ny receptbank följer med nästa bygge och
den gamla städas vid activate — ingen stale bank som låtsas vara färsk.
Misslyckas hämtningen installeras skalet ändå. Tillsammans med AN1 (304
på banken) kostar en oförändrad bank noll byte online och finns offline.
