# -*- coding: utf-8 -*-
"""Z1: "Vad kan vi äta nu" - receptsök på ingredienser man har.

`RecipeStore.search(ingredients_any=[...])` ger recepten som innehåller
NÅGON av ingredienserna, flest träffar först, och varje träff säger vilka
(`matchedIngredients`). Sökorden löses mot det kanoniska lagret (P05a):
"tomater" och "tomat", "lök" och "gul lök" är samma fråga - registrets
alias, aldrig fuzzy. Okända ord ger inga träffar, inte alla recept.
Vägen: GET /api/recipes?ingredient=lök&ingredient=tomat&maxTime=25.
"""

import http.client
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

import api_server  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.store import RecipeStore, ingredient_query_ids  # noqa: E402


def _recept(rid, namn, ingredienser, tid=20):
    return {"id": rid, "name": namn, "description": "", "servings": 4, "prepTime": 0, "cookTime": tid, "totalTime": tid,
            "difficulty": "lätt", "tags": [], "categories": [], "dietFlags": [], "allergens": [],
            "instructions": ["Laga."], "nutrition": {"kcal": 500, "protein": 20, "carbs": 40, "fat": 15, "fiber": 4},
            "ingredients": [{"name": n, "amount": 1, "unit": "st"} for n in ingredienser]}


class Lagret(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.store = RecipeStore(Path(self.tmp.name) / "r.db")
        self.addCleanup(self.store.close)
        self.store.upsert_recipe(_recept("a", "Tomatsoppa", ["Tomater", "Gul lök", "Grädde"], tid=25))
        self.store.upsert_recipe(_recept("b", "Kycklinggryta", ["Kyckling", "Lök", "Ris"], tid=40))
        self.store.upsert_recipe(_recept("c", "Fiskpinnar", ["Fiskpinnar", "Potatis"], tid=15))

    def sok(self, *ingredienser, **kw):
        return [(r["id"], r.get("matchedIngredients")) for r in self.store.search(ingredients_any=list(ingredienser), **kw)]

    def test_nagon_av_ingredienserna_flest_traffar_forst(self):
        self.assertEqual(self.sok("tomat"), [("a", ["Tomater"])])
        self.assertEqual(self.sok("tomat", "lök"), [("a", ["Tomater", "Gul lök"]), ("b", ["Lök"])])
        # Lika många träffar: namnordning
        self.assertEqual([rid for rid, _ in self.sok("lök")], ["b", "a"])

    def test_registrets_alias_ar_samma_fraga(self):
        self.assertEqual(self.sok("tomater"), self.sok("tomat"))
        self.assertEqual([rid for rid, _ in self.sok("gul lök")], [rid for rid, _ in self.sok("lök")])
        self.assertIn("gul-lok", ingredient_query_ids(["lök"]))
        self.assertIn("tomater", ingredient_query_ids(["tomat"]))

    def test_okant_ord_ger_ingenting_inte_allt(self):
        self.assertEqual(self.sok("drakfruktsnektar"), [])
        self.assertEqual(self.sok(""), [])
        self.assertEqual(ingredient_query_ids(["", None]), [])
        # ...och utan ingredienser är sökningen som förut (alla, utan fältet)
        alla = self.store.search()
        self.assertEqual(len(alla), 3)
        self.assertNotIn("matchedIngredients", alla[0])

    def test_tiden_filtrerar_ihop_med_ingredienserna(self):
        self.assertEqual([rid for rid, _ in self.sok("lök", max_time=30)], ["a"])


class Vagen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recipes_api.bootstrap_if_empty()
        recipes_api.clear_cache()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=5)

    def get(self, path):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            con.request("GET", path)
            r = con.getresponse()
            import json
            return r.status, json.loads(r.read())
        finally:
            con.close()

    def test_vagen_svarar_med_traffarna_ur_banken(self):
        status, svar = self.get("/api/recipes?ingredient=l%C3%B6k&limit=10")
        self.assertEqual(status, 200)
        self.assertGreater(len(svar["recipes"]), 0)
        for r in svar["recipes"]:
            self.assertTrue(r.get("matchedIngredients"), r["id"])
        # Alias: samma svar för tomat och tomater
        a = self.get("/api/recipes?ingredient=tomat&limit=50")[1]["recipes"]
        b = self.get("/api/recipes?ingredient=tomater&limit=50")[1]["recipes"]
        self.assertEqual([r["id"] for r in a], [r["id"] for r in b])
        self.assertGreater(len(a), 0)
        # Tid: inget över gränsen
        snabba = self.get("/api/recipes?ingredient=l%C3%B6k&maxTime=20&limit=50")[1]["recipes"]
        self.assertTrue(all((r["totalTime"] or 0) <= 20 for r in snabba))
        # Okänt: tomt, inte hela banken
        self.assertEqual(self.get("/api/recipes?ingredient=drakfruktsnektar")[1]["recipes"], [])


if __name__ == "__main__":
    unittest.main()
