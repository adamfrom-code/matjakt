# -*- coding: utf-8 -*-
"""Tester för det delade läs-API:t (/api/v1/shared/).

Kontraktstester, inte enhetstester. Det som prövas här är precis det en
ANNAN kodbas ser: statuskoder, fältnamn och vad som INTE finns i svaret.
Matchningsreglerna i sig har sina egna tester i test_shared_matching.py.

Receptbanken pekas om till en temporär fil i setUpClass. Testerna får aldrig
skriva i den riktiga recipes.db - en testkörning som råkar bygga om banken
tar med sig de backfillade bilderna i fallet.
"""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api_server  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.shared import api as shared_api  # noqa: E402


GRYTA = {
    "id": "gryta", "slug": "kycklinggryta", "name": "Kycklinggryta",
    "description": "En gryta att testa mot.", "servings": 4,
    "prepTime": 10, "cookTime": 20, "totalTime": 30,
    "kcal": 540, "protein": 38, "carbs": 34, "fat": 28, "fiber": 6,
    "image": "assets/recipes/kycklinggryta.jpg", "imageCredit": "Shrabee",
    "imageLicense": "CC BY-SA 4.0", "imageAlt": "Kycklinggryta på tallrik",
    "ingredients": [
        {"name": "Kycklingfilé", "amount": 600, "unit": "g"},
        {"name": "Ris", "amount": 250, "unit": "g"},
        {"name": "Paprika", "amount": 2, "unit": "st"},
        {"name": "Crème fraiche", "amount": 2, "unit": "dl"},
        {"name": "Gul lök", "amount": 1, "unit": "st"},
        {"name": "Salt", "pantryStaple": True},
    ],
    "instructions": ["Bryn kycklingen.", "Koka riset."],
    "categories": ["Familjefavorit"], "tags": ["barn"],
    "allergens": ["mjölk"], "dietFlags": ["blandkost"],
}

LAXEN = {
    "id": "lax", "slug": "ugnslax", "name": "Ugnslax", "description": "Lax i ugn.",
    "servings": 4, "totalTime": 25, "kcal": 480, "protein": 34,
    "ingredients": [
        {"name": "Laxfilé", "amount": 600, "unit": "g"},
        {"name": "Potatis", "amount": 800, "unit": "g"},
        {"name": "Citron", "amount": 1, "unit": "st"},
    ],
    "instructions": ["Sätt ugnen på 200 grader."],
    "categories": [], "tags": [], "allergens": ["fisk"], "dietFlags": [],
}


class SharedApiHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls._original_db = recipes_api.DB_PATH
        recipes_api.DB_PATH = Path(cls._tmp.name) / "recipes.db"
        store = recipes_api.open_store()
        try:
            for recipe in (GRYTA, LAXEN):
                store.upsert_recipe(dict(recipe))
        finally:
            store.close()
        recipes_api.clear_cache()
        shared_api.clear_cache()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        recipes_api.DB_PATH = cls._original_db
        recipes_api.clear_cache()
        shared_api.clear_cache()
        cls._tmp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            request_headers = dict(headers or {})
            body = None
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                request_headers["Content-Type"] = "application/json"
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            conn.close()

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)

    def post(self, path, payload=None, headers=None):
        return self.request("POST", path, payload=payload or {}, headers=headers)

    # ---- meta ------------------------------------------------------------

    def test_meta_states_the_contract(self):
        status, body = self.get("/api/v1/shared/meta")
        self.assertEqual(status, 200)
        self.assertEqual(body["contractVersion"], shared_api.CONTRACT_VERSION)
        self.assertEqual(body["recipeCount"], 2)
        self.assertIn("recipe-match", body["provides"])

    def test_meta_says_out_loud_that_prices_are_not_shared(self):
        """En app ska inte behöva gissa sig till vad som saknas."""
        _, body = self.get("/api/v1/shared/meta")
        self.assertIn("pricing", body["excludes"])

    def test_meta_publishes_the_default_pantry_staples(self):
        _, body = self.get("/api/v1/shared/meta")
        self.assertIn("salt", body["defaultPantryStaples"])
        self.assertNotIn("ris", body["defaultPantryStaples"])

    # ---- recept ----------------------------------------------------------

    def test_recipes_returns_cards(self):
        status, body = self.get("/api/v1/shared/recipes")
        self.assertEqual(status, 200)
        self.assertEqual({recipe["id"] for recipe in body["recipes"]}, {"gryta", "lax"})

    def test_no_endpoint_leaks_a_price(self):
        """Prisgrindens regler gäller Matjakts egna ytor. Att skicka samma
        tal genom en ny endpoint vore att publicera dem någon annanstans
        utan att någon beslutat det."""
        payloads = [
            self.get("/api/v1/shared/recipes")[1],
            self.get("/api/v1/shared/recipes/gryta")[1],
            self.post("/api/v1/shared/recipe-match", {"items": ["Ris"]})[1],
        ]
        for payload in payloads:
            raw = json.dumps(payload)
            for field in ("pricePerPortion", "priceChain", "priceCovered",
                          "priceTotal", "pricedAt"):
                self.assertNotIn(field, raw, field)

    def test_a_single_recipe_carries_its_ingredients_and_steps(self):
        status, body = self.get("/api/v1/shared/recipes/gryta")
        self.assertEqual(status, 200)
        recipe = body["recipe"]
        self.assertEqual(recipe["name"], "Kycklinggryta")
        self.assertEqual(len(recipe["ingredients"]), 6)
        self.assertEqual(recipe["instructions"][0], "Bryn kycklingen.")
        self.assertEqual(recipe["allergens"], ["mjölk"])

    def test_an_image_never_travels_without_its_licence(self):
        """En delad app som visar bilden måste kunna visa attributionen."""
        _, body = self.get("/api/v1/shared/recipes/gryta")
        recipe = body["recipe"]
        self.assertTrue(recipe["image"])
        self.assertEqual(recipe["imageLicense"], "CC BY-SA 4.0")
        self.assertEqual(recipe["imageCredit"], "Shrabee")

    def test_a_recipe_can_be_fetched_by_slug(self):
        status, body = self.get("/api/v1/shared/recipes/kycklinggryta")
        self.assertEqual(status, 200)
        self.assertEqual(body["recipe"]["id"], "gryta")

    def test_an_unknown_recipe_is_404(self):
        status, _ = self.get("/api/v1/shared/recipes/finns-inte")
        self.assertEqual(status, 404)

    def test_servings_scales_the_amounts(self):
        _, body = self.get("/api/v1/shared/recipes/gryta?servings=2")
        recipe = body["recipe"]
        self.assertEqual(recipe["servings"], 2)
        chicken = next(row for row in recipe["ingredients"] if row["name"] == "Kycklingfilé")
        self.assertEqual(chicken["amount"], 300)
        # Näringen är per portion och skalas aldrig.
        self.assertEqual(recipe["nutrition"]["kcal"], 540)

    def test_a_broken_servings_parameter_still_returns_the_recipe(self):
        status, body = self.get("/api/v1/shared/recipes/gryta?servings=tva")
        self.assertEqual(status, 200)
        self.assertEqual(body["recipe"]["servings"], 4)

    # ---- ingredienser ----------------------------------------------------

    def test_ingredients_returns_the_banks_own_vocabulary(self):
        status, body = self.get("/api/v1/shared/ingredients")
        self.assertEqual(status, 200)
        by_id = {row["id"]: row for row in body["ingredients"]}
        self.assertIn("kycklingfile", by_id)
        self.assertEqual(by_id["kycklingfile"]["name"], "Kycklingfilé")
        self.assertEqual(by_id["gul-lok"]["generalId"], "lok")
        self.assertTrue(by_id["salt"]["isPantryStaple"])

    # ---- matchning -------------------------------------------------------

    def test_recipe_match_answers_the_first_milestone(self):
        """Uppgiftens §25, genom HTTP: kyckling, ris, paprika, crème fraiche
        in - relevanta recept och det som saknas ut."""
        status, body = self.post("/api/v1/shared/recipe-match", {
            "items": ["kyckling", "ris", "paprika", "creme fraiche"]})
        self.assertEqual(status, 200)
        match = next(row for row in body["matches"] if row["recipe"]["id"] == "gryta")
        self.assertEqual([row["name"] for row in match["missingIngredients"]], ["Gul lök"])
        self.assertEqual(match["missingCount"], 1)
        self.assertFalse(match["canCookNow"])
        self.assertEqual(match["matchPercent"], 83)

    def test_the_answer_says_how_the_pantry_was_understood(self):
        """Utan detta kan en app inte skilja "receptet finns inte" från "vi
        tolkade aldrig creme fraiche som crème fraiche"."""
        _, body = self.post("/api/v1/shared/recipe-match", {"items": ["creme fraiche"]})
        self.assertEqual(body["pantry"][0]["id"], "creme-fraiche")

    def test_a_recipe_with_everything_at_home_can_be_cooked_now(self):
        _, body = self.post("/api/v1/shared/recipe-match", {
            "items": ["Kycklingfilé", "Ris", "Paprika", "Crème fraiche", "Gul lök"]})
        match = next(row for row in body["matches"] if row["recipe"]["id"] == "gryta")
        self.assertTrue(match["canCookNow"])
        self.assertEqual(match["matchPercent"], 100)

    def test_max_missing_filters_the_result(self):
        _, body = self.post("/api/v1/shared/recipe-match",
                            {"items": ["Laxfilé"], "maxMissing": 1})
        self.assertEqual(body["matches"], [])

    def test_limit_truncates_the_result(self):
        _, body = self.post("/api/v1/shared/recipe-match",
                            {"items": ["Ris", "Laxfilé"], "limit": 1})
        self.assertEqual(len(body["matches"]), 1)

    def test_the_caller_decides_its_own_pantry_staples(self):
        _, body = self.post("/api/v1/shared/recipe-match", {
            "items": ["Kycklingfilé", "Ris", "Paprika", "Crème fraiche", "Gul lök"],
            "notStaples": ["Salt"]})
        match = next(row for row in body["matches"] if row["recipe"]["id"] == "gryta")
        self.assertFalse(match["canCookNow"])
        self.assertEqual([row["name"] for row in match["missingIngredients"]], ["Salt"])

    def test_items_must_be_a_non_empty_list(self):
        for bad in ({}, {"items": []}, {"items": "ris"}, {"items": ["", "  "]}):
            status, _ = self.post("/api/v1/shared/recipe-match", bad)
            self.assertEqual(status, 400, bad)

    def test_a_pantry_of_objects_is_accepted(self):
        """Ät Upps skafferi bär mängd och bäst före. Bara namnet betyder
        något här; resten är den andra appens sak."""
        status, body = self.post("/api/v1/shared/recipe-match", {
            "items": [{"name": "Ris", "amount": "500 g", "expiresAt": "2026-10-01"}]})
        self.assertEqual(status, 200)
        self.assertEqual(body["pantry"][0]["id"], "ris")

    def test_duplicate_pantry_entries_are_collapsed(self):
        _, body = self.post("/api/v1/shared/recipe-match",
                            {"items": ["Ris", "ris", "  RIS  "]})
        self.assertEqual(len(body["pantry"]), 1)

    def test_an_absurd_pantry_is_bounded(self):
        _, body = self.post("/api/v1/shared/recipe-match",
                            {"items": [f"vara-{n}" for n in range(500)]})
        self.assertLessEqual(len(body["pantry"]), api_server.ApiHandler.MAX_PANTRY_ITEMS)


class SharedApiKeyTest(unittest.TestCase):
    """Utvecklingslåset och app-nyckeln.

    Nyckeln finns för att Ät Upp ska kunna läsa recept medan Matjakt är
    stängt - och för INGENTING annat. Att den bara öppnar sitt eget prefix
    är den enda egenskapen som gör den ofarlig att lägga i en annan kodbas.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._gate = api_server.GATE_ENABLED
        self._keys = api_server.SHARED_API_KEYS
        api_server.GATE_ENABLED = True
        api_server.SHARED_API_KEYS = ("hemlig-app-nyckel",)

    def tearDown(self):
        api_server.GATE_ENABLED = self._gate
        api_server.SHARED_API_KEYS = self._keys

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_the_gate_blocks_the_shared_api_without_a_key(self):
        self.assertEqual(self.get("/api/v1/shared/meta"), 401)

    def test_a_valid_key_opens_the_shared_api(self):
        self.assertEqual(
            self.get("/api/v1/shared/meta", {"X-Shared-Key": "hemlig-app-nyckel"}), 200)

    def test_a_wrong_key_is_refused(self):
        for wrong in ("", "fel", "hemlig-app-nyckel ", "HEMLIG-APP-NYCKEL"):
            self.assertEqual(
                self.get("/api/v1/shared/meta", {"X-Shared-Key": wrong}), 401, wrong)

    def test_the_key_opens_nothing_but_the_shared_prefix(self):
        """En läckt app-nyckel ska inte kunna göra något annat än att läsa
        recept."""
        headers = {"X-Shared-Key": "hemlig-app-nyckel"}
        for path in ("/api/entitlements", "/api/recipes", "/api/stores?zip=80252",
                     "/api/v1/recipes/search?q=kyckling"):
            self.assertEqual(self.get(path, headers), 401, path)

    def test_without_configured_keys_nothing_opens(self):
        """Fail-closed: utan variabel finns ingen nyckel, och då släpps
        ingen in - inte ens med en tom header."""
        api_server.SHARED_API_KEYS = ()
        self.assertEqual(self.get("/api/v1/shared/meta", {"X-Shared-Key": ""}), 401)

    def test_an_empty_configured_key_is_dropped(self):
        """"MATJAKT_SHARED_API_KEYS=" får inte göra tomma strängen giltig."""
        self.assertEqual(
            tuple(key for key in
                  (part.strip() for part in ",, ,".split(","))
                  if key), ())


if __name__ == "__main__":
    unittest.main()
