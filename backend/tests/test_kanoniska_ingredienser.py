# -*- coding: utf-8 -*-
"""P05a: det kanoniska ingredienslagret.

Grinderna, i den ordning de spelar roll:
  1. TÄCKNING. Varje ingrediens i varje recept löser till en kanonisk post.
     Ett recept som pekar på ingenting kan varken handlas eller prissättas.
  2. DRIFT. Datafilens id ∪ alias == receptbankens id, exakt. Ett nytt
     ingrediensnamn i ett recept utan post här blir röd CI - inte ett
     tyst "Pris saknas" i produktion.
  3. INGEN GISSNING. Okänt namn -> None. Omvandling utan källa -> None.
     Ingen omvandling mellan familjer.
  4. EN VOKABULÄR. Enhetsfamiljerna är prissättningens, och frontendens
     UNIT_TO_BASE säger samma sak. Slug-härledningen är identisk med
     recipes.store.normalize_ingredient_id.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.ingredients import canonical as kan  # noqa: E402
from services.grocery.pricing import convert_amount  # noqa: E402
from services.recipes.pantry import is_pantry_staple  # noqa: E402
from services.recipes.store import normalize_ingredient_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KÄLLOR = ROOT / "backend" / "recipe_sources"


def _receptingredienser():
    for path in sorted(KÄLLOR.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            for i in r.get("ingredients") or []:
                yield r["id"], i


class Tackning(unittest.TestCase):
    def test_varje_receptingrediens_loser_till_en_kanonisk_post(self):
        saknas = sorted({i["name"] for _, i in _receptingredienser() if kan.resolve(i["name"]) is None})
        self.assertEqual(saknas, [], f"ingredienser utan kanonisk post: {saknas}")

    def test_datafilen_ar_exakt_receptbankens_id(self):
        """Drift åt båda hållen: en död post är lika fel som en saknad."""
        i_recepten = {normalize_ingredient_id(i["name"]) for _, i in _receptingredienser()}
        i_filen = set(kan.ladda()) | set(kan._aliasindex())
        self.assertEqual(sorted(i_recepten - i_filen), [], "id i recepten som saknar post")
        self.assertEqual(sorted(i_filen - i_recepten), [], "poster/alias som inget recept använder")

    def test_minst_tvahundra_poster(self):
        self.assertGreater(len(kan.ladda()), 190)


class Alias(unittest.TestCase):
    def test_de_sex_aliasen(self):
        for a, k in (("tomat", "tomater"), ("lök", "gul-lok"), ("Soja", "sojasas"),
                     ("feta", "fetaost"), ("tortilla", "tortillabrod"), ("peppar", "svartpeppar")):
            self.assertEqual(kan.canonical_id(a), k, a)

    def test_ett_alias_ar_aldrig_ocksa_en_post(self):
        for a in kan._aliasindex():
            self.assertNotIn(a, kan.ladda(), f"{a} är både alias och egen post")

    def test_namn_med_accent_och_id_utan_ger_samma(self):
        self.assertIs(kan.resolve("Kycklingfilé"), kan.resolve("kycklingfile"))
        self.assertIs(kan.resolve("Crème fraiche"), kan.resolve("creme-fraiche"))

    def test_liknande_text_ar_inte_samma_produkt(self):
        """Regel 1. De här ska INTE vara alias - olika produkt, olika pris."""
        for a, b in (("grädde", "vispgrädde"), ("olja", "olivolja"), ("ris", "jasminris"),
                     ("kycklingfilé", "kycklinglårfilé"), ("köttfärs", "nötfärs"),
                     ("yoghurt", "grekisk yoghurt"), ("buljong", "buljongtärning")):
            ka, kb = kan.resolve(a), kan.resolve(b)
            if ka is None or kb is None:
                continue  # finns inte båda i banken - då finns inget att blanda ihop
            self.assertIsNot(ka, kb, f"{a!r} och {b!r} har slagits ihop")


class IngenGissning(unittest.TestCase):
    def test_okant_namn_ger_none(self):
        self.assertIsNone(kan.resolve("enhörningsfilé"))
        self.assertIsNone(kan.resolve(""))
        self.assertIsNone(kan.resolve(None))

    def test_omvandling_utan_kalla_ar_ingen_omvandling(self):
        k = kan.Kanonisk(id="x", namn="x", omvandling={"g_per_st": 60})
        self.assertIsNone(k.g_per_st(), "ett tal utan källa är en gissning")
        k2 = kan.Kanonisk(id="x", namn="x", omvandling={"g_per_st": 60, "kalla": "vägd 2026-09-16"})
        self.assertEqual(k2.g_per_st(), 60.0)

    def test_datafilen_bar_inga_tal_utan_kalla(self):
        for k in kan.alla():
            if k.omvandling:
                self.assertIn("kalla", k.omvandling, f"{k.id}: omvandling utan källa")

    def test_ingen_omvandling_over_familjegrans(self):
        """De historiska felen. 224 g fiskpinnar blev 224 paket och 6 561 kr."""
        self.assertIsNone(convert_amount(224, "g", "st"))
        self.assertIsNone(convert_amount(10, "g", "st"))     # persilja
        self.assertIsNone(convert_amount(2, "st", "g"))      # morötter
        self.assertIsNone(convert_amount(1, "msk", "g"))     # tomatpuré
        self.assertEqual(convert_amount(2, "dl", "ml"), 200.0)


class EnVokabular(unittest.TestCase):
    def test_slug_ar_identisk_med_recipes_store(self):
        for namn in ("Kycklingfilé", "Crème fraiche", "Gul lök", "Ägg", "Sötpotatis", "  Salt ", "Vispgrädde 40%"):
            self.assertEqual(kan._slug(namn), normalize_ingredient_id(namn), namn)

    def test_enhetsfamiljerna_ar_prissattningens(self):
        for u, fam in (("g", "massa"), ("kg", "massa"), ("ml", "volym"), ("dl", "volym"),
                       ("msk", "volym"), ("tsk", "volym"), ("st", "antal"), ("klyfta", "antal")):
            self.assertEqual(kan.unit_family(u), fam, u)
        self.assertIsNone(kan.unit_family(None))
        self.assertIsNone(kan.unit_family("hink"))

    def test_frontendens_unit_to_base_sager_samma_sak(self):
        """Tre definitioner av samma sak är två för mycket. Frontendens tabell
        läses ur källan och jämförs familj för familj."""
        js = (ROOT / "frontend" / "app" / "src" / "services" / "calculations.js").read_text(encoding="utf-8")
        block = js[js.index("const UNIT_TO_BASE = {"):js.index("};", js.index("const UNIT_TO_BASE = {"))]
        fam_js = {m.group(1): m.group(2) for m in re.finditer(r'(\w+):\s*\["(vol|vikt)",', block)}
        self.assertGreater(len(fam_js), 8)
        for enhet, f in fam_js.items():
            self.assertEqual(kan.unit_family(enhet), {"vol": "volym", "vikt": "massa"}[f],
                             f"{enhet}: frontend säger {f}, kanoniska lagret säger {kan.unit_family(enhet)}")

    def test_skafferiflaggan_ar_pantry_modulens(self):
        for k in kan.alla():
            self.assertEqual(k.skafferi, is_pantry_staple(k.namn), k.id)

    def test_standardenhetens_familj_stammer(self):
        for k in kan.alla():
            self.assertEqual(k.enhetsfamilj, kan.unit_family(k.standardenhet), k.id)


if __name__ == "__main__":
    unittest.main()
