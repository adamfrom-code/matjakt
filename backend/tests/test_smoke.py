# -*- coding: utf-8 -*-
"""K4: rökprovet mot en levande Matjakt, och kedjan staging -> produktion.

Före det här paketet såg kontrollen efter en deploy ut så här: en människa
öppnade `/api/health` i en flik och tittade. Det fångar "servern svarar inte"
och ungefär inget annat. En release som startar, svarar `ok: true` och har
tappat hela prisplattformen ser likadan ut i den fliken som en frisk - och
E2E kördes bara mot en process i CI, aldrig mot något som liknar Render.

Acceptansen är två påståenden:

  1. RÖKPROVET UPPTÄCKER DE SEX FELEN. Varje prov körs här mot en påhittad
     men fullständig backend, och varje prov prövas BÅDE friskt och sjukt.
     Ett prov som bara testas i det gröna läget bevisar ingenting.

  2. KEDJAN SITTER IHOP I CI. staging deployas och rökprovas FÖRE
     produktionens hook, produktionen rökprovas efter hälsogrinden, och en
     återställning utlöses av rätt sak. Ett hoppat jobb får inte hoppa över
     produktionsdeployen med sig.
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
RENDER = ROOT / "render.yaml"


def _ladda(namn):
    sökväg = ROOT / "backend" / "scripts" / f"{namn}.py"
    spec = importlib.util.spec_from_file_location(namn, sökväg)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


smoke = _ladda("smoke")
rollback = _ladda("render_rollback")

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"

FRISK_HÄLSA = {
    "ok": True,
    "commit": SHA[:12],
    "platform": {"active": True, "chains": {}},
    "pricingAudit": {"gate": "GRÖN", "flagged": 0},  # produktionens riktiga värde
    "stripe": {"configured": True, "mode": "live"},
}


def falsk_backend(hälsa=None, recipes=200, account=401, admin=404):
    """En backend som svarar precis som produktionen gör - eller inte gör."""
    hälsa = FRISK_HÄLSA if hälsa is None else hälsa

    def hämtare(url, token=None, timeout=None):
        if url.endswith("/health"):
            return (200 if hälsa else 503), hälsa
        if "/recipes" in url:
            return recipes, {"recipes": []}
        if "/account/state" in url:
            return account, {"error": "ogiltig token"}
        if "/admin/" in url:
            return admin, None
        raise AssertionError(f"rökprovet frågade en väg ingen känner till: {url}")

    return hämtare


def kör(stripe_läge=None, **kwargs):
    return smoke.prov("https://exempel.test/api", SHA, hämtare=falsk_backend(**kwargs),
                      stripe_läge=stripe_läge)


def föll(resultat):
    return [namn for namn, ok, *_ in resultat if not ok]


def klass(resultat, namn):
    """Vilken klass ett prov har - DRIFT eller LANSERING."""
    for n, _ok, _d, k in resultat:
        if n == namn:
            return k
    raise AssertionError(f"provet {namn!r} kördes inte")


class EnFriskDeployPasserar(unittest.TestCase):
    def test_allt_gront_ger_noll_fallna(self):
        resultat = kör()
        self.assertEqual(föll(resultat), [])
        self.assertEqual(smoke.rapportera(resultat, skriv=lambda *_: None), 0)

    def test_alla_prov_kors_och_de_valfria_ar_valfria(self):
        # Sex i grunden, sju med commit-kontrollen, åtta med stripe-läget.
        # Faller ett prov ur listan tyst blir provet svagare utan att någon
        # rad ser annorlunda ut.
        self.assertEqual(len(smoke.prov("https://exempel.test/api", None,
                                        hämtare=falsk_backend())), 6)
        self.assertEqual(len(kör()), 7)
        self.assertEqual(len(kör(stripe_läge="live")), 8)

    def test_prisauditen_utan_historik_ar_inte_ett_fel(self):
        # En miljö där auditen aldrig körts har inget att rapportera. Det är
        # en saknad förutsättning, inte en trasig deploy.
        utan = dict(FRISK_HÄLSA, pricingAudit=None)
        self.assertEqual(föll(kör(hälsa=utan)), [])


class RokprovetUpptackerVarjeFel(unittest.TestCase):
    """Ett prov som bara körs i det gröna läget bevisar ingenting."""

    def test_health_som_inte_ar_ok(self):
        självbedrägeri = dict(FRISK_HÄLSA, ok=False)
        self.assertIn("health svarar 200 och ok", föll(kör(hälsa=självbedrägeri)))

    def test_gammal_commit_i_drift(self):
        # Provet kan annars ha lyckats mot den GAMLA processen medan den nya
        # kraschade i starten: grönt prov, trasig release.
        gammal = dict(FRISK_HÄLSA, commit="000011112222")
        self.assertIn(f"drift kör {SHA[:12]}", föll(kör(hälsa=gammal)))

    def test_commit_som_saknas_helt(self):
        utan = dict(FRISK_HÄLSA, commit=None)
        self.assertIn(f"drift kör {SHA[:12]}", föll(kör(hälsa=utan)))

    def test_prisplattformen_inaktiv(self):
        # Den här servar tomma veckor och svarar ändå ok: true.
        död = dict(FRISK_HÄLSA, platform={"active": False})
        self.assertIn("prisplattformen är aktiv", föll(kör(hälsa=död)))

    def test_plattformsfaltet_borta(self):
        borta = {k: v for k, v in FRISK_HÄLSA.items() if k != "platform"}
        self.assertIn("prisplattformen är aktiv", föll(kör(hälsa=borta)))

    def test_rod_prisaudit(self):
        # "RÖD" - inte "red". Provet jämförde mot "red" och testet skickade
        # "red", så de var överens om ett värde ingen kod producerar.
        # Produktionen stod på RÖD och provet sa OK.
        röd = dict(FRISK_HÄLSA, pricingAudit={"gate": "RÖD", "flagged": 42})
        r = kör(hälsa=röd)
        self.assertIn("prisauditen är grön", föll(r))
        self.assertEqual(klass(r, "prisauditen är grön"), smoke.LANSERING)

    def test_receptbanken_borta(self):
        # Receptbanken byggs ur committad JSON vid start; en deploy på tom
        # disk har startat utan den förut.
        self.assertIn("recipes svarar 200", föll(kör(recipes=500)))

    def test_kontotillstandet_ligger_oppet(self):
        # Den allvarligaste: någons sparade vecka utan token.
        self.assertIn("account/state utan token svarar 401", föll(kör(account=200)))

    def test_adminytan_syns(self):
        self.assertIn("adminvägen svarar 404 utan token", föll(kör(admin=200)))
        self.assertIn("adminvägen svarar 404 utan token", föll(kör(admin=401)))

    def test_stripe_i_fel_lage(self):
        # Staging med sk_live_ debiterar riktiga kort; produktion med
        # sk_test_ tar inte emot en enda betalning och säger inget om det.
        # Båda ser friska ut i allt annat rökprovet frågar om.
        self.assertIn("stripe kör i test-läge",
                      föll(kör(stripe_läge="test")))          # hälsan säger live
        live = dict(FRISK_HÄLSA, stripe={"configured": True, "mode": "test"})
        self.assertIn("stripe kör i live-läge",
                      föll(kör(hälsa=live, stripe_läge="live")))

    def test_stripe_som_saknas_helt_faller_inte(self):
        # AVSIKTLIGT. Ett rött rökprov mot produktion utlöser en automatisk
        # återställning; att rulla tillbaka en release för att en nyckel
        # aldrig sattes vore värre än felet. Bara MISSMATCH faller.
        for hälsa in (dict(FRISK_HÄLSA, stripe={"configured": False, "mode": None}),
                      {k: v for k, v in FRISK_HÄLSA.items() if k != "stripe"}):
            self.assertEqual(föll(kör(hälsa=hälsa, stripe_läge="live")), [])

    def test_flera_fel_rapporteras_alla(self):
        resultat = kör(recipes=500, account=200, admin=200)
        self.assertEqual(len(föll(resultat)), 3)
        self.assertEqual(smoke.rapportera(resultat, skriv=lambda *_: None), 1)


class AterstallningenValjerRattMal(unittest.TestCase):
    def _deploy(self, id_, status, commit):
        return {"deploy": {"id": id_, "status": status, "commit": {"id": commit}}}

    def test_senaste_live_som_inte_ar_den_trasiga(self):
        historik = [self._deploy("d3", "live", SHA),
                    self._deploy("d2", "live", "bbbb2222cccc3333"),
                    self._deploy("d1", "live", "aaaa1111bbbb2222")]
        self.assertEqual(rollback.välj_mål(historik, SHA)["id"], "d2")

    def test_en_misslyckad_deploy_ar_inget_att_rulla_tillbaka_till(self):
        # Precis det val man gör fel klockan tre på natten.
        historik = [self._deploy("d3", "live", SHA),
                    self._deploy("d2", "build_failed", "bbbb2222cccc3333"),
                    self._deploy("d1", "live", "aaaa1111bbbb2222")]
        self.assertEqual(rollback.välj_mål(historik, SHA)["id"], "d1")

    def test_ingen_tidigare_live_ger_inget_mal(self):
        historik = [self._deploy("d1", "live", SHA)]
        self.assertIsNone(rollback.välj_mål(historik, SHA))

    def test_utan_nyckel_sager_skriptet_ifran_i_stallet_for_att_tiga(self):
        # 2, inte 0: "kunde inte rulla tillbaka" får aldrig se ut som
        # "rullade tillbaka".
        import os
        gammal = os.environ.pop("RENDER_API_KEY", None)
        try:
            self.assertEqual(rollback.main(["--service", ""]), rollback.SAKNAS)
        finally:
            if gammal is not None:
                os.environ["RENDER_API_KEY"] = gammal


class StripeLagetProvasIBadaMiljoerna(unittest.TestCase):
    """Kommentaren i render.yaml lovar att rökprovet ser skillnad på
    sk_test_ och sk_live_. Det här är raden som gör löftet sant."""

    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")

    def test_staging_provas_mot_testlaget(self):
        efter = self.ci.split("  smoke-staging:", 1)[1].split("\n  deploy-backend:", 1)[0]
        self.assertIn("--stripe-lage test", efter,
                      "staging kunde köra sk_live_ och debitera riktiga kort")

    def test_produktionen_provas_mot_livelaget(self):
        efter = self.ci.split("  smoke-prod:", 1)[1].split("\n  rollback:", 1)[0]
        self.assertIn("--stripe-lage live", efter,
                      "produktionen kunde tyst sluta ta emot betalningar")


class KedjanICI(unittest.TestCase):
    def setUp(self):
        self.ci = CI.read_text(encoding="utf-8")

    def _krav(self, bit, varför):
        self.assertTrue(bit in self.ci, f"saknas i ci.yml: {bit!r} - {varför}")

    def test_staging_deployas_och_rokprovas(self):
        self._krav("deploy-staging:", "ingen stagingdeploy alls")
        self._krav("smoke-staging:", "staging deployas men provas aldrig")

    def test_produktionen_behover_stagingprovet(self):
        # Det HÄR är grinden. Utan raden är staging en parallell kuriosa.
        self._krav("needs: [backend, frontend, security, e2e, smoke-staging]",
                   "produktionsdeployen går förbi stagingprovet")

    def test_deploy_backend_villkoret_ar_orort(self):
        # De andra paketen mergar genom samma CI. Fyrar deploy-backend på fel
        # event deployas en PR-gren till produktion.
        self._krav("if: success() && github.event_name == 'push' && github.ref == 'refs/heads/main'",
                   "deploy-backend får bara fyra på en push till main")

    def test_produktionen_rokprovas_efter_halsogrinden(self):
        self._krav("smoke-prod:", "produktionen rökprovas inte")
        efter = self.ci.split("smoke-prod:", 1)[1][:400]
        self.assertIn("needs: [deploy-backend, health-gate]", efter,
                      "rökprovet måste köra EFTER att drift kör committen")

    def test_aterstallningen_utloses_av_ratt_sak(self):
        self._krav("rollback:", "ingen väg tillbaka från en trasig release")
        efter = self.ci.split("  rollback:", 1)[1][:600]
        for villkor in ("needs.health-gate.result == 'failure'",
                        "needs.smoke-prod.result == 'failure'"):
            self.assertIn(villkor, efter, f"återställningen utlöses inte av {villkor}")
        self.assertIn("always()", efter,
                      "utan always() tystas jobbet av ett HOPPAT behov - och det är "
                      "precis vad en failande hälsogrind gör med smoke-prod")

    def test_utan_staging_stoppas_inte_produktionen(self):
        # Ett HOPPAT jobb gör varje jobb som behöver det hoppat med sig. Därav
        # steg-nivå-if inne i smoke-staging i stället för ett villkor på
        # jobbet: en halvfärdig staging får inte stoppa produktionsdeployer.
        efter = self.ci.split("  smoke-staging:", 1)[1].split("\n  deploy-backend:", 1)[0]
        self.assertIn("if: needs.deploy-staging.outputs.triggad == 'true'", efter)
        self.assertIn("if: needs.deploy-staging.outputs.triggad != 'true'", efter,
                      "det måste finnas en gren som gör jobbet grönt utan staging")


class BlueprintenBeskriverStaging(unittest.TestCase):
    def setUp(self):
        self.render = RENDER.read_text(encoding="utf-8")

    def test_tjansten_finns_i_blueprinten(self):
        # Radslutet är inte pedanteri: utan det matchar strängen även
        # "name: matjakt-staging-data", diskens namn, och testet hade
        # passerat i en blueprint utan tjänst.
        self.assertIn("name: matjakt-staging\n", self.render)

    def test_staging_har_egen_disk(self):
        # Delad disk med produktion vore en testmiljö som skriver i
        # kontodatabasen.
        self.assertIn("name: matjakt-staging-data", self.render)

    def test_staging_varken_skrapar_eller_mejlar(self):
        efter = self.render.split("name: matjakt-staging", 1)[1]
        # Schemaläggaren hade bränt Primats DYGNSKVOT en gång till varje natt
        # - samma kvot som produktion delar.
        self.assertIn('key: MATJAKT_GROCERY_SCHEDULE_ENABLED\n        value: "0"', efter)
        self.assertIn('key: MATJAKT_MAILINGS_ENABLED\n        value: "0"', efter)

    def test_staging_deployas_inte_pa_push(self):
        efter = self.render.split("name: matjakt-staging", 1)[1]
        self.assertIn("autoDeploy: false", efter,
                      "staging ska deployas av CI, inte av en push")


if __name__ == "__main__":
    unittest.main()


class DriftSkiljsFranLansering(unittest.TestCase):
    """K4b. Ett rött rökprov mot produktion utlöser rollback, och rollback
    kan bara laga det föregående kod gjorde rätt. Proven är därför två
    sorter: DRIFT ger exit 1, LANSERING ger exit 0 med en varning.

    Bakgrunden är verklig: Stripe i testläge fällde produktionsrökprovet på
    en frisk release, rollbacken utlöstes och föll på saknade nycklar. Med
    nycklarna på plats hade en fungerande backend kastats tillbaka för att
    betalningarna ännu inte var live.
    """

    def _exit(self, resultat):
        rader = []
        kod = smoke.rapportera(resultat, skriv=rader.append)
        return kod, "\n".join(rader)

    # --- friska releaser ---

    def test_frisk_med_stripe_test_ger_exit_0_och_not_launch_ready(self):
        hälsa = dict(FRISK_HÄLSA, stripe={"configured": True, "mode": "test"})
        kod, ut = self._exit(kör(hälsa=hälsa, stripe_läge="live"))
        self.assertEqual(kod, 0, ut)
        self.assertIn("NOT LAUNCH READY", ut)
        self.assertIn("Ingen rollback", ut)

    def test_frisk_med_stripe_live_ger_exit_0_utan_varning(self):
        kod, ut = self._exit(kör(stripe_läge="live"))
        self.assertEqual(kod, 0, ut)
        self.assertNotIn("NOT LAUNCH READY", ut)
        self.assertNotIn("::warning::", ut)
        self.assertIn("LAUNCH READY", ut)

    # --- prisauditens riktiga värden, ur api_server ---

    def test_audit_rod_ger_alert_men_ingen_rollback(self):
        hälsa = dict(FRISK_HÄLSA, pricingAudit={"gate": "RÖD", "flaggor": {"estimat": 48}})
        kod, ut = self._exit(kör(hälsa=hälsa, stripe_läge="live"))
        self.assertEqual(kod, 0, ut)
        self.assertIn("ALERT: gate='RÖD'", ut)
        self.assertIn("NOT LAUNCH READY", ut)

    def test_audit_ingen_data_ger_hog_alert_men_ingen_rollback(self):
        hälsa = dict(FRISK_HÄLSA, pricingAudit={"gate": "INGEN DATA", "kontroller": 0})
        kod, ut = self._exit(kör(hälsa=hälsa, stripe_läge="live"))
        self.assertEqual(kod, 0, ut)
        self.assertIn("HÖG ALERT: gate='INGEN DATA'", ut)

    def test_audit_fel_ger_hog_alert_men_inte_blind_rollback(self):
        # Auditen kraschade. Orsaken kan vara kod ELLER en trasig datarad -
        # tvetydigt, och en tvetydig signal får inte kasta tillbaka en
        # fungerande backend. Men den läses inte längre som grön, vilket
        # den gjorde med jämförelsen mot "red".
        hälsa = dict(FRISK_HÄLSA, pricingAudit={"gate": "FEL", "error": "audit_failed"})
        kod, ut = self._exit(kör(hälsa=hälsa, stripe_läge="live"))
        self.assertEqual(kod, 0, ut)
        self.assertIn("HÖG ALERT: gate='FEL'", ut)

    def test_okant_auditvarde_ar_inte_gront(self):
        """Fail closed: ett värde vi inte känner igen får aldrig läsas som OK."""
        hälsa = dict(FRISK_HÄLSA, pricingAudit={"gate": "green"})
        self.assertIn("prisauditen är grön", föll(kör(hälsa=hälsa)))

    def test_audit_gron_ar_tyst(self):
        kod, ut = self._exit(kör(stripe_läge="live"))
        self.assertEqual(kod, 0)
        self.assertNotIn("gate=", ut.split("LAUNCH READY")[-1])

    # --- driftfel: rollback ---

    def test_health_false_ger_exit_1(self):
        kod, ut = self._exit(kör(hälsa=dict(FRISK_HÄLSA, ok=False)))
        self.assertEqual(kod, 1)
        self.assertIn("DEPLOY HEALTH", ut)

    def test_fel_commit_ger_exit_1(self):
        kod, _ = self._exit(kör(hälsa=dict(FRISK_HÄLSA, commit="0000000000ab")))
        self.assertEqual(kod, 1)

    def test_recipes_trasig_ger_exit_1(self):
        kod, _ = self._exit(kör(recipes=500))
        self.assertEqual(kod, 1)

    def test_authgrans_trasig_ger_exit_1(self):
        kod, _ = self._exit(kör(account=200))
        self.assertEqual(kod, 1)

    def test_adminvag_exponerad_ger_exit_1(self):
        kod, _ = self._exit(kör(admin=200))
        self.assertEqual(kod, 1)

    def test_prisplattform_inaktiv_ger_exit_1(self):
        hälsa = dict(FRISK_HÄLSA, platform={"active": False})
        kod, _ = self._exit(kör(hälsa=hälsa))
        self.assertEqual(kod, 1)

    def test_driftfel_och_lanseringshinder_samtidigt_ger_exit_1(self):
        """Driften vinner. Lanseringshindret rapporteras ändå, i samma utdata."""
        hälsa = dict(FRISK_HÄLSA, ok=False, stripe={"configured": True, "mode": "test"})
        kod, ut = self._exit(kör(hälsa=hälsa, stripe_läge="live"))
        self.assertEqual(kod, 1)
        self.assertIn("stripe kör i live-läge", ut)

    # --- varje prov har rätt klass ---

    def test_klasserna(self):
        r = kör(stripe_läge="live")
        for namn in ("health svarar 200 och ok", "prisplattformen är aktiv",
                     "recipes svarar 200", "account/state utan token svarar 401",
                     "adminvägen svarar 404 utan token"):
            self.assertEqual(klass(r, namn), smoke.DRIFT, namn)
        self.assertEqual(klass(r, "prisauditen är grön"), smoke.LANSERING)
        self.assertEqual(klass(r, "stripe kör i live-läge"), smoke.LANSERING)


class EngelskaGateVardenFarAldrigTillbaka(unittest.TestCase):
    """Spärren. Buggen var att smoke.py jämförde gate mot "red" och testet
    skickade "red"/"green" - värden ingen kod producerar. Produktionen stod på
    RÖD, provet sa OK, och auditen kunde aldrig fälla någonting.

    Kontrollen är på JÄMFÖRELSER ("gate" tillsammans med ett engelskt ord),
    inte på ordet i sig - kommentarer får förklara vad som var fel.
    """

    ENGELSKA = ("red", "green", "yellow", "amber")

    def _jamforelser(self, text):
        import re
        träffar = []
        for i, rad in enumerate(text.splitlines(), 1):
            if rad.lstrip().startswith("#"):
                continue
            for ord_ in self.ENGELSKA:
                if re.search(rf'gate[^\n#]*[=!]=\s*"{ord_}"|"gate":\s*"{ord_}"', rad):
                    träffar.append(f"{i}: {rad.strip()}")
        return träffar

    def test_smoke_jamfor_inte_mot_engelska(self):
        text = (ROOT / "backend" / "scripts" / "smoke.py").read_text(encoding="utf-8")
        self.assertEqual(self._jamforelser(text), [])

    def test_testerna_skickar_inte_engelska(self):
        text = Path(__file__).read_text(encoding="utf-8")
        # Ett enda undantag: fallet som bevisar att ett OKÄNT värde inte är
        # grönt använder "green" med flit, och står i test_okant_auditvarde.
        träffar = [t for t in self._jamforelser(text) if "okant" not in t and "test_okant" not in text.splitlines()[int(t.split(":")[0]) - 3]]
        self.assertEqual(träffar, [], träffar)

    def test_de_riktiga_vardena_ar_de_api_server_producerar(self):
        api = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        for värde in ("GRÖN", "RÖD", "INGEN DATA", "FEL"):
            self.assertIn(f'"{värde}"', api, f"api_server producerar inte längre {värde!r}")
        self.assertEqual(smoke.AUDIT_GRÖN, "GRÖN")
        self.assertEqual(set(smoke.AUDIT_HINDER), {"RÖD", "INGEN DATA", "FEL"})
