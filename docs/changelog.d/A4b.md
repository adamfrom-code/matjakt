---
paket: A4b
titel: Vävningen prövades aldrig mot de fragment som faktiskt ligger i repot
---

`node scripts/weave_checkpoint.mjs` kastade på main och kunde inte väva någon
release alls:

    Error: N0d.md: saknar front matter (--- ... ---). Se docs/changelog.d/README.md

`N0d.md`, `N0e.md` och `N0f.md` hade mergats med en `###`-rubrik överst i
stället för front matter. `läsFragment` kräver `paket` och `titel`, och kastar
på den första trasiga filen — så hela katalogen låg låst bakom den första av
dem. Filerna har nu front matter, och rubriken är borta: `väv()` skriver redan
`### <paket> · <titel>` själv, så den stod där två gånger.

**Varför tre PR:er kunde gå in gröna med ett format som inte går att väva.**
`tests/changelog.test.js` hade fem tester, och alla fem byggde sin egen
temporära katalog med `mkdtempSync` och la dit fragment de själva skrivit.
De prövade *reglerna* — sorteringen, ID-kontrollen, att en saknad titel
avvisas — men aldrig `docs/changelog.d/`. Ett format som går sönder i
verkligheten och en regel som är rätt i en tom katalog är inte samma sak, och
det var precis glappet emellan som tre paket ramlade ner i.

Grinden som saknades var den enklaste tänkbara: **väv det som faktiskt ligger
i repot.** `varje fragment i docs/changelog.d/ går faktiskt att väva` läser den
riktiga katalogen, kräver att `läsFragment` inte kastar, att den returnerar
exakt en post per `.md`-fil utom `README.md`, och att varje post också kommer
med som en rubrik i det vävda avsnittet. En väv som tyst tappar halva katalogen
är ett värre fel än ett kast, och det fallet fanns det inget som fångade.

Det andra nya testet håller ordning på den redundanta rubriken: ett fragment
får inte öppna med sin egen titel som rubrik, eftersom `väv()` redan skriver
den. Underrubriker längre ned är däremot husets sätt att skriva långa fragment
— K6 och N0b är båda avsiktligt indelade — så kontrollen gäller bara första
raden, och bara när den upprepar titeln.

Sett faila utan ändringen: båda nya testerna röda, med `N0d.md: saknar front
matter` som orsak. Efteråt väver torrkörningen alla 94 fragment och skriver
ingenting. `CHECKPOINT.md` är orörd — den här filen är hela poängen med A4.
