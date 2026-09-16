# Matjakt — master-roadmap, avstämd mot koden

**Datum:** 2026-09-16
**Utgångspunkt:** `origin/main` = `c907f89ddd7461145cc52aaaf829f980deb57ca2` (O17, PR #193)
**Metod:** varje rad nedan är kontrollerad genom att läsa modulen, räkna testerna
och slå upp PR:en (`gh pr view`). Kod och tester är facit; äldre rapporter
(`KRAVTABELL.md`, `MASTER_BACKLOG.md`, `LANSERING.md`) är bara jämförelsematerial.
Inga tester har körts för det här dokumentet — siffrorna nedan är räknade i källan
(`grep -c 'def test_'` ger 2 463 backend-testfunktioner, `node:test` 796 fall) och
CI:s täckningsgolv står i `backend/tests/tackningsgolv.txt` (70 %).

## Statusord

| Status | Betyder här |
|---|---|
| **DONE** | Kravet är byggt, mergat på `main` och har ett test som fäller det om det tas bort |
| **PARTIAL** | Delar finns i koden — raden säger exakt vilka, och exakt vad som saknas |
| **NOT STARTED** | Sökt i koden (`grep -rn` på nyckelorden i raden) och inte hittat något som bär kravet |
| **BLOCKED EXTERNAL** | Koden är förberedd men effekten kräver något utanför repot: avtal, nyckel, ägarbeslut |
| **REJECTED-SUPERSEDED** | Kravet är medvetet ersatt av ett senare beslut, med källa |

---

## 0. Sammanfattning

### Masterordern, sektion F–AT (41 krav)

| Status | Antal | Sektioner |
|---|---:|---|
| DONE | 6 | F, O, AP, AQ, AR, AS |
| PARTIAL | 24 | H, I, K, L, M, N, P, Q, R, S, U, Y, Z, AB, AC, AE, AG, AH, AJ, AK, AM, AN, AO, AT |
| NOT STARTED | 10 | G, J, T, V, W, X, AA, AD, AF, AI |
| BLOCKED EXTERNAL | 1 | AL |
| REJECTED-SUPERSEDED | 0 | — (delkrav markerade i respektive rad: G10:s "sälj avsikten" ersatt av J6) |

### Första arbetsordern (`UPPDRAG-MATJAKT.md` våg A–K + tilläggen L, M, N, T, O)

**131 fragment i `docs/changelog.d/`, 193 PR-nummer, 0 öppna PR.** Av de
paket som står i uppdragsdokumenten är **fyra inte byggda** och **ett halvt**:

| Paket | Status | Vad som saknas |
|---|---|---|
| **C11** fyndrankningen | NOT STARTED | Bara spec (`docs/PAKET-C11-fynd.md`, PR #80). `grocery/api.py` rankar fortfarande på rabattdjup; inget `recipeIds`/`savesOnWeek` i svaret |
| **H4** delbar sparbild | NOT STARTED | `sparat.js:369` delar meningen som ren text; ingen 1080×1080-canvas |
| **L8** literalstädning | NOT STARTED | 46 färgliteraler kvar utanför `:root` i `styles.css` (8× `#FFFFFF`, 14× `rgba(23,33,27,…)`); inget test som fäller nya |
| **N1 (våg N)** köpflödet ut ur native-bygget | NOT STARTED | PR #145 heter också "N1" men är Xcode-projektet. Native-appen öppnar fortfarande Stripe externt (`app.js:4071–4097`) — tillåtet i TestFlight, inte i App Store (3.1.1) |
| **G12** egna dialoger | PARTIAL | `alert()`/`confirm()` är borta (`src/views/dialog.js`, PR #164). Kvar: "Visa alla" scrollar bara raden (`app.js:3976`), "Byt förslag" roterar `RECEPT` åtta steg (`app.js:4168`) |

Allt annat i vågorna A–K, L0–L7, L9, M1–M5, N0b–N0k, H1–H3, H5, J1–J6, T1–T4,
O16–O17 är mergat och testat — tabellerna i del 1 listar PR per paket.

### Lanseringsgrinden (`LANSERING.md` §3)

| Punkt | Status | Not |
|---|---|---|
| D11 ICA | DONE (#108) | ICA ligger på 04:30 i `DEFAULT_SCHEDULE` som LANSERING bad om |
| M1 + M2 | DONE (#137, #142) | 240/240 `mealType`; 11 recept utan foto får reservkort |
| H1 söndagsnotisen | DONE i kod / **BLOCKED EXTERNAL** i drift | `MATJAKT_VAPID_*` måste sättas i Render av Adam; tills dess `blocked_reason` |
| H2 sparkvittot | DONE (#141) | |
| L1 + L2 + L3 | DONE (#136, #161, #151) | |
| J2 | DONE (#152) | tabellen prövas mot `features.py` |
| Adams fyra punkter | BLOCKED EXTERNAL | git-historik, Stripe live/moms, biträdesavtal, support@ — se del 5 |

---

## 1. Första arbetsordern — paket för paket

Kolumnen *Test* anger acceptanstestet som PR:en pekar på. Alla rader är
mergade om inget annat sägs.

### Våg A — infrastruktur

| Paket | Status | PR | Test |
|---|---|---|---|
| A1 CLAUDE.md | DONE | #47 | `test_agentinstruktion.py` |
| A2 CODEOWNERS | DONE | #48 | `test_codeowners.py` |
| A3 genererade filer ut | DONE | #49 | `test_genererade_filer.py`, CI-steget "Inga genererade artefakter" |
| A4 changelog.d | DONE | #50 (+A4b #165, A6 #179) | `tests/changelog.test.js` |

### Våg B — pengar och säkerhet

| Paket | Status | PR | Test |
|---|---|---|---|
| B1 Stripe tappad betalning | DONE | #53 | `test_billing_recovery.py`; `/api/admin/stripe-reconcile` finns |
| B2 moms | DONE i kod / BLOCKED EXTERNAL i Stripe | #58 (+B2b #125) | `test_billing_moms.py`, `test_billing_oss.py`; `tax.py` skickar `automatic_tax` först när Stripe Tax är aktivt — Adam måste skapa nya priser med `tax_behavior=inclusive` (RELEASE.md §1) |
| B3 ångerrätt | DONE | #63 | `test_billing_angerratt.py` |
| B4 X-Forwarded-For | DONE | #51 | `test_client_ip.py` |
| B5 backup-token + kryptering | DONE i kod / BLOCKED EXTERNAL | #56 | `test_backup_download.py`; `MATJAKT_BACKUP_TOKEN`/`_PUBLIC_KEY` saknas i Render → nedladdning 404 (fail closed) |
| B6 IP-hink | DONE | #59 | `test_login_ip_budget.py` |
| B7 reset-token i URL | DONE | #54 | `tests/url-tokens.test.js`, `e2e/test_reset_link_journey.py` |
| B8 rate limit + anslutningstak | DONE | #61 | `test_connection_cap.py`, `bounded_server.py` |
| B9 tokenfragment | DONE | #62 | `test_ratelimit_identifiers.py` |
| B10 GDPR-export | DONE (API) | #65 | `test_account_export.py`; **ingen knapp i UI** anropar `/api/account/export` (grep tomt i `frontend/app/`) |

### Våg C — priser

| Paket | Status | PR | Test |
|---|---|---|---|
| C1 portionspris osäkra rader | DONE | #52 | `test_recipe_pricing.py` |
| C2 multipack | DONE | #55 | `test_units.py` |
| C3 vitlöksklyftor | DONE | #57 | `test_vitloksklyftor.py`, `migrate_vitloksklyftor.py` |
| C4 kampanjviktvaror | DONE | #60 | `test_two_tier_pricing.py` |
| C5 kampanjålder | DONE | #64 | `test_recipe_pricing.py` (`effective_price`) |
| C6 referensprisålder + orsakskoder | DONE | #66 | `COMPARISON_TOO_OLD`/`COMPARISON_LOW_COVERAGE` i `pricing.py:1474`, `test_jamforbarhet.py` |
| C7 kassasumman som golv | DONE | #67 | `test_kassasumma_golv.py`; L2 och H2 läser `totalIsFloor` |
| C8 rimlighetsspärr i motorn | DONE | #68 | `test_rimlighetssparr.py`; raden bär `unreasonable` |
| C9 skafferi med enhet | DONE | #70 | `test_skafferi_enheter.py` |
| C10 smakordsflagga | DONE | #72 | `test_audit_smakord.py` |
| **C11 fyndrankning** | **NOT STARTED** | spec #80 | — |

### Våg D — drift

| Paket | Status | PR | Test |
|---|---|---|---|
| D1 larmmottagare | DONE | #71 | `test_ops_alert_recipient.py` |
| D2 prisnivågrind | DONE | #73 | `test_price_level_gate.py` |
| D3 missad körning | DONE | #74 | `test_grocery_scheduler.py` |
| D4 senaste försöket larmar | DONE | #77 | `test_grocery_alerts.py` |
| D5 kvoten bokförs före start | DONE | #84 | `test_primat_row_budget.py`, `quota.py` |
| D6 City Gross-avdelningar | DONE | #92 | `test_citygross_departments.py` |
| D7 streaming | DONE | #105 | `test_katalog_minne.py`, `streaming.py` |
| D8 SQLite busy_timeout/cache | DONE | #107 | `test_grocery_samtidighet.py` |
| D9 robots.txt | DONE | #122 | `test_robots.py` |
| D10 backup + canary | DONE | #126 | `test_backup_aterstallning.py`, `test_canary.py` |
| D11 ICA referensnivå | DONE | #108 | `test_slappta_kedjor.py`, `test_national_stores.py` |

### Våg E och F — frontend-buggar och refaktorering

| Paket | Status | PR | Var det löstes |
|---|---|---|---|
| E0 render-buss | DONE | #69 | `invalidate("basket"|"recipes"|"account")` i `app.js`, samlad i `requestAnimationFrame`; T2b (#185) lärde E2E:n att läsa efter omritningen |
| E1 app-state.js (+E2, E4) | DONE | #75 | `src/state/app-state.js`, `normalizeState`; `tests/app-state.test.js` |
| E3 trasig blob | DONE | #174 | `tests/state.test.js` |
| E5, E13 | DONE | i F1 #102 | `src/pricing/sync.js` |
| E6, E7 | DONE | i F2 #79 | `src/api/http.js` |
| E8 flikar | DONE | #78 | `src/state/tab-sync.js` |
| E9 butiksval | DONE | #86 | `src/services/branch-choice.js`, `seeded-random.js` |
| E10, E11, E14 | DONE | i F3 #85 | `src/views/shopping.js` |
| E12 | DONE | i F4 #83 | `src/views/recipes.js` |
| E15 SW + läckor | DONE | #104 | `tests/service-worker.test.js`, `recipe-search.test.js` |
| E16 kontosynken | DONE | #124 | `test_household_sync_hardening.py` |
| F1–F6 | DONE | #102, #79, #85, #83, #106, #111 | `app.js` är 4 447 rader (var 5 297); målet 300–400 rader är **inte** nått |

### Våg G — utseende och UX

| Paket | Status | PR | Not |
|---|---|---|---|
| G1 designsystem D | DONE | #89 | `tests/stilsystem.test.js` |
| G2 Ikväll först | DONE | #103 | `tests/ikvall-forst.test.js` |
| G3 hela veckan | DONE | #120 | `tests/hela-veckan.test.js` |
| G4 kontrast | DONE | #90 | `tests/kontrast.test.js` |
| G5 träffytor 44 px | DONE | #94 (+L2b #176, L2c #192) | `tests/traffytor.test.js` |
| G6 modaler | DONE | #127 | `src/utils/modal.js`, `tests/modaler.test.js` |
| G7 Skapa min vecka | DONE | #133 | `tests/skapa-veckan.test.js` |
| G8 betalvägg efter värde | DONE | #163 | se del 2 |
| G9 postnummer frivilligt | DONE | #140 | se del 2 |
| G10 byten | DONE | #143 | se del 2 |
| G11 Inställningar | DONE | #144 (+L6 #149) | `tests/installningar.test.js` |
| G12 dialoger | **PARTIAL** | #164 | dialogerna klara; "Visa alla" och "Byt förslag" kvar |
| G13 Handla-ordningen | DONE | #187 (visas CLOSED i `gh`, men commit `cd1a51b` ligger på main) | `tests/handla-ordningen.test.js` |
| G14, G15 native/mörkt läge | DONE | #139, #183 | `tests/native-paletten.test.js` |

### Våg H — retention

| Paket | Status | PR | Not |
|---|---|---|---|
| H1 söndagsnotisen | DONE / BLOCKED EXTERNAL i drift | #138 | se del 2 |
| H2 sparkvittot | DONE | #141 (+T4 #159) | se del 2 |
| H3 veckohistorik | DONE | #188 | se del 2 |
| **H4 delbar sparbild** | **NOT STARTED** | — | `sparat.js:369` |
| H5 hänvisning + kodhantering | DONE | #177 | `billing/referral.py`, `billing/codes.py`, `test_referral_h5.py`; belöningen betalas vid `vecka_skapad` via `billing/activation.py` |

### Våg I — marknadsföring

| Paket | Status | PR |
|---|---|---|
| I1 landningssidan | DONE | #82, `test_landningssidan.py` |
| I2 SEO/delning + I3 juridik | DONE | #93, #173 (+I3b #170), `test_seo.py`, `test_juridiska_sidorna.py`, `tests/juridik.test.js` |
| I4 mailen | DONE | #95, `test_mailings.py`; utskicken är fortfarande **AV** (`MATJAKT_MAILINGS_ENABLED=0`, Adams beslut) |
| I5 App Store/Play-texter | DONE | #109; skärmbilder ska tas om efter våg L (`make_store_screenshots.py`) |
| I6 fyndsidan | DONE | #112, `test_fyndsidan.py` (byggd för C11-fältet som inte finns) |
| I7 mätning i kronor | DONE | #115 (+I7b #184, I8 #153), `test_matning_kronor.py`, `test_analytics_handelsenamn.py` |

### Våg J — paketering

| Paket | Status | PR | Not |
|---|---|---|---|
| J1 serverside paywall | DONE | #100 | `billing/gate.py`, `test_serverside_paywall.py` — varje grind bär en probe |
| J2 premiumlistan | DONE | #152 | `tests/premiumtabellen.test.js` |
| J3 ny paketering | DONE | #114 | `features.py`: alla veckotyper fria, `FREE_MAX_DINNERS=5`, hushåll >2 och sparhistorik Premium; **sju dagars trial efter första veckan finns** (`billing/activation.py`, `ACTIVATION_TRIAL_DAYS=7`) |
| J4 entitlement vid resume | DONE | #162 | `src/services/entitlement-refresh.js` |
| J5 dunning m.m. | DONE | #135 | `billing/dunning.py`, `reconcile.py`, `/api/auth/change-email` — **ingen UI** för e-postbyte (grep tomt) |
| J6 bytesavsikter | DONE | #171 | `swap_intents: free` — avsikterna är gratis igen |

### Våg K — CI och leverans

| Paket | Status | PR |
|---|---|---|
| K1 lint | DONE | #116 (+K1b #117), `test_lint.py` |
| K2 pinnade beroenden + audit | DONE | #91 (+K2b #128), `test_beroenden.py`, `test_sarbarhetsgrind.py`, `dependabot.yml` |
| K3 deploy-ordning | DONE | #81 (+K3b #118, K3c #189, K3d #190), `test_deploy_ordning.py`, `test_deploy_sker_pa_riktigt.py` |
| K4 staging + rökprov + rollback | DONE | #101, `test_smoke.py`, `render_rollback.py`; kräver `STAGING_API`/`RENDER_API_KEY` i secrets |
| K5 versionsfärskhet | DONE | #88 (ersatt i praktiken av L9 #130) |
| K6 testluckor | DONE | #110 (+K6b #123, K6c #178, K6d #181), `test_collector_kontrakt.py`, `test_migrationer.py`, `test_skipbudget.py`, `test_deploy_bakdorr.py`, coverage-jobb med golv |

### Våg L, M, N, T, O

| Paket | Status | PR |
|---|---|---|
| L0 prisreglerna | DONE | #119, `src/views/pris.js`, `tests/prisregler.test.js` |
| L1–L7 | DONE | #136, #161, #151, #132, #131, #149, #158 (+L7b #168, L7c #191) |
| **L8 literalstädning** | **NOT STARTED** | — |
| L9 versionen ur källan | DONE | #130, `test_frontend_version_farskhet.py` |
| M1–M5 receptbanken | DONE | #137, #142, #160, #172, #186 — `test_recipe_meal_type.py`, `test_recipe_images.py`, `test_recipe_pantry.py`, `test_recipe_labels.py`, `test_recipe_protein_floor.py` |
| N0b–N0k | DONE | #156, #146, #147, #154, #150, #155, #157, #167, #180 |
| N1 Xcode-projektet | DONE | #145, `test_ios_projektet.py` |
| **N1 (våg N-dokumentets)** köpflöde ut | **NOT STARTED** | namnkrock — se sammanfattningen |
| T1–T4 E2E-stabilitet | DONE | #76, #99, #185, #134, #159 |
| O16, O17 | DONE | #175, #193 |

---

## 2. Särskilt kontrollerade paket

### Förstagångsupplevelsen: G8 och G9

| | G8 · betalväggen ur första-värde-ögonblicket | G9 · postnummer frivilligt |
|---|---|---|
| **Status** | DONE | DONE |
| **PR/commit** | #163, `9968f6d`, mergad 2026-09-12 | #140, `6538f64`, mergad 2026-09-12 |
| **Filer** | `frontend/app/src/views/forsta-vardet.js` (ny), `app.js` fyra rader (`chooseMenu`, `renderStoreCards`, `setView`) | `app.js` onboarding steg 4, `renderPostcodePrompt()` i Handla, `#locateBtn` |
| **Tester** | `tests/forsta-vardet.test.js` (9 sabotage, alla sedda röda), E2E `test_forsta_veckan_kommer_utan_betalvagg` | `tests/postnummer-frivilligt.test.js` (7), E2E `test_postnumret_ar_inte_en_grind_fore_forsta_veckan`, `test_postnumret_som_hoppas_over_ger_samma_vecka` |
| **Nuvarande beteende** | `finishOnboarding()` → `chooseMenu()` → Vecka utan planmodal. Under leveransögonblicket ritas bara butiker användaren har (`utanHanglas`); "Se pris med Premium"-korten återkommer när hon navigerar vidare. Erbjudandet "Vill du ha en familjevecka i stället?" ligger som en rad ovanför veckan | Fältet heter "Postnummer (frivilligt)". Tomt fält går igenom; halvskrivet (`802`) varnar en gång. "Hoppa över – vi visar riksgemensamma priser tills vidare" tar samma väg som "Skapa min vecka" (`FALLBACK_BRANCH`). Frågan ställs igen i Handla när postnumret saknas (`postnummer_fran_handla`). "Hitta mig" säger vad som hände vid nekad plats |
| **Restarbete** | Inget inom paketet. Erbjudanderaden kostar 56 px på Veckan (L2 fick krympa sin typografi för att sju rader ska rymmas på 844 px) | Inget |

### Ikväll: L1

| | |
|---|---|
| **Status** | DONE |
| **PR/commit** | #136, `0d928f9` |
| **Filer** | `frontend/app/src/views/ikvall.js` (ny), `styles.css` (`--scrim`, `--hjalte-text`), `tests/fixtures/kontrast.mjs` |
| **Tester** | `tests/ikvall.test.js` (18 prov, 7 mutationer röda), E2E i `test_consumer_journey.py`; kontrast mätt 10,10–10,77:1 mot helvitt foto |
| **Nuvarande beteende** | Helbleed foto 278 px, ögonbryn `IKVÄLL · ONSDAG` (bara "Ikväll" när rätten är i dag), rätten i Newsreader på bilden, portionspris via `prisMarkup()`, budgetremsa med `role="img"` "557 kr av 800 kr använda", fyndrad under. Reservkort (M2) när foto saknas |
| **Restarbete** | Fyndraden är byggd för C11:s `recipeIds`/`savesOnWeek` som backend inte levererar — den visar i dag rabattrankade varor och knappen scrollar till kampanjsektionen (`app.js:3972`). Reservkortets `cqi`-padding (Z-STYLE, rapporterat i PR:en). Mörkt läge utanför skärmen städas av L8 |

### Veckan: L2, G10, H3

| | L2 · Veckan | G10 · byten | H3 · veckohistorik |
|---|---|---|---|
| **Status** | DONE | DONE (delkrav ersatt) | DONE |
| **PR/commit** | #161, `4292a37` | #143, `705c62b` | #188, `babbfb4` |
| **Filer** | `src/views/week.js` (`todayIndex()`, `veckoDagarMarkup()`), `index.html` `#weekOverview` | `app.js` `openSwapModal`/`swapDay`/`applySwap`, `src/services/swap.js` | `src/views/veckohistorik.js`, `index.html`, `renderStats` |
| **Tester** | `tests/veckan-skarmen.test.js` (19), E2E `test_veckan_ryms_pa_en_skarm_med_rubrik_och_summering` (390×844) | `tests/byten.test.js`, E2E `test_ett_tryck_byter_ratten_och_angra_tar_tillbaka_den` (fyra byten utan tak) | `tests/veckohistorik.test.js` (14, fyra mutationer körda) |
| **Nuvarande beteende** | Sju rader, inga dagflikar, `weekOverviewDay` borta. Tom dag = streckad ruta + plus med dagens namn. Summering: delposter, linje, summa; "Minst att handla för" när `totalIsFloor` (server OR radvis). "✓ Lagad"/"✗ Hoppade över" per rad (`data-cooked`/`data-skipped`, `app.js:2256`) | Ett tryck på alternativet byter, Ångra-remsa, `FREE_SWAP_LIMIT` borta. Fem avsikter (billigare, snabbare, barnvänligare, mer protein, använd hemma) | Under nyckeltalen på Sparat: när/vad/vad det kostade, snitt per vecka, rubrik efter årstid, `total: null`-veckor visas men räknas inte i snittet |
| **Restarbete** | Inget inom L2 | **REJECTED-SUPERSEDED:** G10 sålde avsikterna som Premium; J6 (#171) satte `swap_intents: {"free": True}` — alla avsikter är gratis. Låset i markupen kvarstår kopplat till nyckeln (`tests/lasen-har-en-nyckel.test.js`) | "Återanvänd förra veckan med ändringar" (X13) saknas; ingen kontroll gjord av om Free ser bara `FREE_SAVINGS_WEEKS=1` här |

### Retention: H1 och H2

| | H1 · söndagsnotisen | H2 · sparkvittot |
|---|---|---|
| **Status** | DONE i kod · **BLOCKED EXTERNAL** i drift | DONE |
| **PR/commit** | #138, `f89f3af` | #141, `0c8d9a9`; T4 #159 lagade konfliktmarkören som H2 lämnade i `styles.css` |
| **Filer** | `backend/services/push/{schedule,store,webpush}.py`, `frontend/app/src/services/weekly-push.js`, `sw.js` (`push`, `notificationclick`), `household/routes.py` (`/notifications/push`), `render.yaml` (tre `sync: false`) | `frontend/app/src/views/sparkvitto.js`, importerar `bärUnderlag`/`sparatSedan` ur `sparat.js` (L5) |
| **Tester** | `test_sondagsnotis.py` (43) inkl. `test_tva_korningar_som_bada_hann_lasa_mottagarlistan_ger_anda_en`, `tests/veckonotis.test.js` (15), `tests/service-worker.test.js` | `tests/sparkvitto.test.js` (22, fyra sabotage), browser-E2E mot bygget som bockar av hela listan |
| **Nuvarande beteende** | Söndag 17:00 Europe/Stockholm till konton med prenumeration och `notification_prefs.week`; texten "5 middagar för 4 personer" läses ur `synced_state`, generisk text utan siffror annars; `push_log UNIQUE(user_id, kind, day)` med `claim()` före sändning; tryck landar i `chooseMenu()`. Utan VAPID-nycklar: `blocked_reason`, ingen krasch. iOS: bara installerad PWA 16.4+; Capacitor-webview → `PUSH_UNSUPPORTED` ("stods-inte") | "Veckan kostade 612 kr hos Willys. 83 kr mindre än Hemköp … Ni har sparat 313 kr sedan i september." Kröningen kommer alltid från `compare_chains()` (täckning ≥ 85 %, samma saknade varor, ingen delad förstaplats, inte för gammalt); "minst" vid `totalIsFloor`; ca-form på besparingen; "Vi kunde inte jämföra den här veckan" + serverns skäl när underlag saknas; senaste giltiga jämförelse hålls kvar per veckonyckel |
| **Restarbete** | Adam: `npx web-push generate-vapid-keys` → `MATJAKT_VAPID_PUBLIC_KEY`, `_PRIVATE_KEY`, `_SUBJECT` i Render. Native-vägen (APNs via `push_devices`) är ett eget paket — `household/notifications.py` har eventlagret men ingen APNs-transport | Inget inom paketet. Notera att den löpande summan räknas ur klientens `state.savingsLog`; serversidans `billing/savings.py` (J3) är en parallell sanning — de två är inte avstämda mot varandra |

### Receptsökning — vad finns, och hur långt räcker det

**Backend** `backend/services/recipes/store.py:549` `search(tags, max_time, min_protein, max_kcal, query, meal_type, limit, offset)`:
SQL-filter; `tags` AND:as mot `recipe_labels` (normaliserade nycklar, M4); `query` är `name LIKE OR description LIKE` — **inte ingredienser**; `meal_type` är likhet. Listraden bär `ingredientNames`.
`GET /api/recipes?tag=&maxTime=&minProtein=&maxKcal=&q=` (`api_server.py:2837–2851`). `/api/v1/recipes/search?q=` går till `RECIPE_SERVICE` (TheMealDB, extern), `/api/v1/recipes/by-pantry?items=` likaså (gate `full_pantry`, gratis sedan J3).

**Frontend** `src/data/recipes.js` `searchRecipes({tags, maxTime, minProtein, maxKcal, query})`, `TAG_LABELS` (snabbt = under 20 min, billigt = under 25 kr/portion, barn, kyckling …); `src/services/recipe-search.js` `filterRecipes(recipes, query)` söker klient-sidigt i namn, typ **och ingredienser** på redan laddad lista; `pantry.js` `matchLocalRecipesToPantry`; `state.ogillar` filtrerar planerarens kandidater (`app.js:975`), inte sökningen.

| Kravfråga | Går det i dag? | Hur / vad som saknas |
|---|---|---|
| "billigt barn" | **Delvis** | Som två tag-toggles `billigt`+`barn` (AND). "Billigt" är en importetikett (<25 kr/portion vid importtillfället), inte ett levande prisfilter. Ingen fritextparsning |
| "middag 20 minuter" | **Delvis** | `maxTime=20` + `meal_type=middag` som parametrar; UI:t har toggeln "Under 20 minuter". Inte ur fritext |
| "kyckling under 40 kr" | **Nej** | Tag `kyckling` finns; **inget `maxPrice`-filter** i `search()` — `price_per_portion` ligger i `recipes` men frågas inte |
| "använd grädden" | **Delvis** | Klient: `filterRecipes` träffar ingrediensnamn i den laddade listan; `cookModal` matchar skafferi lokalt. Backend-`q` söker inte ingredienser; `by-pantry` går till TheMealDB, inte egna banken |
| "utan lök" | **Nej som sökning** | Uteslutning finns bara som `state.ogillar` i planeraren och som allergen-filter (`diet.js`). `search()` har ingen `exclude` |

Slutsats: **AG = PARTIAL.** Strukturerade filter finns och testas (`test_recipe_store.py`, `test_serverside_paywall.py:369`); saknas: pristak, ingrediens-inkludering/uteslutning i backend, fritextparsning till filter.

---

## 3. Masterordern — sektion F till AT

Varje rad: status · filer · PR/commit · tester · nuvarande beteende · exakt restarbete.

### F · Deploy/rollback-klassificering — **DONE**

| | |
|---|---|
| Filer | `.github/workflows/ci.yml` (jobb `deploy-staging` → `smoke-staging` → `deploy-backend` → `health-gate` → `smoke-prod` → `rollback`), `deploy.yml` (Pages bara på grön `workflow_run`), `backend/scripts/{wait_for_deploy,smoke,render_rollback}.py`, `services/schema_version.py` (`PRAGMA user_version`, `stämpla()` sänker aldrig) |
| PR | K3 #81, K3b #118, K3c #189, K3d #190, K4 #101, K6 #110, K6b #123, K6c #178, K6d #181 |
| Tester | `test_deploy_ordning.py`, `test_deploy_sker_pa_riktigt.py`, `test_deploy_bakdorr.py`, `test_smoke.py` (varje prov friskt och sjukt), `test_migrationer.py` (additiva migrationer mot fixtur-DB av föregående version), `test_konton_schemabaslinje.py`, `test_priscache_schemabaslinje.py` |
| Beteende | Backend först, hälsogrind pollar `commit`, Pages efter, rökprov (`smoke.py` räknar upp sju kontroller; CI-steget heter "Åtta prov"), automatisk "deploy previous" via Renders API vid rött rökprov. Rollback-klassen för schemat är "additiv eller inget": gammal kod mot ny databas är bevisad att fungera |
| Restarbete | Ingen explicit per-PR-klassificering ("kräver migration / säker att rulla tillbaka") — regeln är i stället ett test som fäller icke-additiva migrationer. `STAGING_API`/`RENDER_API_KEY` måste finnas som secrets för att staging- och rollback-jobben ska göra något (jobben säger själva ifrån annars) |

### G · App Store IAP / StoreKit — **NOT STARTED**

| | |
|---|---|
| Finns | Bara `storekitProductId: "se.matjakt.premium.monthly"/"yearly"` i `accounts/features.py:32,42` och beslutsunderlaget i `docs/IOS_RELEASE.md` (väg A: v1 utan köp i appen, väg B: StoreKit 2 + App Store Server API + `services/billing/apple_client.py`) |
| Sökt | `storekit|SKProduct|SKPayment|revenuecat|in-app purchase|transaction_id` i `backend/`, `frontend/`, `ios/`, `package.json` — noll träffar utöver ovan |
| Beteende | Native-appen öppnar Stripe Checkout externt (`@capacitor/browser`, `app.js:4071–4097`) och pollar Premium vid återkomst. OK för intern TestFlight (VAG-N §0), inte för App Store |
| Restarbete | **ADAMS BESLUT** väg A eller B. A: dölj köp-CTA när `isNativeApp()` (VAG-N:s "N1"). B: ES256-verifiering kräver kryptobibliotek (bryter stdlib-only), App Store Server Notifications-webhook, entitlement-sammanslagning Stripe/Apple, produkter i ASC |

### H · En kanonisk receptkälla, fallback ur samma data — **PARTIAL**

| | |
|---|---|
| Finns | Källa: `backend/recipe_sources/batch00–batch12.json` = **240 recept, 240 unika id** → `recipes.db` via `scripts/import_recipes.py` (validera → bild → licens → spara → prissätt; ett recept som faller i valideringen sparas inte alls). Backend bygger banken ur JSON vid start (`smoke.py` prov 4) |
| Fallback | `frontend/app/data/recipes.json` = **58 recept** i det gamla svenska schemat (`namn`, `portionspris`, `inkopspris`, `sparar`, `hemma`, `emoji`) — handskrivna priser, egen struktur. Alla 58 id finns i källan (`test_recipe_identity.py`), men innehållet genereras **inte** ur källan |
| Tester | `test_recipe_identity.py` (id-grind), `test_recipe_store.py`, `test_product_data_integrity.py` |
| Restarbete | Ett byggsteg som skriver fallbacken ur `recipe_sources` (samma fält som `/api/recipes`-projektionen, utan handskrivna priser), plus ett test att fallbacken är en delmängd av källan fält för fält. `migrate_recipes.py` (den gamla 58-migreringen) kan pensioneras när det är gjort |

### I · Receptidentitet, dubbletter, alias — **PARTIAL**

| | |
|---|---|
| Finns | `id` PRIMARY KEY + `slug UNIQUE` i `recipes`; `id_for_slug()`; `test_recipe_identity.py` håller fallback och källa ihop; dubbletten `biff-lindstrom` togs bort för hand (CHECKPOINT); de fem gamla id:na (`chili`, `lax` …) mappades om i fallbacken 2026-09-06 |
| Saknas | Ingen alias-tabell för recept-id (ett omdöpt recept bryter länkar i `weekHistory`, som därför sparar id och tål saknat namn — H3), ingen dubblettdetektion vid import (samma rätt under två namn passerar `validate()`) |
| Restarbete | `recipe_aliases(old_id → id)` med uppslag i `get()`; en importkontroll på normaliserat namn + ingredienssignatur som varnar för dubbletter |

### J · Kvalitetsstatus (DRAFT/NEEDS_REVIEW/VERIFIED/REJECTED) + tiers (CORE/DISCOVER/SPECIAL) — **NOT STARTED**

| | |
|---|---|
| Sökt | `NEEDS_REVIEW|DRAFT|VERIFIED|REJECTED|quality_status|tier|CORE|DISCOVER` i `backend/services/recipes/`, `recipe_sources/` — inga fält. Källfilerna har inget `status`/`tier` (räknat: 240 × `<none>`) |
| Närmast | Implicita grindar: `validate()` i `import_recipes.py` (mängd, enhet ur `KNOWN_UNITS`, meal_type, proteingolv `MIN_DINNER_PROTEIN_G`), `image_status`, `labels` (`vardagsmat`/`husmanskost` styr `everydayFirst()` i planeraren — en informell "CORE") |
| Restarbete | Kolumnerna `quality_status` och `tier` i `recipes` + `recipe_sources`, standard `DRAFT`/`DISCOVER` vid import, `search(meal_type="middag")` och veckoplaneraren filtrerar på `VERIFIED`+`CORE|DISCOVER`, adminvyn räknar per status (`stats()`) |

### K · Bildstatus EXACT/GOOD_VARIANT/MISSING/REJECTED — **PARTIAL**

| | |
|---|---|
| Finns | `recipes.image_status` med **två** värden (`ok`/`needs_image`), plus `image_source`, `image_source_url`, `image_credit`, `image_license`, `image_alt`; `services/recipes/images.py` `score_candidate()` (avvisar råvarufoton, icke-foton, fel rätt), `COMMERCIAL_LICENCES`; M2: 20 av 31 fick foto, 11 får reservkort (`src/views/receptbild.js`, `tests/reservkort.test.js`) |
| PR | M2 #142, L1 #136 |
| Tester | `test_recipe_images.py`, `tests/reservkort.test.js`, `tests/recipe-fallback.test.js` |
| Restarbete | Utöka värdeförrådet till `EXACT | GOOD_VARIANT | MISSING | REJECTED`; låt `score_candidate` sätta EXACT/GOOD_VARIANT; ett REJECTED som hindrar att samma bild återkommer vid nästa `backfill_recipe_images.py`; adminvyn per status |

### L · Kanoniska ingredienser — **PARTIAL**

| | |
|---|---|
| Finns | `normalize_ingredient_id(name)` i `recipes/store.py:49` (samma vikning som prismotorns `_fold`) — **212 namn → 212 id**, alltså en slug, ingen kanonisering ("Gul lök"/"Lök" är två id). På produktsidan: `INGREDIENT_ALIASES` (`pricing.py:369`), kanoniska constraints för rättvisa mellan kedjor (`pricing.py:616`), `_violates_own_rules` så alias ärver kravets uteslutningar; `recipes/pantry.py` bestämmer skafferistatus **per ingrediens** (M3); `recipe_providers/ingredient_map.py` (svenska → TheMealDB) |
| Tester | `test_category_matching.py` (`CanonicalCrossStoreRequirements`, alias), `test_recipe_pantry.py`, `test_canonical_matrix.py` |
| Restarbete | En `canonical_ingredients`-tabell (id, visningsnamn, synonymer, enhetsfamilj, skafferistatus) som `recipe_ingredients.normalized_id` pekar på; sammanslagning av synonymer i banken (t.ex. lök-varianter, torsk/torskfilé) — då blir "använd grädden" och "utan lök" en fråga mot ett id i stället för en textmatch |

### M · Enhetsfamiljer (g kg ml l st klyfta msk tsk dl paket burk påse förpackning) — **PARTIAL**

| | |
|---|---|
| Finns | `pricing.py`: `_MASS`, `_VOLUME` (ml/cl/dl/l/msk/tsk/krm), `COUNT_UNITS` (st/förp/pack … + burk/påse/paket/förpackning/knippe sedan P06a), `KLYFTA_UNITS` (C3), `convert_amount()`, `VERIFIED_DENSITY_G_PER_ML` (uppmätta Livsmedelsverket-värden, PR #32/#34), multipack ur produktsträng (C2), buljongfamilj; `import_recipes.py` `KNOWN_UNITS = {g kg ml l dl msk tsk st krm knippe klyfta}`; frontendens aggregat nycklar på namn + enhetsfamilj och vägrar summera msk med g |
| Tester | `test_units.py`, `test_verified_density.py`, `test_vitloksklyftor.py`, `test_skafferi_enheter.py`, `test_mangder_och_enheter.py` (P06a: paketorden, importvakten, checklistan), `tests/calculations.test.js` |
| Saknas | "1 st" för en förpackad vara är olöst (`KRAVTABELL`: 13 av 35 hemmavaror får inget pris); tomatpuré/sirap/currypasta/sambal saknar densitet (O10b, kräver källa); enhetsfamiljen delas inte som modul mellan frontend och backend (dubbelrader för samma vara) |
| Restarbete | En delad enhetsfamiljstabell (JSON som både `pricing.py` och `calculations.js` läser), receptenheterna paket/burk/påse med förpackningsstorlek ur produktdata, och ett beslut om vad "1 st" betyder för en förpackad vara |

### N · Produktmatchning med explainability — **PARTIAL**

| | |
|---|---|
| Finns | Varje prisrad ur `price_item()` (`pricing.py:1940–1985`) bär `productName`, `brand`, `category` ("so a caller can see WHY this product was accepted"), `packageSize`, `packageSource` (DABAS_VERIFIED/PROVIDER_VERIFIED/NORMALIZED), `packages`, `unitPrice`, `perKg`, `exactPackaging`, `unreasonable` (orsak när raden är osäker), `priceTier`, `priceSource`, `verifiedAt`; UI: "Ser något fel ut?" → `prisfel_rapporterat`; auditen namnger osäkra rader per ingrediens (#16) |
| Tester | `test_category_matching.py`, `test_rimlighetssparr.py`, `test_pricing_audit.py`, `test_pricing_audit_rules.py`, `test_matchningen_forklarar_sig.py` (P07a) |
| Saknas | Raden i appen som skriver ut förklaringen ("vald för att: …"), och alternativa kandidater i svaret (U27, topp 3). **P07a** gav `explain_match()` (åtta namngivna avvisningsregler, `helord`/`sammansattningshuvud`, kategorisk säkerhet) och `matchRule` på varje prisrad, med `alias:<alias>/<regel>` när aliaset släppte in produkten |
| Restarbete | `matchReason: {rule, headWord, category, alternativesConsidered}` i raden, och en rad i Handla-detaljen som skriver ut den; kandidatlistan (topp 3) för U27 |

### O · Jämförbar butikskorg — **DONE**

| | |
|---|---|
| Filer | `grocery/api.py:1302` `compare_chains()` — kröner bara vid täckning ≥ 85 %, identiska saknade varor (`different_baskets` + `differingItems`), ingen delad förstaplats (`all_totals_identical`), färskhet (`COMPARISON_TOO_OLD`, `COMPARISON_LOW_COVERAGE` i `pricing.py:1474`); `priceTier` REFERENCE_PRICE/VERIFIED_STORE_PRICE (D11) |
| PR | F1 #9, C6 #66, C7 #67, D11 #108 |
| Tester | `test_jamforbarhet.py`, `test_two_tier_pricing.py`, `test_national_stores.py`, `test_features.py:140` |
| Restarbete | Inget för kravet. Kvar från KRAVTABELL: valet av *vecka* görs på `comboEstimatedCost` (F2 asynkront val) — det är R/AK, inte O |

### P · Handla i butiken — **PARTIAL**

| | |
|---|---|
| Finns | L3 #151 (`src/views/shopping.js`): listan först, avdelningsgrupper (`categories.js` `CATEGORY_ORDER`), 44 px kryssruta, `prisMarkup`, genomstruken avbockad rad, "Minst att betala"-fot; G13 (`cd1a51b`) grind på ordningen + hushållsraden; `swipe-remove.js` med Ångra; U34/U35 skilda handlingar Har hemma/Köpt/Ångra via servern; offline-listan lever i `localStorage` |
| Tester | `tests/handla-skarmen.test.js`, `tests/handla-ordningen.test.js`, `tests/svep-bort.test.js`, `tests/shopping-view.test.js`, E2E `test_household_journey.py` |
| Saknas | Butiksspecifik hyllordning (U33 — ordningen är en fast lista), "varan är slut" (U36), anteckning/kategori/mängd med enhet på egna varor (U41 — `extras.js` har bara `qty` 1–99 via `setQty`, `manualItemInput` tar bara namn), bekräfta faktiskt köpt innan skafferiet uppdateras (U42 — `purchased` skriver direkt), visa behov mot faktiskt inköp (U32) |
| Restarbete | De fem U-raderna ovan; hyllordning per kedja kräver avdelningsdata från providers (`category` finns på produkten) |

### Q · Veckans fynd, personaliserat — **PARTIAL**

| | |
|---|---|
| Finns | `/api/grocery/campaigns` (rankat på rabattdjup, `api.py:139`), kampanjsektion på Ikväll med "+ Lägg i inköpslistan" (`fynd_tillagt` → `addExtraItem`, `app.js:3930`), "Följ varan" (`state.foljdaVaror`, `#followedSection`), Kampanjtorget-mailet (I4) med `favoritbutik`, fyndsidan (I6), händelsen `household.price_drop` i notislagret |
| Saknas | **C11** (rankning på sparade kronor × receptspridning, tak per kategori, `recipeIds` i svaret) — bara spec; ingen personalisering mot användarens vecka/skafferi/historik; prisbevakningsjobbet som publicerar `price_drop` finns inte (HUSHALL.md "Förberett men inte byggt") |
| Restarbete | C11 enligt `docs/PAKET-C11-fynd.md`; sedan filtrera på veckans ingredienser + `foljdaVaror`; ett nattjobb som jämför dagens pris mot historik och skriver `household.price_drop` |

### R · Planeringsmotor: hard constraints + soft scoring + PlanningContext — **PARTIAL**

| | |
|---|---|
| Hårda villkor som finns | `filterByDiet` (kosttyp, allergener med synonymer, hushållets allergier via `mergeDiet`), `dinnerCandidates` (M1 `meal_type=middag`), `state.ogillar` + hushållets `dislikes` (`app.js:975`), `feedback.disliked`, näringsmål (Premium, med fallback + U17-varning), `FREE_MAX_DINNERS` |
| Mjuk poäng som finns | `src/services/planning.js`: `inBudgetPool` (budget × 1,2 marginal, F2), `pickCheapest`/`pickBalanced`/`pickProtein`, `comboVarietyPenalty` (rättfamilj + protein, kvadratiskt), `comboHistoryPenalty` (`recentlyEatenPenalty` ur `weekHistory`), `comboPantryBonus` (0,4/vara), `comboRating` (betyg), `everydayFirst`/`everydayRank`, seedad slump per "skapa vecka" (E9), `CANDIDATE_POOL_FOR_COUNT` |
| Tester | `tests/planning.test.js`, `tests/plan-warning.test.js`, `tests/diet.test.js`, `tests/seeded-random.test.js`, `tests/meal-type.test.js`, E2E |
| Saknas | Ingen `PlanningContext` (indata är utspritt över `state.*` och lästs inne i `app.js`-funktioner); valet sker på `comboEstimatedCost` (dubbelräknar delade förpackningar, blandar kedjor — mätt median +4,6 %), inte på `/api/pricing/week`; ingen förklaring per vald rätt ("vald för att: billigast inom budget, ny proteinkälla"); inga per-dag-villkor (T); lås av enskild middag (U07), flytt mellan dagar (U08), portioner per dag (U10), aktiv tid (U15), utrustning (U16) |
| Restarbete | Bryt ut `planningContext(state)` → `{people, dinners, budget, diet, dislikes, pantry, history, goals}`; gör `bestMenuCombo` asynkron med riktig prissättning av ett fåtal kandidater; lägg `reasons[]` per vald rätt; därefter T/U07/U08/U10 |

### S · HouseholdMember med roller — **PARTIAL**

| | |
|---|---|
| Finns | `household_members(role, display_name, profile)`; `ROLE_ADMIN`/`ROLE_MEMBER` (admin ärvs av äldsta medlem, `store.py:567–631`); profil = `diet`, `spice`, `allergies`, `dislikes`, **`child: bool`** (`_clean_profile`, `store.py:1105`); allergier och ogillar slås ihop i planeraren (`mergeDiet`, `householdDietary`); hushållets plan är Premium om någon medlem är det (`routes.py:72`); cap 2/12 (`features.py`) |
| PR | #3, J3 #114 |
| Tester | `test_household_store.py` (inkl. `profile.child`), `test_household_api.py`, `test_packaging_j3.py` |
| Saknas | Rollerna vuxen/barn/gäst som kravet menar: `child` sparas men **läses ingenstans** (grep i `frontend/app` och `services/`: bara lagring + test); ingen portionsvikt per medlem; ingen "kock"/"handlare"-roll |
| Restarbete | `role ∈ {admin, member}` + `kind ∈ {adult, child, guest}` i profilen, portionsfaktor per kind, och `personer` härledd ur medlemmarna i stället för ett tal |

### T · "Vem äter hemma" per dag — **NOT STARTED**

| | |
|---|---|
| Sökt | `perDay|per_day|attendance|presence|äter hemma|personerPerDag` — inga träffar utanför analytics/dunning |
| Läge | `state.personer` är **ett** tal för hela veckan (`app-state.js:53`, klampat 1–12); `portionFactor(state.personer)` skalar alla rätter lika; `household_docs.week` bär ingen närvaro |
| Restarbete | `week.days[i].people` (eller medlems-id-lista) i veckodokumentet, `portionFactor` per dag, aggregatet i `calculations.js` per dag, och en rad i L2:s dagrad ("3 av 4 hemma") |

### U · Barnläge — **PARTIAL** (byggstenar, inget läge)

| | |
|---|---|
| Finns | Etiketten `barn` på 86 recept (`test_recipe_labels.py:47`), toggeln "Barn" i receptfiltret, bytesavsikten "Barnvänligare" (`swap.js`, kräver taggen — hittar inte på), `everydayFirst` ger +1 för `barn`, medlemsflaggan `child` (S) |
| Saknas | Inget läge som ändrar planeringen (ingen hård/mjuk term för barnvänligt i `comboAffinity`), ingen barnportion, ingen förenklad vy |
| Restarbete | En `kidsMode`/andel barn ur S som ger `barn`-etiketten vikt i `comboAffinity` och sänker kryddstyrka via `spice`; "Barnvänligare" som standardavsikt när hushållet har barn |

### V · Matmötet — **NOT STARTED**

Sökt `matmöte|omröstning|röst|vote|voting` — inga träffar. Närmast: hushållets delade vecka (`household_docs.week`) och `week_changed`-notisen. Restarbete: en förslagsrunda per medlem (`household_votes`), sammanräkning till veckan, notis `household.week_ready` när mötet är klart (eventtypen finns redan i `notifications.py:61`).

### W · Familjepuls — **NOT STARTED**

Sökt `puls|familjepuls|activity feed` — inga träffar. Substrat som finns: `household_events` (typ, aktör, tid, högst 500/hushåll), notisreglerna med debounce och gruppering ("Sara lade till 10 varor"), `analytics_user_days`. Restarbete: en vy som läser `household_events` bakåt (vem lagade, vem handlade, sparat per vecka) — datan skrivs redan.

### X · Två hem — **NOT STARTED**

`HUSHALL.md`: "En användare hör till **högst ett** hushåll" är ett medvetet beslut (`household_id_for_user` returnerar ett id). Sökt `second_household|flera hushåll` — inget. Restarbete kräver ett ombeslut: `household_members` utan unikhet per användare, ett "aktivt hushåll" i sessionen, och att `_household_id()` i `routes.py:64` tar ett val i stället för ett uppslag. Allt i `routes.py` går genom den funktionen, så ändringen är lokal — men varje vy måste få en hushållsväljare.

### Y · "Planerna ändrades" — **PARTIAL**

| | |
|---|---|
| Finns | "✓ Lagad"/"✗ Hoppade över" per dag i Veckan (`data-cooked`/`data-skipped` → `state.feedback[id].cooked/skipped`, används i `recipeAffinity`), ett-trycks-byte med Ångra (G10), `restorePreviousWeek()` (U09), `refreshAfterSettingsChange` behåller veckan (U18), `household.week_changed`-notis |
| Saknas | Flytta en middag till annan dag (U08), "ikväll blev det inget — skjut på veckan", omräkning av listan när en dag stryks (varor som redan köpts hamnar inte i skafferiet), X11 |
| Restarbete | `moveDay(from, to)` i `app-state.js`, "Hoppade över" → erbjud flytt eller skafferiinsättning av redan köpta varor, och en notis till hushållet |

### Z · "Vad kan vi äta nu" — **PARTIAL**

| | |
|---|---|
| Finns | `cookModal` "Laga med det du har hemma" (`app.js:4272`): `matchLocalRecipesToPantry` på egna banken via `pantryNamesForCooking()` + `/api/v1/recipes/by-pantry` (TheMealDB) med `matchedIngredients`; bytesavsikten "Använd det vi har hemma"; `comboPantryBonus` i planeraren |
| Tester | `tests/pantry.test.js`, `test_api_server.py:1032–1049`, `test_serverside_paywall.py:286`, E2E (`#cookFromPantryBtn`) |
| Saknas | Filter på tid ("20 minuter") och antal personer i `cookModal`; kombinera skafferi + veckans redan köpta varor; egna banken frågas bara klient-sidigt (backend-`by-pantry` går till en extern källa) |
| Restarbete | `search(ingredients_any=[…], max_time=…)` i `recipes/store.py` mot `recipe_ingredients.normalized_id`, och ett tid/personer-val i modalen |

### AA · Leftovers — **NOT STARTED**

Sökt `leftover|rester|restmiddag|överbliv` — bara `importer.py` (annan betydelse) och `kravtabell.py` (U58). Ingen restportion, ingen "resten av gårdagens" i planeraren. Restarbete: `servings` mot `personer` ger överskott per rätt (data finns: `servings` i `recipes`, `portionFactor`), spara det som skafferipost med `location=kyl` + `expiry`, och låt AC/Z läsa den.

### AB · Intelligent skafferi — **PARTIAL**

| | |
|---|---|
| Finns | `state.pantry[name] = {amount, location ∈ skafferi/kyl/frys, expiry}` (`pantry.js`), `expiryStatus()` visas som "Bäst före …" (`app.js:1989–1996`); hushållets `inventory_items` (amount, unit, category, expiry, gtin, product) synkas med revision; C9 skickar enheten och motorn vägrar gissa; `pantry_staple` per ingrediens (M3); antagna hemmavaror med tillägg (U06); "Har hemma" ur Handla skriver skafferiraden med undo-beskrivning |
| PR | #3, C9 #70, M3 #160, U06 #21 |
| Tester | `test_household_store.py:362` (expiry), `test_household_api.py:299`, `test_skafferi_enheter.py`, `tests/pantry.test.js`, `tests/assumed-home.test.js` |
| Saknas | "Har hemma utan mängd" blir `amount: 1` = exakt avdrag (U53, **kräver beslut**, mätt 4,50 kr fel); köpt ≠ förbrukat (U55/U56 — inget drar ner lagret när en rätt lagas); samma vara kan få namn-nyckel från Handla och GTIN-nyckel från Skafferi (CHECKPOINT); servern verifierar inte klientens GTIN |
| Restarbete | Beslut U53; `consume(recipeId)` vid "Lagad" som drar av ingredienserna; nyckelsammanslagning namn/GTIN (`item_key()` finns) |

### AC · ÄTA UPP — **PARTIAL**

Finns: `expiryStatus` (snart/utgången) i skafferivyn, `comboPantryBonus` (0,4 per vara — medvetet lågt, "veckan ska inte bli resthantering"), avsikten "Använd det vi har hemma". Saknas: utgångsdatum som **prioritet** (bonusen ser inte på `expiry`), en "ät upp den här veckan"-rad på Ikväll/Veckan, koppling till AA. Restarbete: vikta `comboPantryBonus` med dagar till `expiry`, och en lista "går ut inom 3 dagar" med ett tryck till `cookModal`.

### AD · Egna recept — **NOT STARTED**

Sökt `egna recept|user_recipe|own_recipe|custom_recipe` — inga träffar (U13 "att göra"). Banken är importerad från JSON av admin; `RecipeStore.upsert_recipe` finns men ingen användarväg, ingen ägarkolumn, ingen prissättning av användarens ingredienser (prismotorn tar redan `items: [{name, amount, unit}]` — `price_list()` — så prissättningen vore gratis). Restarbete: `recipes.owner_user_id`, `POST /api/recipes` med `validate()` ur `import_recipes.py`, `search()` filtrerar `owner IS NULL OR owner = me`, receptvyn med formulär.

### AE · Receptimport — **PARTIAL** (admin/batch, inte användare)

| | |
|---|---|
| Finns | `scripts/import_recipes.py` (validera → bild → licens → spara → prissätt, `KNOWN_UNITS`, proteingolv), `recipe_providers/` (abstraktion `RecipeProvider` + `TheMealDbProvider` med `ingredient_map.py`, `RECIPE_SERVICE.search/get/search_by_pantry`), `migrate_recipes.py`, `classify_recipe_meal_type.py`, `classify_recipe_pantry.py`, `compute_recipe_nutrition.py`, `normalize_recipe_labels.py` |
| Tester | `test_recipe_providers.py`, `test_recipe_pantry.py:263` (importskriptet), `test_recipe_protein_floor.py:103` |
| Saknas | Import från URL/klistrad text för användaren (schema.org/JSON-LD-parsning), ingrediensparsning "2 dl grädde" → `{amount, unit, normalized_id}` finns inte som modul (importen kräver strukturerad JSON) |
| Restarbete | En `parse_ingredient_line()` (svenska enheter ur `KNOWN_UNITS`), en `recipe_from_url()` som läser JSON-LD `Recipe`, och AD:s ägarväg |

### AF · Varianter — **NOT STARTED**

Sökt `variant` — bara mailens A/B-ämnesrader. Ingen "mindre chili"/"utan lök"-variant av ett recept (U51). Restarbete: `recipe_overrides(user_id, recipe_id, ingredient_position, amount|omitted)` som `price_list` och receptvyn läser; bygger på AD:s ägarmodell.

### AG · Smart sökning — **PARTIAL** — se del 2, "Receptsökning".

### AH · Lärande — **PARTIAL**

| | |
|---|---|
| Finns (klient) | `state.betyg` (1–5 stjärnor), `state.feedback[id] = {liked, disliked, cooked, skipped}`, `recipeAffinity()` (`app.js:648–651`: gillar +3, lagad ×1,5 upp till 3, hoppad −1), `comboRating`, `recentlyEatenPenalty` ur `weekHistory` + `favoriter`, `disliked` utesluts; allt synkas i `synced_state` |
| Tester | `tests/swap.test.js`, `tests/planning.test.js`, `tests/app-state.test.js` |
| Saknas | Inget lärande på servern (ingen aggregering över hushåll, inget "andra med din profil"), ingen per-medlem-inlärning, inget reglage "nytt mot bekant" (U12), feedback används inte för att välja **veckotyp** eller portionsstorlek |
| Restarbete | Flytta `recipeAffinity` in i R:s `PlanningContext`, ett reglage `novelty ∈ [0,1]` som skalar `comboHistoryPenalty`, och "Har du lagat den här?"-frågan kopplad till `cooked` i stället för en knapp i listan |

### AI · Kalender — **NOT STARTED**

Sökt `kalender|calendar|\.ics|ical` — bara en kommentar i `app.js:2164` ("ingen kalender emellan"). Veckan är mån–sön med `todayIndex()`. Restarbete: `.ics`-export av veckan (`text/calendar`, en händelse per middag med receptlänk) är ett litet paket; import av familjens kalender (borta-kvällar → T) är ett stort.

### AJ · Kampanjstyrd vecka — **PARTIAL**

Finns: kampanjpriser i prissättningen (`effective_price`, C4/C5), "Lägg i inköpslistan" från fynd (extravara, inte receptbyte), Kampanjtorget-mailets löfte "byter Matjakt ut en rätt mot en som använder varan" (`mailings.py`, I4). Saknas: det löftet är inte infriat — fynden bär ingen receptkoppling (C11), och planeraren har inget objektiv "kring veckans fynd". Restarbete: C11 → `recipeIds` per fynd → en `pickCampaign`-objective i `planning.js` som viktar `savesOnWeek`, och "Lägg i veckan" som byter in receptet i stället för att lägga en extravara.

### AK · Budgetmotor — **PARTIAL**

| | |
|---|---|
| Finns | `state.budget` per vecka, U01 omfattningstext (`budget-scope.js`), `inBudgetPool` med uppmätt marginal (F2), riktig prissättning `/api/pricing/week` (veckoaggregering före förpackningsräkning, U20), budgetremsa på Ikväll med `--andel`, `weekCostAlert`, C7-golvet i Veckan/Handla/kvittot, `test_e2e_matt.py` (tid till första prissatta lista), sparhistorik på servern i öre (`billing/savings.py`) |
| Saknas | Valet av vecka sker på uppskattningen (F2 asynkront val kvar), "minsta att betala nu" vid liten budget (X06), jämför med användarens vanliga butik (U22), kvarvarande mängd efter veckan (U30), månadsbudget |
| Restarbete | F2-valet (samma ändring som R), sedan X06/U22 som presentationslager på befintlig `price_list` |

### AL · Köp hela listan — **BLOCKED EXTERNAL**

`grocery/cart.py`: fyra nivåer (`FULL_CART_API` → `BULK_LIST_IMPORT` → `PRODUCT_DEEPLINK` → `STORE_HOMEPAGE_FALLBACK`), `HandoffResult.unmatched` obligatorisk, `PROVIDERS = {}` med flit; `test_cart.py` (8) hindrar att en kedja påstår mer än hemsidelänk. Blockerat på att ingen kedja har en avtalad väg in (Willys tänkt POC). Restarbete när avtal finns: en `CartProvider` per kedja; ingen DOM-styrning.

### AM · Prestanda — **PARTIAL**

Finns: E0 render-buss, E9 (butiksvalet utan kombinatorik, budgetfältet triggar inget omval), D7 streaming, D8 `busy_timeout` + schema en gång per process + självläkande cache, esbuild-bundle (~141 kB rå), `CANDIDATE_POOL_FOR_COUNT`, livepriser 5/20 per anrop med 429-stopp, `scripts/acceptance_speed.py` (flödet under pågående import), U03 mätt 1,7–5,3 s till första prissatta lista (`test_e2e_matt.py`). Saknas: ingen prestandagrind i CI (U03-testet faller först över 30 s), bilder utan `width/height` (E15-notering), ingen mätning på riktig telefon (U79). Restarbete: sänk taket i `test_e2e_matt.py` till en uppmätt nivå × 2, Lighthouse-körning mot bygget i `deploy.yml`.

### AN · Offline — **PARTIAL**

Finns: `sw.js` cache-first för skalet med revalidering av `navigate`/`src`, fallback `ignoreSearch` → `./` för djuplänkar (E15), versionen stämplas i bygget (L9), `/api/` cachas aldrig; veckan och listan ligger i `localStorage` (`storage.js`, E3 flyttar undan trasig blob), offline-texten i `index.html`, receptfallbacken `recipes.json`; hushållssynken pausar vid 401 och återupptas vid synlighet. Saknas: kö för hushållsskrivningar offline (en avbockning utan nät går förlorad — U38/U39), "väntar/bekräftat"-status per rad (U67 finns bara som global `setSyncStatus`), prisdatum på den offline visade listan. Restarbete: en `pendingWrites`-kö i `household-state.js` som töms vid `online`, och radstatus i `shopping.js`.

### AO · UI full pass — **PARTIAL**

Finns: G1–G15 och L0–L7 (designsystem D, alla åtta skärmar utom L8), `tests/kontrast.test.js`, `tests/traffytor.test.js`, `tests/modaler.test.js`, `tests/dialoger.test.js`, `tests/stilsystem.test.js`, `:focus-visible` (G5). Saknas: L8 (46 literaler), U61–U70 (en huvudhandling per vy, progressiv detaljvisning, konsekventa ord, tomlägen, Premium i sammanhang) är inte inventerade som paket, skärmläsartest (U66), "Visa alla"/"Byt förslag" (G12). Restarbete: L8 med literaltest, en U61–U70-genomgång per vy med `matjakt-design-D.html` som facit.

### AP · Hushållssynk — **DONE**

`household/store.py` + `routes.py`: revision per hushåll, `GET /api/household/sync?since=N`, soft delete med gravstenar, statusmodell NEED_TO_BUY/ALREADY_HAVE/PURCHASED/REMOVED som aldrig raderar rader, `undo` via servern, nyckelkontraktet låst i `tests/fixtures/household-keys.json` på båda sidor, E16 (blob = ögonblicksbild), låst läs- och skrivväg. Tester: `test_household_store.py`, `test_household_api.py`, `test_household_sync_hardening.py`, `test_household_release_e2e.py`, `e2e/test_household_journey.py` (två personer), `tests/household-state.test.js`, `tests/household-keys.test.js`. Kvar (dokumenterat i CHECKPOINT, inte krav-brytande): notiser konsumeras av första enheten på samma konto; servern litar på klientens GTIN.

### AQ · Analytics — **DONE**

`ANALYTICS_ALLOWED_EVENTS = ANALYTICS_EVENTS` (`api_server.py:131` → `analytics/store.py:32`, 40+ namn inkl. vyer, inställningsrader, betalsteget), `funnel()` med kohorter, `premiumBetalande`, `mrrKronor`/`mrrExMomsKronor`/`arpuKronor`, `tappadePremium`, `veckans_tal()` (de fem talen), `activation.py` markerar första veckan. I7b (#184): `test_analytics_handelsenamn.py` läser varje `trackEvent(...)` ur frontenden (10 namn i dag) och postar dem mot servern med krav på 200 — mallarna `view_<vy>` och `installning_<rad>` expanderas. Kvar (inte krav-brytande): `mail_klick` och `checkout_avbruten` har namn utan avsändare (Adams beslut om klickspårning, RELEASE.md §3); ingen egen avstängning av mätningen för användaren (DATA_MAP).

### AR · Juridik — **DONE** (kod) · Adams punkter kvar

I3 #173: avtalspart Adam From, org.nr, postadress, ångerrätt beskriver B3:s mekanism; `tests/juridik.test.js` fäller platshållare; B10 export (`data_export.py`, sju kategorier) + radering som tömmer `mail_log`, `analytics_user_days`, push-prenumerationer; `docs/DATA_MAP.md`, `docs/RETENTION.md` (2026-09-13); CI varnar på juridiska platshållare. **Kvar för Adam** (BLOCKED EXTERNAL, inte kod): GDPR art. 33-bedömning av databasläckan i git-historiken (198 rader, 11 verkliga adresser), biträdesavtal Render/Stripe/Resend, `support@matjakt.store`-vidarebefordran (adressen står på fem ställen), retention för inaktiva konton och feedback. Kodluckor som återstår: export-knapp i UI, e-postbyte i UI (API finns).

### AS · iOS privacy — **DONE**

`ios/App/App/PrivacyInfo.xcprivacy` (N0k #180): `NSPrivacyTracking=false`, fem datatyper — e-post, grov plats (postnummer), hälsa (allergier/kosttyp), produktinteraktion (Analytics), köphistorik; API-skäl `CA92.1`, `C617.1`; `ios-prep/APP_PRIVACY_LABEL.md` som `test_ios_privacy_manifest.py` håller mot manifestet; integritetspolicyn beskriver samma uppgifter (I3). Kvar för Adam: skriva av etiketten i App Store Connect.

### AT · iOS-funktioner — **PARTIAL**

| | |
|---|---|
| Finns | Capacitor 8/SPM-projekt i git (N1 #145, `test_ios_projektet.py`), `Info.plist` med `CFBundleURLSchemes matjakt`, `NSLocationWhenInUseUsageDescription`, `ITSAppUsesNonExemptEncryption`, stående läge, sv; `appUrlOpen` laddar om med query (`?verify/?reset/?invite/?recept`), `appStateChange` → `onAppResumed()` (J4 entitlement), externa länkar och Stripe i `@capacitor/browser`, `@capacitor/keyboard`, buntade typsnitt (N0b), egna ikoner/splash i design D (N0e, G14), kontrollrummet utanför bygget (N0d), signering/TestFlight-skript (N0f–N0i, `scripts/ios_testflight.sh`), granskningskonto-mall (N0h), `AbortSignal.timeout`-polyfill |
| Saknas | Universal links (ingen `applinks:` i projektet, ingen `frontend/.well-known/apple-app-site-association` — kräver Team-ID), native push via APNs (H1:s web push är `stods-inte` i webviewen), IAP (G), köp-CTA dold i native (våg N:s N1), skärmbilder efter våg L, fysisk enhet aldrig testad (U79), Android-paritet ej verifierad utöver manifestet |
| Restarbete | AASA-fil + Associated Domains (Adam: Team-ID), APNs-transport i `notifications.py` (eventlagret finns), N1 (dölj köp när `isNativeApp()`), skärmbilder |

---

## 4. Korrigeringar mot tidigare avstämningar

Det här är saker som stått som "att göra"/"inte byggt"/"ingen trial" i `KRAVTABELL.md`, `MASTER_BACKLOG.md`, `LANSERING.md` eller uppdragsbriefen men som **finns i koden på `main`**:

1. **Det finns en trial.** Briefen säger "59/399, ingen trial". `features.py` säger "No automatic trial" — men `billing/activation.py` beviljar **sju dagars Premium när kontot skapar sin första vecka** (`grant_activation_trial`, J3 #114), triggat av `/api/pricing/week` eller `vecka_skapad`. Det som är borttaget är trial vid registrering (`/api/auth/start-trial` avvisar).
2. **Retention-vågen är inte "noll paket".** `LANSERING.md` (2026-09-12) skrev "Ingenting av H är byggt". På `main` ligger H1 (#138), H2 (#141), H3 (#188) och H5 (#177). Bara H4 saknas.
3. **G13 är mergad.** `gh pr list` visar #187 som CLOSED, men commit `cd1a51b` ("G13 … (#187)") ligger på `main` och `tests/handla-ordningen.test.js` finns. LANSERING listade den under "kan vänta".
4. **Lärande finns (AH).** Betyg 1–5, gillar/gillar inte, lagad/hoppade över, `recipeAffinity` och `recentlyEatenPenalty` viktar planeraren i dag — KRAVTABELL:s U12/U52 "att göra" gäller bara reglaget och serversidan.
5. **Skafferiet är mer än en namnlista (AB/AC).** Plats (skafferi/kyl/frys), bäst före med `expiryStatus`, GTIN, mängd + enhet (C9), hushållssynk och skafferibonus i planeraren finns. Det som saknas är förbrukning och "har hemma utan mängd"-beslutet.
6. **HouseholdMember har roller och en barnflagga (S).** `role admin/member`, `profile.child`, allergier/ogillar per medlem som faktiskt slår igenom i planeraren. KRAVTABELL nämner inget av det.
7. **Planeraren har mjuk poäng och hårda filter (R).** Variation, historik, skafferibonus, betyg, tre objektiv, allergen-filter som aldrig lättas, `meal_type=middag`. Det som saknas är strukturen (PlanningContext, förklaring) och valet på riktigt pris — inte poängen.
8. **Deploy/rollback är komplett (F).** Staging → rökprov → produktion → hälsogrind → rökprov → automatisk rollback via Renders API, plus additiva migrationer bevisade mot föregående schema. `RELEASE.md`:s rollback-avsnitt ("`git revert` + push") är äldre än K4.
9. **Explainability finns i prisraden (N).** `productName`, `brand`, `category`, `packageSource`, `unreasonable`, `priceTier` går hela vägen till UI:t. Det som saknas är en läsbar mening och kandidatlistan.
10. **Sparhistoriken finns på servern (AK).** `billing/savings.py` (öre, en rad per konto och vecka, Free ser en vecka) — inte bara `state.savingsLog`.
11. **Receptimporten har en pipeline (AE).** Validering, bildsök med licenskrav, proteingolv, prissättning — och en providerabstraktion. Det är admin-vägen; användarvägen saknas.
12. **B10-exporten och J5:s e-postbyte finns som API men inte i UI.** `DATA_MAP.md` säger "e-post kan inte bytas i UI ännu" — API:t `/api/auth/change-email` + `/confirm-email-change` mergades i #135; ingen fil i `frontend/app/` anropar det (grep tomt).

Och åt andra hållet — **påståenden som inte håller vid läsning**:

- `UPPDRAG-MATJAKT.md` F-vågens mål "app.js blir 300–400 rader": filen är 4 447 rader.
- `KRAVTABELL.md` "X15 påminnelse: delvis, notiskod finns" → sedan H1 är den byggd och testad; det som saknas är nyckeln i Render.
- `IOS_RELEASE.md` rubriken "Ingen `ios/`-katalog finns ännu" är inaktuell sedan N1 #145.

---

## 5. Blockerat på Adam (inte kod)

| Vad | Varför bara Adam | Var det står |
|---|---|---|
| VAPID-nycklar för söndagsnotisen | hemligheter i Render | PR #138 |
| Stripe: nya priser `tax_behavior=inclusive`, Stripe Tax, kvitton, live-läge | Stripe-dashboarden, juridisk person | `RELEASE.md` §1 |
| `MATJAKT_BACKUP_TOKEN` + publik nyckel | hemligheter | `RELEASE.md` §2 |
| IAP väg A eller B | affärs- och plattformsbeslut | `IOS_RELEASE.md` |
| Git-historiken (`filter-repo`) + GDPR art. 33 | force-push, rättslig tidsfrist | `LANSERING.md` §4 |
| Biträdesavtal, `support@`-vidarebefordran | leverantörskonton | `LANSERING.md` §4 |
| U53 "har hemma utan mängd", O10b osäkra rader i grinden, F3b maxålder referenspris | produktdefinitioner | `KRAVTABELL.md` |
| `MATJAKT_MAILINGS_ENABLED=1`, Plausible-meta, klickspårning i mejl | beslut + policytext | `RELEASE.md` §3–4 |
| Team-ID för universal links, TestFlight-uppladdning, App Privacy-etikett | Apple-kontot | `VAG-N-appstore.md` §3 |

---

## 6. Föreslagen ordning för det som återstår

Ordnat efter vad som låser upp mest, med zon så paketen kan köras parallellt.

| # | Paket | Zon | Låser upp |
|---|---|---|---|
| 1 | **C11** fyndrankning med `recipeIds` | Z-GROCERY | Q, AJ, Ikvälls fyndrad, I4:s löfte, I6 |
| 2 | **R1** `PlanningContext` + asynkront val på riktigt pris (F2) | Z-FRONT-CORE | R, AK, T, U07/U08/U10 |
| 3 | **L-1** kanonisk ingredienstabell | Z-RECEPT | L, AG ("använd grädden", "utan lök"), Z, AE |
| 4 | **J-1** `quality_status` + `tier` | Z-RECEPT | J, K (samma migration) |
| 5 | **H-1** fallback genererad ur källan | Z-RECEPT | H, I |
| 6 | **AG-1** `maxPrice`, `ingredients_any/none` i `search()` | Z-GROCERY (recipes) | de fem sökfrågorna |
| 7 | **S/T** medlemstyp + närvaro per dag | Z-AUTH (household) + Z-FRONT-VIEW | U, AA, Y |
| 8 | **AB-1** förbrukning vid "Lagad" (efter U53-beslut) | Z-FRONT-CORE | AB, AC, AA |
| 9 | **H4**, **L8**, **G12-rest** | Z-FRONT-VIEW / Z-STYLE | lanseringens "kan vänta"-lista |
| 10 | **N1** (dölj köp i native), AASA, APNs | Z-NATIVE | AT, G (väg A) |
| 11 | **AD/AE/AF** egna recept → import → varianter | Z-RECEPT + Z-FRONT-VIEW | i den ordningen; alla tre delar ägarmodellen |
| 12 | **V/W/X/AI** | — | först efter 7; X kräver ombeslut om ett hushåll per användare |

Regeln från `CLAUDE.md` gäller varje rad: ett paket, en gren, ett acceptanstest
som setts falla utan ändringen.
