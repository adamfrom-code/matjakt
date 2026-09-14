"""Ett deployjobb som inte deployar får inte vara grönt.

Backenden stod stilla i fjorton timmar med nio mergade commits bakom sig.
Ingen larmade, för jobbet som heter "Deploy backend till Render" skrev en
notis och `exit 0` när RENDER_DEPLOY_HOOK saknades - med motiveringen att
"Renders egen Auto-Deploy gör jobbet i stället".

Den motiveringen var falsk, och render.yaml sa hela tiden motsatsen:

    # Deploy sker BARA via deploy-hooken från GitHub CI - aldrig direkt på
    # push. Måste också vara Off i dashboarden; det här gör att en
    # blueprint-synk inte slår på det igen.
    autoDeploy: false

Två filer som säger emot varandra, och den som ljög var den som körde. Det
var inte hälsogrinden som var trasig - den var det enda som upptäckte det.

Testet vaktar SAMBANDET, inte texten: så länge render.yaml stänger av
autoDeploy måste hooken vara enda vägen, och saknas den ska bygget bli rött
med en gång. Slår någon på autoDeploy i render.yaml faller testet också -
med flit, för då måste beslutet tas medvetet och kommentarerna skrivas om.
"""

import re
import unittest
from pathlib import Path

ROT = Path(__file__).resolve().parents[2]
CI = (ROT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
RENDER = (ROT / "render.yaml").read_text(encoding="utf-8")


def _jobb(namn: str) -> str:
    """Kroppen av ett jobb i ci.yml, fram till nästa jobb på samma nivå."""
    start = CI.index(f"\n  {namn}:")
    nästa = re.search(r"\n  [a-z][a-z0-9-]*:\n", CI[start + 1:])
    return CI[start:start + 1 + nästa.start()] if nästa else CI[start:]


class DeployJobbetMasteFaktisktDeploya(unittest.TestCase):
    def test_render_deployar_inte_av_sig_sjalvt(self):
        """Premissen för allt nedan. Ändras den ska testet falla."""
        värden = re.findall(r"^\s*autoDeploy:\s*(\S+)\s*$", RENDER, re.M)
        self.assertTrue(värden, "render.yaml har ingen autoDeploy-nyckel alls")
        for v in värden:
            self.assertEqual(
                v, "false",
                "render.yaml slår på autoDeploy. Då är hooken inte längre enda "
                "vägen, och kommentarerna i ci.yml och render.yaml måste skrivas "
                "om innan det här testet lättas.",
            )

    def test_saknad_hook_gor_bygget_rott(self):
        """Ingen hook + ingen autoDeploy = ingen deploy. Det ska synas."""
        jobb = _jobb("deploy-backend")
        self.assertIn("RENDER_DEPLOY_HOOK", jobb)
        gren = jobb[jobb.index('if [ -z "$RENDER_DEPLOY_HOOK" ]'):]
        gren = gren[:gren.index("fi")]
        self.assertIn(
            "exit 1", gren,
            "deploy-backend avslutar med exit 0 när hooken saknas. Då är jobbet "
            "grönt utan att ha deployat något, och ingen ser att backenden står "
            "stilla - det tog fjorton timmar att upptäcka förra gången.",
        )
        self.assertNotIn(
            "::notice::", gren,
            "en saknad deploy-hook är inte en notis, den är ett fel",
        )

    def test_felmeddelandet_sager_vad_man_ska_gora(self):
        """En röd bock utan åtgärd är bara en röd bock."""
        gren = _jobb("deploy-backend")
        gren = gren[gren.index('if [ -z "$RENDER_DEPLOY_HOOK" ]'):]
        for ledtråd in ("Deploy Hook", "RENDER_DEPLOY_HOOK", "Settings"):
            self.assertIn(ledtråd, gren, f"felmeddelandet nämner inte {ledtråd!r}")

    def test_ingen_pastar_langre_att_render_deployar_sjalv(self):
        """Kommentaren som gjorde felet osynligt."""
        # "After CI Checks Pass" är Renders namn på autoDeploy. Står det i
        # ci.yml som ett PÅSTÅENDE om dagens läge motsäger det render.yaml.
        for rad in CI.splitlines():
            if "After CI Checks Pass" in rad and "påslaget" in rad:
                self.fail(
                    f"ci.yml påstår att Auto-Deploy är påslaget: {rad.strip()!r}. "
                    "render.yaml säger autoDeploy: false på båda tjänsterna."
                )


if __name__ == "__main__":
    unittest.main()
