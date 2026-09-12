# -*- coding: utf-8 -*-
"""I3: de juridiska sidorna ska beskriva den kod som faktiskt körs.

Två sidor på matjakt.store är avtalsdokument, inte marknadsföring:
`integritetspolicy.html` och `anvandarvillkor.html`. App Store och Google
Play pekar båda på policyn (`store/*/metadata/sv-SE/privacy_url.txt`), och
appen länkar dit från kontovyn. Står det något där som koden inte gör är
det inte en slarvig mening - det är en oriktig uppgift i ett avtal.

DÄRFÖR ÄR DET HÄR ETT TEST OCH INTE EN GRANSKNING. Varje påstående nedan
är knutet till sin källa i koden: lagringstiderna läses ur konstanterna,
tredjeparterna ur de filer som anropar dem, och typsnitts- och
statistikleverantören ur sidornas egen markup. Byter någon ut en
leverantör, förlänger en giltighetstid eller lägger på ett skript failar
det här testet tills policyn följt med.

PLATSHÅLLARE. `test_inga_platshallare_i_texten` är paketets
acceptanskriterium: ingen "[FYLLS I]", ingen TODO, ingen "exempel.se" i en
publicerad juridisk text. MEDVETET KVARLÄMNADE platshållare står i
`MEDVETNA_PLATSHALLARE` med ett skäl - listan är tom i dag, och det är
meningen att den ska vara svår att fylla på.
"""

import re
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
POLICY = FRONTEND / "integritetspolicy.html"
VILLKOR = FRONTEND / "anvandarvillkor.html"
JURIDISKA = (POLICY, VILLKOR)


def text(sida: Path) -> str:
    return sida.read_text(encoding="utf-8")


def brodtext(sida: Path) -> str:
    """Sidan som en läsare ser den: utan <style>, <script> och taggar.

    Platshållarjakten ska titta på det PUBLICERADE, inte på en
    CSS-klass som heter .placeholder eller en kommentar till nästa agent."""
    html = text(sida)
    html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


# Mönstren är skrivna för att fånga det som faktiskt brukar bli kvar i en
# juridisk mall, inte för att vara kluriga. "lorem" och "exempel.se" har
# aldrig stått i de här filerna; de står här för att nästa mall som klistras
# in ska studsa på raden.
PLATSHALLARMONSTER = (
    r"\[[^\]]{0,60}(fylls i|fyll i|ditt namn|företagsnamn|organisationsnummer|adress här|xxx)[^\]]{0,60}\]",
    r"\bTODO\b",
    r"\bFIXME\b",
    r"\bTBD\b",
    r"\blorem ipsum\b",
    r"\bexempel\.se\b",
    r"\bexample\.com\b",
    r"\bdin-domän\b",
    r"\bÅÅÅÅ-MM-DD\b",
    r"\bXXXXXX-XXXX\b",
    r"\[ *\.\.\. *\]",
)

# Formatet är (sida, exakt textrad, skäl). Tom lista = ingenting är medvetet
# kvarlämnat. Lägger du till en rad här ska skälet gå att läsa av en
# människa som undrar varför det står en lucka i ett avtal - "hinner inte"
# är inte ett skäl, "Adam måste bekräfta X hos leverantören" är det.
MEDVETNA_PLATSHALLARE: tuple[tuple[str, str, str], ...] = ()


class IngaPlatshallare(unittest.TestCase):
    """Paketets acceptanskriterium (I3)."""

    def test_inga_platshallare_i_texten(self):
        tillatna = {(sida, rad) for sida, rad, _ in MEDVETNA_PLATSHALLARE}
        for sida in JURIDISKA:
            läst = brodtext(sida)
            for mönster in PLATSHALLARMONSTER:
                for träff in re.finditer(mönster, läst, flags=re.I):
                    rad = träff.group(0).strip()
                    self.assertIn(
                        (sida.name, rad), tillatna,
                        f"{sida.name} innehåller platshållaren {rad!r}. Fyll i den, "
                        f"eller skriv in den i MEDVETNA_PLATSHALLARE med ett skäl.")

    def test_medvetna_platshallare_star_kvar_och_har_skal(self):
        """En rad i listan som ingen längre kan hitta på sidan är en lögn om
        vad som är ofärdigt. Då ska raden bort ur listan."""
        for sidnamn, rad, skäl in MEDVETNA_PLATSHALLARE:
            sida = FRONTEND / sidnamn
            self.assertTrue(sida.exists(), f"{sidnamn} finns inte")
            self.assertIn(rad, brodtext(sida),
                          f"{sidnamn}: platshållaren {rad!r} är ifylld - ta bort raden ur listan")
            self.assertGreater(len(skäl), 20, f"{sidnamn}: {rad!r} saknar ett läsbart skäl")

    def test_sidorna_ar_daterade_och_datumet_har_varit(self):
        """Stämpla med UTC-datumet, inte med din klocka.

        `date.today()` är LOKAL tid. CI-löparen står på UTC; en svensk
        sommarkväll efter kl. 22:00 är det redan i morgon här och
        fortfarande i dag där. En sida daterad efter din egen kalender
        failar då i CI med "daterad i framtiden" - verifierat 2026-09-12,
        22:37 UTC. Regeln är enkel: `date -u +%F` är datumet som ska stå
        på sidan."""
        for sida in JURIDISKA:
            träff = re.search(r"Senast uppdaterad:\s*(\d{4}-\d{2}-\d{2})", brodtext(sida))
            self.assertIsNotNone(träff, f"{sida.name} saknar ett uppdateringsdatum")
            stämpel = date.fromisoformat(träff.group(1))
            self.assertLessEqual(stämpel, date.today(),
                                 f"{sida.name} är daterad i framtiden ({stämpel})")


class PolicynNamngerDetSidornaLaddar(unittest.TestCase):
    """Det som en besökares webbläsare kontaktar går att läsa ur markupen.
    Då ska det också gå att läsa i policyn."""

    def publika_sidor(self) -> list[Path]:
        return sorted(FRONTEND.glob("*.html")) + [FRONTEND / "app" / "index.html"]

    def test_google_fonts_ar_namngivet_sa_lange_sidorna_hamtar_typsnitt_dar(self):
        laddar = [s.name for s in self.publika_sidor()
                  if s.exists() and "fonts.googleapis.com" in text(s)]
        if not laddar:
            self.skipTest("ingen sida hämtar typsnitt från Google längre")
        self.assertIn("Google Fonts", text(POLICY),
                      f"{', '.join(laddar)} hämtar typsnitt från Google - besökarens "
                      "IP-adress går dit, och det ska stå i policyn")

    def test_statistikleverantoren_i_markupen_ar_den_som_namns(self):
        """<meta name="matjakt-traffic"> avgör vilket skript som laddas
        (frontend/traffic.js). Byts plausible mot umami måste policyn med."""
        leverantörer = set()
        for sida in self.publika_sidor():
            if not sida.exists():
                continue
            for värde in re.findall(r'name="matjakt-traffic"\s+content="([^"]*)"', text(sida)):
                if värde.strip():
                    leverantörer.add(värde.split(":")[0].strip().lower())
        policy = text(POLICY)
        for namn in leverantörer:
            self.assertIn(namn.capitalize(), policy,
                          f"besöksstatistiken körs med {namn} - policyn namnger den inte")
        if "plausible" not in leverantörer:
            self.assertNotIn("Plausible", policy,
                             "policyn namnger Plausible men ingen sida laddar det längre")


class PolicynNamngerDetServernAnropar(unittest.TestCase):
    """Varje rad är ett par: ett bevis i koden och ett namn i policyn. Faller
    beviset bort ska namnet ut ur policyn; tillkommer ett nytt anrop någon
    annanstans fångas det inte här - men ett som BYTS ut fångas."""

    # Resend är med flit det enda paret vars bevis är en driftfil och inte en
    # anropande modul: mailer.py talar ren SMTP mot värden i SMTP_HOST och
    # nämner ingen leverantör alls. Vem den värden är avgörs av Render-miljön,
    # och det enda spårade stället som skriver ut den är RELEASE.md. Policyn
    # namnger Resend för att det är sant i drift - inte för att koden gör det.
    PARTER = (
        ("Stripe", "backend/services/billing/stripe_client.py", "api.stripe.com"),
        ("Primat", "backend/services/pricing/primat_client.py", "primat.nu"),
        ("Dabas", "backend/services/grocery/providers/dabas.py", "api.dabas.com"),
        ("Open Food Facts", "backend/services/pricing/open_food_facts_client.py", "openfoodfacts.org"),
        ("Zippopotam", "backend/api_server.py", "zippopotam.us"),
        ("Render", "render.yaml", "matjakt-backend"),
        ("GitHub", ".github/workflows/deploy.yml", "deploy-pages"),
        ("Resend", "docs/RELEASE.md", "smtp.resend.com"),
    )

    def test_varje_namngiven_part_har_ett_bevis_och_tvartom(self):
        policy = text(POLICY)
        for namn, fil, bevis in self.PARTER:
            källa = ROOT / fil
            self.assertTrue(källa.exists(), f"{fil} finns inte - uppdatera PARTER")
            self.assertIn(bevis, källa.read_text(encoding="utf-8"),
                          f"{fil} anropar inte längre {bevis} - då ska {namn} ut ur policyn")
            self.assertIn(namn, policy, f"policyn namnger inte {namn} ({fil})")

    def test_push_tjansten_namns_sa_lange_notiser_skickas_till_en(self):
        webpush = (ROOT / "backend" / "services" / "push" / "webpush.py").read_text(encoding="utf-8")
        self.assertIn("endpoint", webpush)
        policy = text(POLICY)
        for part in ("Apple", "Google", "Mozilla"):
            self.assertIn(part, policy,
                          f"notisen POSTas till användarens push-tjänst - {part} ska nämnas")

    def test_policyn_sager_att_ip_adressen_sparas_pa_disk(self):
        """Missbruksspärren skriver IP-adress (och vid inloggning e-post) till
        ratelimit.db - inte bara till processminnet. docs/DATA_MAP.md påstod
        motsatsen; policyn får inte göra om det felet."""
        ratelimit = (ROOT / "backend" / "services" / "accounts" / "ratelimit.py").read_text(encoding="utf-8")
        self.assertIn("rate_limit_hits", ratelimit)
        läst = brodtext(POLICY)
        self.assertRegex(läst, r"IP-adress[^.]{0,400}spärr|spärr[^.]{0,400}IP-adress",
                         "policyn förklarar inte att IP-adressen sparas i missbruksspärren")

    def test_postnumret_gar_till_de_tre_som_faktiskt_far_det(self):
        """Ett utkast placerade Primat under 'får aldrig något om dig'. Det var
        fel: butiksuppslaget skickar användarens postnummer till Primat och
        till ICA, precis som till Zippopotam. Postnumret ÄR en personuppgift
        när det hör till ett konto, så de tre ska stå för sig - och den dag ett
        anrop slutar bära postnumret ska raden ut ur policyn igen."""
        server = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        primat = (ROOT / "backend/services/pricing/primat_client.py").read_text(encoding="utf-8")
        self.assertIn('params={"postcode": zip_code}', primat,
                      "Primat får inte längre postnumret - flytta tillbaka den till anonyma källor")
        self.assertIn("handla.ica.se/api/store/v1?zip=", server,
                      "ICA-butikssökningen bär inte längre postnumret")
        self.assertIn("api.zippopotam.us/SE/", server)
        läst = brodtext(POLICY)
        rubrik = "Det ditt postnummer – och bara det – skickas till"
        self.assertIn(rubrik, läst, "policyn har ingen rubrik för mottagarna av postnumret")
        avsnitt = läst.split(rubrik, 1)[1][:900]
        for part in ("Zippopotam", "Primat", "ICA"):
            self.assertIn(part, avsnitt, f"{part} får postnumret men står inte under {rubrik!r}")

    def test_primat_star_inte_kvar_bland_dem_som_inte_far_nagot(self):
        """Regressionsvakt för just det felet: rubriken om anonyma källor får
        inte lova att Primat aldrig får något, när butiksuppslaget gör det."""
        läst = brodtext(POLICY)
        rubrik = "Källor som aldrig får något om dig"
        self.assertIn(rubrik, läst)
        avsnitt = läst.split(rubrik, 1)[1][:900]
        self.assertNotIn("Zippopotam", avsnitt,
                         "Zippopotam får postnumret - den hör inte hemma under "
                         f"{rubrik!r}")


class LagringstidernaStammerMedKoden(unittest.TestCase):
    """Tiderna i policyns tabell är konstanter någon annanstans. Ändras
    konstanten utan att tabellen följer med är tabellen fel - och en fel
    lagringstid i en integritetspolicy är en oriktig uppgift, inte en detalj."""

    def konstant(self, fil: str, namn: str) -> int:
        källa = (ROOT / fil).read_text(encoding="utf-8")
        träff = re.search(rf"^{namn}\s*=\s*(\d+)", källa, flags=re.M)
        self.assertIsNotNone(träff, f"{namn} finns inte i {fil}")
        return int(träff.group(1))

    def test_sessionen_och_tokenen(self):
        läst = brodtext(POLICY)
        dagar = self.konstant("backend/services/accounts/store.py", "SESSION_TTL_DAYS")
        self.assertIn(f"{dagar} dygn från inloggning", läst)
        verifiering = self.konstant("backend/services/accounts/store.py", "VERIFICATION_TOKEN_TTL_DAYS")
        self.assertRegex(läst, rf"Verifieringslänk\s*{verifiering} dygn")
        återställning = (ROOT / "backend/services/accounts/store.py").read_text(encoding="utf-8")
        self.assertIn("timedelta(hours=1)", återställning.split("def request_password_reset")[1][:600],
                      "återställningslänken gäller inte längre en timme")
        self.assertRegex(läst, r"Återställningslänk för lösenord\s*1 timme")

    def test_hushallets_tider(self):
        läst = brodtext(POLICY)
        timmar = self.konstant("backend/services/household/store.py", "INVITE_TTL_HOURS")
        self.assertIn(f"{timmar} timmar", läst)
        händelser = self.konstant("backend/services/household/store.py", "MAX_EVENTS_PER_HOUSEHOLD")
        self.assertIn(f"{händelser} senaste", läst)
        self.assertIn(f"{händelser} rader", läst)

    def test_backupens_livslangd(self):
        """KEEP räknar KOPIOR, inte dygn: `for stale in sets[:-KEEP]` sorterar
        katalogerna och kastar alla utom de sista. Ett set per dygn gör att det
        i praktiken blir ungefär en vecka - men efter ett driftavbrott sträcker
        sig de sju seten längre bak än sju dygn. Policyn ska säga kopior."""
        läst = brodtext(POLICY)
        set_kvar = self.konstant("backend/services/backup.py", "KEEP")
        självaste = (ROOT / "backend/services/backup.py").read_text(encoding="utf-8")
        self.assertIn("sets[:-KEEP]", självaste,
                      "backup.py beskär inte längre på antal set - läs om konstanten")
        self.assertIn(f"{set_kvar} senaste kopiorna", läst,
                      "policyn säger inte hur länge ett raderat konto ligger kvar i en säkerhetskopia")
        self.assertNotIn(f"{set_kvar} dygn på servern", läst,
                         "KEEP är antal kopior, inte dygn - formuleringen lovar en exakthet koden inte har")


class PlatsenBeskrivsSomKodenFaktisktGor(unittest.TestCase):
    """Ett utkast skrev att koordinaterna från "Hitta mig" SPARAS tills man
    byter postnummer. De sparas inte alls.

    `state.position` sätts i app.js men ingår inte i `buildSyncPayload()`, och
    det är den payloaden - och bara den - som `persistLocally()` skriver till
    localStorage och som POSTas till /api/account/state. `users` har ingen
    lat/lon-kolumn. Koordinaterna lever alltså i JS-minnet under sessionen och
    tar aldrig vägen till disk eller server.

    Det spelar roll åt båda håll: en policy som överdriver insamlingen är lika
    oriktig som en som underdriver den, och appens iOS-manifest deklarerar
    exakt plats som "linked to the user" - någon av de två har fel."""

    def test_koordinaterna_lamnar_inte_enheten(self):
        state = (ROOT / "frontend/app/src/state/app-state.js").read_text(encoding="utf-8")
        payload = re.search(r"buildSyncPayload[^{]*\{(.*?)\n\}", state, flags=re.S)
        self.assertIsNotNone(payload, "buildSyncPayload() finns inte längre i app-state.js")
        self.assertNotIn("position", payload.group(1),
                         "position ingår nu i synkpayloaden - då SPARAS koordinaterna, "
                         "och policyns 'stannar i appens minne' är inte längre sant")
        konto = (ROOT / "backend/services/accounts/store.py").read_text(encoding="utf-8")
        for kolumn in ('"latitude"', '"longitude"', '("lat"', '("lon"'):
            self.assertNotIn(kolumn, konto, f"users bär nu {kolumn} - policyn måste skrivas om")
        läst = brodtext(POLICY)
        self.assertIn("koordinaterna stannar i appens minne", läst,
                      "policyn säger inte att koordinaterna aldrig lämnar enheten")
        self.assertIn("postnummer", läst)

    def test_policyn_inte_pastar_att_positionen_sparas(self):
        läst = brodtext(POLICY)
        self.assertNotRegex(
            läst, r"sparas också en ungefärlig position",
            "policyn påstår att positionen sparas - koden sparar den inte")


class RattigheternaFinnsIKoden(unittest.TestCase):
    """Policyn lovar fyra vägar ut. Alla fyra ska gå att peka på."""

    def test_raderingen_finns_och_stadar_det_policyn_pastar(self):
        server = (ROOT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/auth/delete-account"', server)
        radering = server.split('"/api/auth/delete-account"')[1][:3000]
        for städning in ("HOUSEHOLD_STORE.forget_user", "NOTIFICATION_STORE.forget_user",
                         "PUSH_STORE.forget_user", "delete_customer"):
            self.assertIn(städning, radering,
                          f"policyn lovar att raderingen tar {städning} - det gör den inte")

    def test_sparrens_rader_ar_undantaget_och_policyn_sager_det(self):
        """Fyra lager har `forget_user` och städas av raderingen. `ratelimit.py`
        har ingen, så spärrens rader - IP och inskriven e-postadress - ligger
        kvar tills de prunas. Policyn kallar dem uttryckligen undantaget.

        Byggs en `forget_user` för spärren är den meningen inte längre sann,
        och då ska den bort. Därför vänds testet om den dyker upp."""
        spärr = (ROOT / "backend/services/accounts/ratelimit.py").read_text(encoding="utf-8")
        städas = "def forget_user" in spärr
        läst = brodtext(POLICY)
        mening = "de enda uppgifter om dig som inte försvinner i samma ögonblick som du raderar kontot"
        if städas:
            self.assertNotIn(mening, läst,
                             "ratelimit.py har fått en forget_user - spärrens rader är inte "
                             "längre undantaget, och policyn ska sluta påstå det")
        else:
            for lager in ("household/store.py", "push/store.py", "billing/savings.py"):
                self.assertIn("def forget_user", (ROOT / "backend/services" / lager).read_text(encoding="utf-8"),
                              f"{lager} städas inte längre vid radering - policyn lovar att den gör det")
            self.assertIn(mening, läst,
                          "spärrens rader överlever kontoraderingen och policyn säger det inte")

    def test_exporten_innehaller_det_policyn_raknar_upp(self):
        export = (ROOT / "backend" / "services" / "accounts" / "data_export.py").read_text(encoding="utf-8")
        träff = re.search(r"CATEGORIES\s*=\s*\(([^)]*)\)", export)
        self.assertIsNotNone(träff, "data_export.CATEGORIES finns inte längre")
        kategorier = re.findall(r'"([^"]+)"', träff.group(1))
        läst = brodtext(POLICY)
        svenska = {"konto": "kontot", "syncedState": "synkade tillståndet", "hushall": "hushållet",
                   "skafferi": "skafferiet", "lista": "listan", "analytics": "produktstatistiken",
                   "prenumeration": "prenumerationen"}
        for kategori in kategorier:
            ord = svenska.get(kategori)
            self.assertIsNotNone(ord, f"exporten har kategorin {kategori} som policyn inte räknar upp")
            self.assertIn(ord, läst, f"policyns utdrag nämner inte {ord} ({kategori})")

    def test_policyn_sager_sanningen_om_att_byta_e_postadress(self):
        """Vägen finns i API:t men har ingen knapp i appen. Policyn säger
        därför 'mejla oss'. Byggs knappen ska den meningen bytas ut."""
        app = (ROOT / "frontend" / "app").rglob("*.js")
        markup = (ROOT / "frontend" / "app" / "index.html").read_text(encoding="utf-8")
        i_ui = "auth/change-email" in markup or any(
            "auth/change-email" in fil.read_text(encoding="utf-8") for fil in app)
        läst = brodtext(POLICY)
        if i_ui:
            self.assertNotIn("går ännu inte att byta i appen", läst,
                             "appen kan byta e-postadress nu - policyn påstår motsatsen")
        else:
            self.assertIn("går ännu inte att byta i appen", läst,
                          "e-postadressen går inte att byta i appen, och policyn ska säga det")

    def test_villkoren_pekar_pa_policyn_och_pa_arn(self):
        läst = text(VILLKOR)
        self.assertIn('href="integritetspolicy.html"', läst,
                      "villkoren hänvisar inte till integritetspolicyn")
        self.assertIn("arn.se", läst,
                      "en konsumenttjänst ska upplysa om Allmänna reklamationsnämnden")


class KansligaUppgifterArHanterade(unittest.TestCase):
    """Allergier och kosttyp är artikel 9-uppgifter. De lagras i
    users.synced_state och i hushållsprofilen - alltså ska policyn både
    nämna dem och ange att grunden är uttryckligt samtycke."""

    def test_policyn_behandlar_allergier_som_artikel_9(self):
        profil = (ROOT / "backend" / "services" / "household" / "store.py").read_text(encoding="utf-8")
        self.assertIn("allergies", profil, "hushållsprofilen sparar inte längre allergier")
        läst = brodtext(POLICY)
        self.assertIn("artikel 9", läst, "policyn placerar inte allergiuppgifterna under artikel 9")
        self.assertIn("uttryckligen", läst, "policyn anger inte uttryckligt samtycke som grund")


if __name__ == "__main__":
    unittest.main()
