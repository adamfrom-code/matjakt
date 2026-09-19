---
paket: AN1
titel: Receptbanken svarar 304 när klienten redan har den
---

Appen hämtar hela banken (`/api/recipes?limit=500`, ~260 KB) vid varje
start utan villkorad hämtning — AM:s baslinje. De cachebara receptsvaren
(banken, hyllorna, ett recept) bär nu en **svag ETag ur kroppens hash**,
och samma kropp igen (`If-None-Match`) ger **304 utan kropp** med samma
cacheregel. Webbläsaren revaliderar av sig själv när `max-age` gått ut:
en oförändrad bank kostar en rundresa och noll byte, en ändrad bank
kommer hel — hashen är kroppens, inte en klockas, så en gammal bank kan
aldrig svara 304 på en ny. `no-store`-svar (Premium-filtrerade) och fel
får ingen tagg.

Mätt lokalt: andra starten ger 304 på banken i stället för 260 KB.
