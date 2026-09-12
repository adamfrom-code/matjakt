"""Signeringsnycklarna för iOS kan inte committas av misstag.

En `.p8`-nyckel från App Store Connect ger den som har den rätt att ladda
upp byggen i Adams namn. Apple visar nyckeln **en gång**, vid nedladdningen,
och den går inte att hämta igen - en läckt nyckel måste återkallas, inte
roteras tyst.

Filen hamnar i reporoten av ren bekvämlighet: den laddas ner till
~/Downloads och dras in i projektmappen för att `xcodebuild
-authenticationKeyPath` ska hitta den. Det är precis det ögonblicket det
här testet finns för.

Testet gör tre saker. Det kontrollerar att mönstren står i .gitignore, att
git faktiskt ignorerar en fil med sådant namn, och att ingen sådan fil
redan är spårad - .gitignore skyddar inte en fil som redan ligger i indexet.

`ExportOptions.plist` står medvetet INTE på listan. Den innehåller team-ID,
och team-ID syns i varje utgiven .ipa - det är ingen hemlighet. Filen ska
gå att klona med, annars får den som bygger gissa sig till innehållet.

Mönstren överlappar med flit: stryker någon `*.p8` fångas AuthKey-filen
ändå av `AuthKey_*`. Därför fäller ett saknat mönster bara listtestet, inte
check-ignore-testet.
"""

import subprocess
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]

# Mönstret, och vad det skyddar mot.
MÖNSTER = {
    "*.p8": "App Store Connect-API-nyckeln",
    "AuthKey_*": "samma nyckel under Apples eget filnamn",
    "*.mobileprovision": "provisioneringsprofiler",
    "*.p12": "exporterade signeringscertifikat med privat nyckel",
    "*.cer": "signeringscertifikat",
}


class Signeringshemligheter(unittest.TestCase):
    def test_gitignore_har_varje_monster(self):
        rader = {
            rad.strip()
            for rad in (ROT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if rad.strip() and not rad.strip().startswith("#")
        }
        saknas = {m: v for m, v in MÖNSTER.items() if m not in rader}
        self.assertFalse(
            saknas,
            "dessa mönster saknas i .gitignore: "
            + ", ".join(f"{m} ({v})" for m, v in saknas.items()),
        )

    def test_git_ignorerar_filen_pa_riktigt(self):
        """Fråga git, inte oss själva, om mönstret biter."""
        for namn in ("AuthKey_ABC123XYZ.p8", "AuthKey_ABC123XYZ.txt", "matjakt.p12"):
            with self.subTest(namn=namn):
                svar = subprocess.run(
                    ["git", "check-ignore", "-q", namn],
                    cwd=ROT,
                    capture_output=True,
                )
                self.assertEqual(
                    svar.returncode, 0, f"git skulle inte ignorera {namn} i reporoten"
                )

    def test_ingen_signeringshemlighet_ar_sparad(self):
        """.gitignore skyddar inte en fil som redan ligger i indexet."""
        spårade = subprocess.run(
            ["git", "ls-files"],
            cwd=ROT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()

        farliga = [
            f
            for f in spårade
            if f.endswith((".p8", ".mobileprovision", ".p12", ".cer"))
            or Path(f).name.startswith("AuthKey_")
        ]
        self.assertFalse(farliga, f"signeringshemligheter ligger i git: {farliga}")


if __name__ == "__main__":
    unittest.main()
