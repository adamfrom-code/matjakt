# CLAUDE.md — arbetsinstruktion för agenter i Matjakt

Läs den här filen först. Den gäller före vana och före vad andra filer i
repot antyder. Uppdragsbeskrivningen med alla paket ligger i
`docs/UPPDRAG-MATJAKT.md`; den här filen är reglerna som gäller oavsett
vilket paket du fått.

Repot är **publikt**. Allt du skriver i en spårad fil är publicerat i samma
sekund som det pushas.

---

## Kommandon

| Vad | Kommando |
|---|---|
| Hela testsviten (node + backend) | `npm test` |
| Bara backend-sviten (1 200+ tester, ~130 s) | `python backend/tests/run.py` |
| Ett urval av backend-sviten | `python backend/tests/run.py --pattern "test_household*"` |
| Bara node-testerna | `node --test` |
| Syntaxkontroll (app.js + compileall) | `npm run check` |
| Bygg frontend-bundlet | `npm run build` |
| Hemlighetsskanning av spårade filer | `python backend/scripts/secret_scan.py` |
| Utvecklingsserver, backend | `npm run backend` |
| Utvecklingsserver, frontend | `npm run frontend` |

**Python-tolken.** Använd `backend/venv/bin/python` eller `node scripts/py.mjs
<skript>`. `python` finns inte på alla maskiner och en tolk ur PATH saknar
nästan alltid beroendena i `backend/requirements.txt`.

`backend/tests/run.py` kör mot en slängbar tempkatalog och tomma
hemlighetsvariabler. Kör aldrig sviten på ett sätt som pekar
`MATJAKT_DATA_DIR` på den riktiga databasen.

---

## En agent = ett paket = en gren = en PR

Aldrig två paket i samma PR. Aldrig en PR som blandar två zoner.

```
git checkout main && git pull
git checkout -b paket/<ID>-<kort-slug>      # t.ex. paket/C2-multipack
# ... bygg paketet OCH acceptanstestet ...
python backend/tests/run.py && node --test  # grönt lokalt först
git commit -m "<ID>: <vad som ändrades>"    # commit-prefix är paketets ID
git push -u origin paket/<ID>-<kort-slug>
gh pr create --base main
gh pr checks <nr>                           # vänta ut CI
gh pr merge <nr> --squash --delete-branch   # bara när allt är grönt
```

- **Grennamn:** `paket/<ID>-<kort-slug>`. **Commit-prefix:** `<ID>: `.
- **Grön CI, sen merge.** Ingen merge på röd CI. Ingen forcerad merge.
  Vid konflikt: rapportera, forcera aldrig.
- `main` är skyddad: direktpush är blockerad, squash-merge krävs, och
  grenen måste vara omtestad mot aktuell main (strict). Ligger grenen
  efter är rätt åtgärd `git rebase main` + `git push --force-with-lease`,
  ny grön CI, sen merge. Det är en ombasering, inte en forcerad merge.
- **Varje paket har ett acceptanskriterium, och det är ett test — inte en
  åsikt.** Finns testet inte, skriv det först. Står det att CI ska faila på
  något: skriv CI-steget och bevisa både att det failar på fel indata och
  passerar på rätt.

---

## Zonkartan

Två paket i samma zon körs aldrig samtidigt. Paket i olika zoner kan köras
parallellt. Zonen står i paketets rubrik i `docs/UPPDRAG-MATJAKT.md`.

| Zon | Vad den äger |
|---|---|
| `Z-INFRA` | `CLAUDE.md`, `.github/CODEOWNERS`, `.gitignore`, `docs/changelog.d/`, `scripts/weave_checkpoint.mjs` |
| `Z-AUTH` | `backend/services/accounts/**` (konton, sessioner, rate limit), auth-vägarna i `api_server.py` |
| `Z-BILLING` | `backend/services/billing/**`, Stripe-webhooken, entitlements, paketering |
| `Z-PRICING` | `backend/services/pricing/**`, `backend/services/grocery/pricing.py`, `audit.py`, `backend/scripts/audit_pricing.py` |
| `Z-GROCERY` | `backend/services/grocery/**` (utom prissättningen), `backend/services/recipe_providers/**`, kollektorer och schemaläggning |
| `Z-FRONT-CORE` | `frontend/app/app.js`, `frontend/app/src/services/**`, `frontend/app/src/state/**`, `frontend/app/src/api/**`, `frontend/app/sw.js` |
| `Z-FRONT-VIEW` | Vyer och rendering i `frontend/app/`, `frontend/app/index.html`, `frontend/app/src/utils/**` |
| `Z-STYLE` | `frontend/app/styles.css`, `frontend/styles.css`, designsystem och tokens |
| `Z-MAIL` | `backend/services/email/**`, `backend/services/mailings.py`, utskick och mallar |
| `Z-SITE` | `frontend/*.html`, `frontend/site/**`, `frontend/sitemap.xml`, `frontend/robots.txt`, `marketing/**` |
| `Z-CI` | `.github/workflows/**`, `render.yaml`, `backend/Dockerfile`, `scripts/build_frontend.mjs` |

`.github/**`, `render.yaml` och `backend/Dockerfile` har **en enda ägare**
(`@adamfrom-code` i `.github/CODEOWNERS`) och rörs aldrig av ett vanligt
arbetspaket. Behöver ditt paket en ändring där: säg det i PR-beskrivningen,
håll ändringen minimal och rör inget annat i katalogen.

---

## De stora filerna är konfliktzoner

`frontend/app/app.js` (~5 300 rader) och `backend/api_server.py` (~3 550
rader) redigeras av många agenter samtidigt. Ny logik hör hemma i en **ny
modul**; i den stora filen ändrar du bara inkopplingsraden. Rör dem inte om
ditt paket inte kräver det.

---

## Absoluta förbud

Bryts något av de här är PR:en död oavsett hur bra resten är.

1. **Committa aldrig `*.db`, `*.sqlite`, `*.db-wal`, `*.db-shm`.**
   `backend/data/backups/` med kontodatabasen — e-postadresser,
   lösenordshashar, salt, reset-token-hashar och fritextfeedback för 198
   användare — låg spårad i det här **publika** repot 2026-08-31 till
   2026-09-07. Den är borta ur HEAD men kvar i historiken. CI:s
   säkerhetsjobb vägrar numera varje spårad databasfil.

2. **Committa aldrig `.env` eller `.env.*`.** Bara `.env.example`, och den
   innehåller platshållare — aldrig ett riktigt värde.

3. **Skriv aldrig ett nyckelvärde i `.claude/`.** `.claude/launch.json` är
   spårad, och den läckte en gång `MATJAKT_ADMIN_TOKEN` i klartext till det
   publika repot (commit `27edd8a`). Nyckeln finns kvar i git-historiken.
   Det är hela anledningen till att det här förbudet står här. Miljövariabler
   sätts i skalet eller i Renders dashboard — aldrig i en spårad fil.

4. **Skriv aldrig en hemlighet i någon spårad fil.**
   `python backend/scripts/secret_scan.py` körs i CI mot varje spårad fil,
   inklusive den här, och failar bygget på Stripe-nycklar, webhook-secrets,
   API-nycklar, privata nycklar och ifyllda hemlighetsvariabler. Kör det
   lokalt innan du pushar.

5. **Redigera aldrig `CHECKPOINT.md` direkt.** Den är en berättelse för en
   människa och en garanterad konflikt när tjugo agenter skriver i den.
   Ditt paket skriver sin egen fil: `docs/changelog.d/<paket-ID>.md`.
   `scripts/weave_checkpoint.mjs` väver ihop dem vid release.

6. **Committa aldrig genererade filer.** Prisauditens utdata skrivs till
   `backend/data/audit/` (gitignorerad), aldrig till repo-roten.
   `marketing/build/**`, `dist/`, `build/`, `node_modules/` och
   `backend/venv/` hör inte i git. CI failar på spårade byggartefakter.

7. **Ingen riktig utgående trafik i tester.** Sviten sätter
   hemlighetsvariablerna till tomma just för att ett test en gång gick ut
   till `api.stripe.com` och skapade riktiga kunder. Mocka.

---

## Innan du öppnar PR:en

- [ ] `python backend/tests/run.py` grön
- [ ] `node --test` grön
- [ ] `python backend/scripts/secret_scan.py` grön
- [ ] `git status` visar inga genererade filer, ingen `*.db`, ingen `.env`
- [ ] Acceptanstestet finns, och du har sett det faila utan din ändring
- [ ] `docs/changelog.d/<paket-ID>.md` skriven — `CHECKPOINT.md` orörd
- [ ] Grenen innehåller **ett** paket
