---
paket: K2b
titel: En blipp mot PyPI är inte en sårbarhet — men den stängde varje PR och hela deployen
---

2026-09-11, main-committen `d34d294`, körning 34650990118. Steget "Kända
sårbarheter i python-beroendena (pip-audit)" föll med

    requests.exceptions.ConnectionError: ('Connection aborted.',
        ConnectionResetError(104, 'Connection reset by peer'))

En omkörning av **exakt samma commit** blev grön. Ingenting var sårbart;
uppkopplingen blinkade när pip-audit frågade PyPI.

Kostnaden för den blippen står inte i loggen. "Hemligheter och versioner" är
en av fyra obligatoriska statuscheckar i ruleset 22826769, och sedan K4/K6
står jobbet dessutom i releasekedjan — `deploy-staging` behöver `security`. En
sekunds registerstrul blockerade alltså **varje öppen PR från varje agent** och
stoppade hela deployen, tills en människa hittade jobbet och körde om det. Båda
stegen frågar över nätet, så `npm audit` bär exakt samma risk.

## Vad som ändrades

`backend/scripts/audit_deps.py` kör båda revisionerna. Den gör om frågan tre
gånger med växande paus, och först när samtliga försök föll på transporten blir
det en `::warning::` i stället för rött.

Det farliga med en sådan här ändring är att den kan göra grinden meningslös:
en skanning som svarar "nja" ser i loggen ut precis som ett rent träd. Därför
kräver nedgraderingen **positivt bevis** för att felet låg i nätet, i tre led:

**1. Finns ett svar är svaret facit.** Båda verktygen kör med maskinläsbar
utdata (`--format=json`, `--json`). Går rapporten att tolka har frågan kommit
fram, och då avgör rapporten ensam: fynd → rött, inga fynd → grönt.
Transportmönstren läses aldrig när det finns en rapport, så en CVE-text som
råkar innehålla "Connection reset by peer" kan inte nedgradera sitt eget fynd.

**2. Saknas svar krävs en känd signatur.** Bara mönstren i `NÄTFALL_MÖNSTER` —
avbruten uppkoppling, DNS, timeout, 502/503/504, 429 — räknas som "kunde inte
fråga". Listan är med flit kort och specifik: varje rad i den är en väg för ett
fel att slippa fälla grinden, så `error` och `failed` hör inte hemma där. Allt
annat som misslyckas är `OKÄNT` och **fäller grinden som förr** — en trasig
låsfil, ett verktyg som inte startar, en borttagen flagga, en hash som inte
stämmer.

**3. Varning, aldrig tyst godkännande.** Annotationen säger rakt ut att trädet
är OSKANNAT i den körningen, och att en varning som återkommer körning efter
körning är ett fel att felsöka och inte en blipp.

Installationen av `pip-audit` ligger innanför samma omförsök: föll den på nätet
kom frågan aldrig fram heller. Den körs numera bara när verktyget saknas.

## Ett hål som byggdes in och stängdes igen

Hela konstruktionen vilar på att en tolkbar rapport är facit — så den dagen
rapporten *inte* går att tolka ser ett fullgott svar ut som "fick inget svar".
Första tolken läste stdout med `json.loads` och, om det inte gick, från första
`{` eller `[`. Den klarade brus **före** rapporten men inte **efter**: ett
`npm notice` på sista raden gjorde att ett verkligt fynd lästes som ett trasigt
verktyg. Rätt håll att faila åt, men fel svar — och hade bruset kommit i varje
körning hade grinden varit avstängd utan att någon märkte det.

Tolken använder nu `raw_decode`, som läser ett dokument från en position och
struntar i vad som följer efter. Fyra tester i `RapportenHittasIBruset` håller
båda sidorna, och den gamla tolken är mätt mot dem: brus efter rapporten gav
`HITTADE INGET`.

## Kommandona flyttade in i skriptet

`pip-audit -r backend/requirements.txt` och `npm audit --audit-level=high` står
inte längre i `ci.yml`. Flaggorna som ger maskinläsbar utdata hör ihop med
tolken som läser den, och skiljer man dem åt kan en ändring i `ci.yml` tyst
göra varje körning otolkbar — då blir varje körning ett "nätfall", och grinden
kan aldrig mer bli röd. Det är precis det felet paketet finns för att stänga.

K2:s två grindtester i `test_beroenden.py` pekar därför om till
`audit_deps.py pip` respektive `npm`; att kommandona bakom dem är *rätt* hålls
av `test_sarbarhetsgrind.SkriptetKorRattKommandon`. Garantin är densamma,
bara förankrad där kommandot numera bor.

## Beviset att grinden fortfarande blir röd

Ett CI-steg som inte kan faila är inget CI-steg, så acceptansen prövar båda
riktningarna — 33 tester i `backend/tests/test_sarbarhetsgrind.py`, varav nio
genom den riktiga CLI:n med attrapper på `PATH` (ingen utgående trafik).

Mätt **utan** ändringen, med ett försök och varje misslyckande rött som förr:
sex tester rött, och det är de sex som håller omförsöket. De övriga tjugosju —
alla "rött på en sårbarhet" — var gröna även då, vilket är precis meningen:
det gamla beteendet försvagas inte, det kompletteras.

Mätt **live** mot riktiga PyPI, genom hela skriptet:

    A · pip-audit -r <jinja2==3.1.2>   → jinja2 3.1.2: PYSEC-2026-1471 … 1475
                                         ::error  ·  steget avslutade med 1
    B · pip-audit -r requirements.txt  → inga kända sårbarheter i 4 låsta paket
                                         steget avslutade med 0

Samma skript, samma nät, två olika träd. Den enda skillnaden är svaret.

## Medveten avvägning

Ligger PyPI eller npm nere en hel dag går PR:er igenom oskannade, med en
varning på varje körning. Det är valt med öppna ögon. Den andra vägen — röd
grind — stoppar elva agenter och hela releasekedjan på ett fel som inte finns i
koden, och en obligatorisk check som fälls av någon annans drift lär man sig
att köra om utan att läsa. Då är den inte en grind längre, bara en rit.

`test_sarbarhetsgrind.GrindenStarICI` håller dessutom fast de fyra
obligatoriska statuscheckarnas **namn**. Ett omdöpt jobb gör rulesetets krav
omöjligt att uppfylla, och varje PR fastnar för evigt på en check som aldrig
rapporteras.
