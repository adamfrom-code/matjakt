"""Ingen utgående förbindelse i klartext.

Postnumret gick till `http://api.zippopotam.us/SE/<postnummer>`. Det är en
personuppgift, och den låg i SÖKVÄGEN - inte i en kropp. Över en okrypterad
förbindelse är den läsbar för varje mellanled, och sökvägen hamnar dessutom
i proxyloggar som aldrig loggar request-kroppar.

Ingen kommentar förklarade varför det var http. Tjänsten svarar likadant på
https - samma data, samma 404 för okänt postnummer - så det fanns aldrig
något skäl. Raden såg bara aldrig efter.

Hittad när integritetspolicyn skrevs om mot koden (I3): stycket "källor som
aldrig får något om dig" listade Primat, medan `primat_client` skickar
postnumret och ICA:s butikssök anropas med `?zip=`. Zippopotam var den
tredje mottagaren, och den enda som fick det i klartext.

Testet läser bara SPÅRADE filer, så backend/venv och node_modules räknas
inte - de är inte vår kod, och de går inte att rätta här.
"""

import re
import subprocess
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]

# Värdar som aldrig lämnar maskinen. Utvecklingsservern och dess utskrifter
# behöver ingen TLS, och ett certifikat för 127.0.0.1 finns inte.
# Inget \b på slutet: {HOST} slutar på } och följs av :, två icke-ordtecken,
# och där finns ingen ordgräns - mönstret matchade aldrig.
LOKALA = re.compile(r"^http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\{HOST\}|\$\{HOST\})")

# Namnrymder och specifikations-URI:er är identifierare, inte anrop. De
# HÄMTAS aldrig; de jämförs som strängar, och byter man https mot http i en
# XML-namnrymd slutar dokumentet validera.
IDENTIFIERARE = re.compile(
    r"^http://(?:www\.w3\.org|www\.sitemaps\.org|schemas?\.|purl\.org"
    r"|ns\.adobe\.com|www\.apple\.com/DTDs)"
)

# .example, .test, .invalid och .localhost är reserverade av RFC 2606 och
# löses aldrig upp. Testfixturer använder dem MED FLIT för att en adress
# ska vara osäker och oanropbar - att kräva https där vore att kräva TLS
# av något som aldrig kontaktas.
RESERVERADE = re.compile(r"^http://[^/\s]*\.(?:example|test|invalid|localhost)(?:[:/]|$)")

GRANSKADE = (".py", ".js", ".mjs", ".html", ".json", ".yml", ".yaml")


def spårade_filer():
    ut = subprocess.run(
        ["git", "ls-files"], cwd=ROT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [f for f in ut if f.endswith(GRANSKADE)]


class UtgåendeIKlartext(unittest.TestCase):
    def test_ingen_http_url_till_en_tredjepart(self):
        träffar = []
        for rel in spårade_filer():
            try:
                text = (ROT / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for nummer, rad in enumerate(text.splitlines(), 1):
                for m in re.finditer(r"http://[^\s\"'`<>)\\]+", rad):
                    url = m.group(0)
                    if LOKALA.match(url) or IDENTIFIERARE.match(url) or RESERVERADE.match(url):
                        continue
                    träffar.append(f"{rel}:{nummer}  {url}")
        self.assertEqual(
            träffar,
            [],
            "utgående förbindelse i klartext:\n  "
            + "\n  ".join(träffar)
            + "\n  Byt till https. Är värden bara en identifierare och inte ett "
            "anrop, lägg den i IDENTIFIERARE med ett skäl.",
        )

    def test_postnummeruppslaget_gar_over_https(self):
        """Den konkreta raden, utöver den generella spärren."""
        källa = (ROT / "backend" / "api_server.py").read_text(encoding="utf-8")
        self.assertIn("https://api.zippopotam.us/SE/", källa)
        self.assertNotIn("http://api.zippopotam.us", källa)


if __name__ == "__main__":
    unittest.main()
