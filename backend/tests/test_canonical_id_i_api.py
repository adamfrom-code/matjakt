# -*- coding: utf-8 -*-
"""P05b: varje ingrediensrad ur /api/recipes bär sitt kanoniska id.

Länken RecipeIngredient -> CanonicalIngredient (P05a) fanns som register
men ingen läste det. Nu bär varje rad `canonicalId`, löst ur namnet - och
det är None för en okänd ingrediens, aldrig en gissning. Att ingen rad i
banken är okänd vaktas redan av P05a:s täckningstest; här vaktas att
länken faktiskt går hela vägen ut genom API-formen och in i reservbanken.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.ingredients import canonical_id, ladda  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.store import RecipeStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class CanonicalIdIApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        katalog = Path(isolated_test_data_dir())
        cls.store = RecipeStore(katalog / "p05b.db")
        recipes_api.import_sources(cls.store)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def test_varje_rad_bar_ett_kanoniskt_id_ur_registret(self):
        poster = ladda()
        utan, fel = [], []
        for row in self.store.connection.execute("SELECT id FROM recipes"):
            for i in self.store.get(row["id"])["ingredients"]:
                if i.get("canonicalId") is None:
                    utan.append(f"{row['id']}: {i['name']}")
                elif i["canonicalId"] not in poster:
                    fel.append(f"{row['id']}: {i['name']} -> {i['canonicalId']!r}")
        self.assertEqual(utan, [], f"rader utan canonicalId: {utan[:10]}")
        self.assertEqual(fel, [], f"canonicalId som inte finns i registret: {fel[:10]}")

    def test_alias_loses_till_det_kanoniska(self):
        """tomat och tomater, lök och gul lök - samma canonicalId på raden."""
        sedda = {}
        for row in self.store.connection.execute("SELECT id FROM recipes"):
            for i in self.store.get(row["id"])["ingredients"]:
                sedda.setdefault(i["normalizedId"], i["canonicalId"])
        for alias, kanon in (("tomat", "tomater"), ("lok", "gul-lok"), ("peppar", "svartpeppar")):
            if alias in sedda and kanon in sedda:
                self.assertEqual(sedda[alias], sedda[kanon], alias)
                self.assertEqual(sedda[alias], kanon)

    def test_okant_namn_ger_none_inte_en_gissning(self):
        self.assertIsNone(canonical_id("enhörningsfilé"))

    def test_reservbanken_bar_faltet(self):
        bank = json.loads((ROOT / "frontend" / "app" / "data" / "recipes.json").read_text(encoding="utf-8"))
        rader = [i for r in bank for i in r.get("ingredients") or []]
        self.assertGreater(len(rader), 1500)
        self.assertTrue(all("canonicalId" in i for i in rader), "reservbanken är inte omgenererad")
        self.assertTrue(all(i["canonicalId"] for i in rader))


if __name__ == "__main__":
    unittest.main()
