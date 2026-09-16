# -*- coding: utf-8 -*-
"""En receptsanning. Reservbanken är byggd ur källorna, inte skriven bredvid.

P03a. Appens reservbank (frontend/app/data/recipes.json) visas när backenden
inte svarar - eller svarar med en tom lista. Den bar 58 handredigerade
recept i appens egen form, och ALLA 58 skilde sig från källorna: kcal upp
till 271 fel (chili-sin-carne-budget 179 mot 450), 200 °C där källan säger
175 (ugnslax-citron), fläskkarré där källan säger fläskfilé (flaskkarre),
sex ingrediensrader där receptet har tio (kottbullar-potatismos). Samma id,
två sanningar, och den felaktiga var den som visades vid ett avbrott.

Nu genereras filen av backend/scripts/generate_recipe_fallback.py: samma
importslinga som servern, in i en riktig RecipeStore, ut genom samma
_to_dict som /api/recipes. Testerna nedan är grinden:

  1. FILEN ÄR GENERERAD UR DAGENS KÄLLOR. Byte för byte. Ändras en källa
     utan att filen byggs om blir CI röd - med kommandot i meddelandet.
  2. FILEN ÄR API-FORMEN. Har den `namn` i stället för `name` har någon
     handredigerat den tillbaka, och då hoppar den över fromApi() igen.
  3. VARJE RECEPT ÄR MED, OCH VARJE FAKTUM STÄMMER. Namn, portioner, kcal,
     protein, antal steg, antal ingredienser - mot källfilen, per id.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

ROOT = Path(__file__).resolve().parents[2]
RESERVBANK = ROOT / "frontend" / "app" / "data" / "recipes.json"
KÄLLOR = ROOT / "backend" / "recipe_sources"
SKRIPT = ROOT / "backend" / "scripts" / "generate_recipe_fallback.py"


def _ladda_skript():
    spec = importlib.util.spec_from_file_location("generate_recipe_fallback", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _källorna() -> dict:
    per_id = {}
    for path in sorted(KÄLLOR.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(r, dict) and r.get("id"):
                per_id[r["id"]] = r
    return per_id


class ReservbankenArGenereradUrKallorna(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skript = _ladda_skript()
        cls.text = RESERVBANK.read_text(encoding="utf-8")
        cls.bank = json.loads(cls.text)
        cls.källor = _källorna()

    def test_filen_stammer_byte_for_byte_med_generatorn(self):
        """Grinden. Källorna är sanningen; filen är ett byggresultat av dem."""
        väntad = self.skript.rendera(self.skript.bygg())
        self.assertEqual(
            self.text, väntad,
            "frontend/app/data/recipes.json är inte genererad ur dagens källor. "
            "Kör: python backend/scripts/generate_recipe_fallback.py",
        )

    def test_check_flaggan_sager_samma_sak(self):
        """Det är --check CI faktiskt kör; den ska vara identisk med testet ovan."""
        self.assertEqual(self.skript.main(["--check"]), 0)

    def test_filen_ar_api_formen_inte_appens(self):
        for r in self.bank[:5]:
            self.assertIn("name", r)
            self.assertIn("servings", r)
            self.assertIn("nutrition", r)
            self.assertNotIn("namn", r, "reservbanken har handredigerats tillbaka till appens form")
            self.assertNotIn("portioner", r)

    def test_inga_pahittade_falt(self):
        """De gamla reservrecepten bar butik, sparar och emoji - påhittade
        värden ur ingen källa ("Spara ca 26 kr" hos ICA). Såna får inte
        finnas: de ser ut som pris- och butiksdata och är det inte."""
        for r in self.bank:
            for fält in ("butik", "sparar", "emoji", "inkopspris", "portionspris"):
                self.assertNotIn(fält, r, f"{r['id']} bär det påhittade fältet {fält!r}")

    def test_varje_kallrecept_ar_med_exakt_en_gang(self):
        ids = [r["id"] for r in self.bank]
        self.assertEqual(len(ids), len(set(ids)), "dubbla id i reservbanken")
        self.assertEqual(set(ids), set(self.källor), "reservbanken och källorna har olika id-mängder")
        self.assertGreater(len(ids), 200)

    def test_varje_faktum_stammer_med_kallan(self):
        """Per recept: det en människa handlar och äter efter."""
        fel = []
        for r in self.bank:
            k = self.källor[r["id"]]
            kn = k.get("nutrition") or {}
            par = [
                ("name", r.get("name"), k.get("name")),
                ("servings", r.get("servings"), k.get("servings")),
                ("kcal", (r.get("nutrition") or {}).get("kcal"), kn.get("kcal")),
                ("protein", (r.get("nutrition") or {}).get("protein"), kn.get("protein")),
                ("mealType", r.get("mealType"), k.get("mealType")),
                ("steg", len(r.get("instructions") or []), len(k.get("instructions") or [])),
                ("ingredienser", len(r.get("ingredients") or []), len(k.get("ingredients") or [])),
                ("totalTime", r.get("totalTime"), (k.get("prepTime") or 0) + (k.get("cookTime") or 0)),
            ]
            for namn, a, b in par:
                if a != b:
                    fel.append(f"{r['id']}.{namn}: reservbank={a!r} källa={b!r}")
        self.assertEqual(fel, [], "\n" + "\n".join(fel[:20]))

    def test_de_kanda_avvikelserna_ar_borta(self):
        """De konkreta felen ur auditen, som regressionsvakt."""
        by = {r["id"]: r for r in self.bank}
        self.assertEqual(by["kottbullar-potatismos"]["nutrition"]["kcal"], 640)
        self.assertEqual(by["chili-sin-carne-budget"]["nutrition"]["kcal"], 450)
        self.assertEqual(by["flaskkarre"]["name"], "Fläskfilé med äppelmos och rödkål")
        steg = " ".join(by["ugnslax-citron"]["instructions"])
        self.assertIn("175", steg)
        self.assertNotIn("200°", steg)

    def test_generatorn_ar_deterministisk(self):
        """Två körningar av samma källor -> samma bytes. Annars blir varje
        CI-körning en diff, och ingen ser den riktiga ändringen."""
        self.assertEqual(self.skript.rendera(self.skript.bygg()),
                         self.skript.rendera(self.skript.bygg()))

    def test_volatila_falt_ar_borta(self):
        for r in self.bank[:10]:
            for fält in self.skript.VOLATILA:
                self.assertNotIn(fält, r)


if __name__ == "__main__":
    unittest.main()
