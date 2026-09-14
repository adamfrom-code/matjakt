---
paket: K6b
titel: Databasen säger själv vilken schemaversion den bär
---

K4 lade in ett `rollback`-jobb i CI som startar föregående live-deploy av sig
själv när rökprovet faller. K6 bevisade att det är ofarligt: migrationerna är
rent additiva, och en återställd release kan fortfarande läsa och skriva mot en
databas som nyare kod har migrerat — ett test per lager, mot en fixtur av
föregående versions schema.

Vad K6 lämnade kvar var **avläsningen**. Efter en återställning är frågan
"vilken schemaversion bär den här filen?" inte akademisk — den avgör om man
letar efter ett datafel eller efter ett schemafel. Fram till nu besvarades den
genom att öppna sqlite för hand och jämföra kolumnlistor mot en commit man
hoppades var rätt. Mitt i natten, med en incident igång.

SQLite har ett fält för exakt det. `PRAGMA user_version` är fyra byte i
databashuvudet som ingen annan rör, den följer med filen genom kopior och
backupper, och den kostar ingenting att läsa:

```
python -c "from services.schema_version import läs_fil; print(läs_fil('backend/data/accounts.db'))"
```

`backend/services/schema_version.py` håller numren och de två operationerna;
varje lager fick **en rad** efter sina migrationer. De fem `store.py`-filerna är
konfliktzoner och är orörda i övrigt.

Stämpeln ärver varje lagers befintliga villkor för när migrationer körs. För
butiksdata betyder det D8:s `_prepare_schema`: schema, migrering *och* stämpel
en gång per process och databasfil. Garantin som räknas håller ändå — varje
process som öppnar filen första gången stämplar den — men den som byter fil
under en pågående process byter inte stämpel förrän nästa start.

## Stämpeln går bara uppåt

`stämpla()` är `max(nuvarande, version)`, aldrig en tilldelning. Det är hela
poängen efter en återställning: den gamla koden känner bara sitt eget nummer,
öppnar en databas som är stämplad högre, och det värdefulla i det läget är just
att filen fortsätter säga *"jag är migrerad av en nyare release än den som kör
mig nu"*. Skrev den gamla koden ner numret vore upplysningen borta i exakt det
läge den finns till för — och det utan att någon rad såg annorlunda ut.

**Numren är per lager.** Ett lager = en databasfil = en egen räknare; `KONTON =
1` och `RECEPT = 1` är inte "samma version". **0 betyder "aldrig stämplad"**,
alltså varje databas som i dag ligger i produktion. Första gången den här
koden öppnar en sådan fil blir nollan lagrets nummer — det är det testet
`test_en_ostamplad_produktionsdatabas_far_sin_version` håller, och det som
failade på alla fem lagren när stämplingen kopplades bort.

`1` är schemat som det såg ut när stämpeln infördes. Migrationerna som fanns
dessförinnan ligger under 1 och kan inte numreras i efterhand: produktions-
databaserna hade redan kört dem utan att lämna spår om vilka.

## En version som inte följer schemat är värre än ingen version

Stämpeln är bara värd något om den går att lita på, och det enda som hotar den
är den tysta glömskan — någon lägger till en kolumn och bumpar inte numret.
Då betyder två databaser med samma version två olika scheman, och avläsningen
är inte längre en avläsning.

Därför bär fixturerna i `backend/tests/fixturer/scheman/*.sql` numera sin egen
`PRAGMA user_version`, och `test_ett_vaxande_schema_kraver_ett_hojt_nummer`
jämför fixturens schema mot dagens: skiljer de sig har någon lagt till en
kolumn, och då **måste** numret ha gått upp. Testet skriver ut vilken kolumn
det gäller och vad som ska göras. Prövat genom att ta bort `last_active_day`
ur `konton.sql`:

```
konton: schemat växte (users.last_active_day) men versionen står kvar på 1.
Höj KONTON i services/schema_version.py och kör
`python backend/tests/test_migrationer.py --spara` i SAMMA commit.
```

`--spara` skriver numret i dumpen och varnar om schemat ändrats utan att
numret gjort det.

## Vad grinden hittade direkt: K6:s egen baslinje var tre kolumner gammal

Första körningen failade på två lager, och det var inte ett testfel.

* `konton.sql` saknade `withdrawal_consent_at` och
  `withdrawal_consent_version`. B3 (#63) mergades 01:27 och K6 (#110) 23:21
  **samma dygn** — K6:s gren dumpade sina fixturer innan B3 landade och
  dumpade aldrig om dem efter ombaseringen.
* `priscache.sql` saknade `parser_version`, tillagd redan 2026-09-07 (#7),
  fyra dagar före K6.

K6:s rollback-tester körde alltså mot en baslinje med tre kolumner för lite.
Testet som säger "ingen kolumn får försvinna" hade tre kolumner färre att
skydda, och ingen märkte det — en fixtur som ligger efter ser i loggen ut
precis som en fixtur som stämmer. Fixturerna är omgenererade i den här
grenen; det är de två borttagna raderna i diffen.

Det är samma klass av fel som stämpeln finns till för, upptäckt av grinden som
byggdes för att upptäcka den, innan den hann bli någons incident.

## Prövat

`backend/tests/test_migrationer.py` gick från 9 till 17 tester. Var och en av
de tre egenskaperna är sedd faila utan sin del av ändringen:

| Borttaget | Vad som failar |
|---|---|
| de fem `stämpla()`-anropen | `..._stamplar_en_tom_databas` och `..._ostamplad_produktionsdatabas...`, alla fem lagren |
| `max()` i `stämpla()` | `..._versionen_sjunker_inte_nar_en_aterstalld_release...`, alla fem lagren |
| en kolumn ur en fixtur | `..._ett_vaxande_schema_kraver_ett_hojt_nummer` |
