# -*- coding: utf-8 -*-
"""K1: varje mönster i hemlighetsskannern måste kunna matcha sin hemlighet.

Ruff hittade sex LITERALA backsteg-tecken (0x08) i `backend/scripts/
secret_scan.py` där någon menat `\\b`. Fem av mönstren - GitHub-token,
AWS-nyckel, Anthropic/OpenAI-nyckel, Slack-token, Google-nyckel - krävde
alltså ett backsteg omedelbart före nyckeln, och ett backsteg står inte i en
källfil. De kunde ALDRIG matcha.

Det betyder att den grind som ska hindra en hemlighet från att nå det här
**publika** repot hade fem hål i sig, i ett repo som redan läckt
`MATJAKT_ADMIN_TOKEN` i klartext en gång. Skannern körde grön varje gång, för
en regex som aldrig matchar ser i loggen ut precis som en regex som inte
hittade något.

Det här är testet som gör att det inte kan hända igen: varje post i PATTERNS
prövas mot en hemlighet av just det slaget. Ett mönster som slutat matcha blir
rött i stället för tyst grönt.

INGA RIKTIGA HEMLIGHETER FINNS I DEN HÄR FILEN, och inga strängar som ser ut
som en. Varje exempel sätts ihop av delar vid körning, just för att skannern
läser den här filen också - ett testvärde som råkar matcha hade fällt bygget
på sitt eget test.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROT / "backend"))


def _ladda():
    sökväg = ROT / "backend" / "scripts" / "secret_scan.py"
    spec = importlib.util.spec_from_file_location("secret_scan", sökväg)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


skanner = _ladda()

B = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# Ett prov per mönster, hopsatt av delar. Formerna är kedjornas egna
# dokumenterade prefix och längder - inga riktiga nycklar.
PROV = {
    "stripe live key": "sk_" + "live_" + B[:24],
    "stripe test key": "sk_" + "test_" + B[:24],
    "stripe webhook secret": "whsec" + "_" + B[:32],
    "resend api key": "re" + "_" + B[:24],
    "privat nyckel": "-----BEGIN " + "PRIVATE KEY-----",
    "github token": "ghp" + "_" + B[:36],
    "aws access key": "AKI" + "A" + "BCDEFGHIJKLMNOPQ",
    "anthropic/openai key": "sk-" + "ant-" + B[:32],
    "slack token": "xox" + "b-" + B[:24],
    "google api key": "AIz" + "a" + B[:35],
    "ifylld hemlighet": 'PRIMAT_API_KEY = "' + B[:24] + '"',
}


class VarjeMonsterMatcharSinHemlighet(unittest.TestCase):
    """Grunden. Ett mönster som inte kan matcha är ingen grind."""

    def test_inget_monster_saknar_prov(self):
        # Lägger någon till ett mönster utan att lägga till ett prov är det
        # nya mönstret oprövat, och det var precis så de fem hålen uppstod.
        self.assertEqual(sorted(skanner.PATTERNS), sorted(PROV),
                         "ett mönster i PATTERNS saknar prov här (eller tvärtom)")

    def test_varje_monster_hittar_sin_egen_hemlighet(self):
        for namn, mönster in skanner.PATTERNS.items():
            with self.subTest(mönster=namn):
                self.assertIsNotNone(
                    mönster.search(PROV[namn]),
                    f"mönstret {namn!r} matchar inte ens en hemlighet av sitt eget slag - "
                    f"grinden är öppen och loggen ser grön ut")

    def test_inget_monster_bar_ett_literalt_styrtecken(self):
        # Felet i ren form. `\b` i en källfil som blivit 0x08 syns inte när
        # man läser koden, och regexen ser fullt rimlig ut i en diff.
        for namn, mönster in skanner.PATTERNS.items():
            with self.subTest(mönster=namn):
                styr = [tecken for tecken in mönster.pattern if ord(tecken) < 32 and tecken != "\n"]
                self.assertEqual(styr, [], f"{namn!r} innehåller ett literalt styrtecken "
                                           f"(ordinal {[ord(t) for t in styr]}) - menades \\b?")


class MonstretHittarHemligheten_MittIEnRad(unittest.TestCase):
    """Skannern läser rad för rad ur riktiga filer, inte rena strängar."""

    def test_en_nyckel_i_en_tilldelning_hittas(self):
        for namn, prov in PROV.items():
            if namn == "ifylld hemlighet":
                continue
            with self.subTest(mönster=namn):
                rad = f'    NYCKEL = "{prov}"  # klistrad av misstag'
                self.assertIsNotNone(skanner.PATTERNS[namn].search(rad), namn)

    def test_en_nyckel_i_ett_json_falt_hittas(self):
        for namn, prov in PROV.items():
            if namn in ("ifylld hemlighet", "privat nyckel"):
                continue
            with self.subTest(mönster=namn):
                self.assertIsNotNone(
                    skanner.PATTERNS[namn].search(f'{{"key": "{prov}"}}'), namn)


class AllowlistenTystarBaraFejkvarden(unittest.TestCase):
    """En allowlist som växer tyst blir en avstängd skanner."""

    def test_de_fejkvarden_sviten_anvander_slapps_igenom(self):
        for fejk in ("sk_" + "test_x", "whsec" + "_test", 'PRIMAT_API_KEY = "' + 'hemlig'):
            with self.subTest(fejk=fejk):
                self.assertIsNotNone(skanner.ALLOWLIST.search(fejk))

    def test_en_riktig_nyckel_slapps_inte_igenom(self):
        for namn, prov in PROV.items():
            with self.subTest(mönster=namn):
                self.assertIsNone(skanner.ALLOWLIST.search(prov),
                                  f"allowlisten tystar en riktig {namn}")


class SkannernAnvandsSomGrind(unittest.TestCase):
    def test_ci_kor_skannern(self):
        ci = (ROT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python backend/scripts/secret_scan.py", ci,
                      "hemlighetsskanningen körs inte i CI")

    def test_skannern_ar_gron_pa_repot_som_det_ser_ut_nu(self):
        # Kör den skarpt. Faller den här har någon committat en hemlighet -
        # och då ska sviten säga det innan CI gör det.
        self.assertEqual(skanner.main(), 0)


if __name__ == "__main__":
    unittest.main()
