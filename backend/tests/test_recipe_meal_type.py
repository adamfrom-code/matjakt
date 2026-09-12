# -*- coding: utf-8 -*-
"""M1:s acceptanskriterium: VARJE recept vet vad det är till för.

Det som prövas här är inte att kolumnen finns - det är att den är TOTAL och
att veckoplaneringen faktiskt lyder den:

  * varje recept i den committade banken har ett `mealType` ur det stängda
    värdeförrådet (inte "de uppenbara och NULL på resten"),
  * ett värde utanför värdeförrådet går inte att spara,
  * `week_candidates()` returnerar aldrig något som inte är `middag`,
  * och det konkreta fallet: risgrynsgröten hamnar inte i en genererad vecka.

Banken läses ur `backend/recipe_sources/*.json` och byggs i en FIXTURKOPIA
under tempkatalogen. `data_guard.py` stoppar ett test som försöker öppna
`backend/data/recipes.db`, med rätta - men klassificeringen ska prövas mot de
riktiga 240 recepten, inte mot tre påhittade.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.recipes import RecipeStore, UnknownMealType  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.meal_types import DINNER, MEAL_TYPES  # noqa: E402

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
FALLBACK_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"
# Receptet uppdraget pekar ut vid namn. Både id och slug står här: id:t är
# vad koden använder, slug:en är vad en URL visar, och ett test som bara
# känner det ena missar dagen någon döper om det andra.
GROT_ID = "risgrynsgrot-lordag"
GROT_SLUG = "risgrynsgrot-med-kanel-och-apple"


def source_recipes() -> list[dict]:
    recipes = []
    for path in sorted(SOURCE_DIR.glob("*.json")):
        recipes.extend(json.loads(path.read_text(encoding="utf-8")))
    return recipes


class VarjeReceptVetVadDetArTillFor(unittest.TestCase):
    """`NULL` betyder i praktiken "kanske middag". Fältet är bara värt något
    om det är satt på ALLA."""

    def setUp(self):
        self.recipes = source_recipes()

    def test_banken_ar_inte_tom(self):
        # Ett test som läser noll filer passerar allt nedanför utan att pröva
        # någonting. 240 är dagens tal; gränsen är satt lågt med flit.
        self.assertGreaterEqual(len(self.recipes), 200)

    def test_varje_recept_har_ett_mealtype_ur_vardeforradet(self):
        saknas = [r.get("id") for r in self.recipes if r.get("mealType") is None]
        self.assertEqual(saknas, [], (
            f"{len(saknas)} recept saknar mealType. Kör "
            "backend/scripts/classify_recipe_meal_type.py --skriv."))
        okanda = sorted({r["mealType"] for r in self.recipes
                         if r["mealType"] not in MEAL_TYPES})
        self.assertEqual(okanda, [], f"Värden utanför värdeförrådet: {okanda}")

    def test_reservbanken_sager_samma_sak_som_kallorna(self):
        """Appen faller tillbaka på den bundlade banken när backenden inte
        svarar. Säger de två olika saker beror middagsveckan på om nätet
        fungerade."""
        fran_kallan = {r["id"]: r["mealType"] for r in self.recipes}
        legacy = json.loads(FALLBACK_JSON.read_text(encoding="utf-8"))
        fel = [(r.get("id"), r.get("mealType"), fran_kallan.get(r.get("id")))
               for r in legacy
               if r.get("mealType") is None
               or (r.get("id") in fran_kallan and r["mealType"] != fran_kallan[r["id"]])]
        self.assertEqual(fel, [], "Reservbanken och källorna är oense")

    def test_grotten_ar_inte_en_middag(self):
        grot = next(r for r in self.recipes if r["id"] == GROT_ID)
        self.assertNotEqual(grot["mealType"], DINNER)
        self.assertEqual(grot["mealType"], "frukost")

    def test_klassificeringen_gar_att_upprepa(self):
        """Reglerna, inte en engångskörning. Kan skriptet inte räkna fram
        exakt det som står i källorna är fältet inte granskningsbart."""
        sys.path.insert(0, str(ROOT / "backend" / "scripts"))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "klassificering", ROOT / "backend" / "scripts" / "classify_recipe_meal_type.py")
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        self.assertEqual(modul.check_sources(), [])

    def test_middagarna_racker_till_en_hel_vecka(self):
        """Ett filter som tömmer poolen löser inget problem - det byter ett
        fel mot ett värre. Sju middagar med variation kräver marginal."""
        middagar = [r for r in self.recipes if r["mealType"] == DINNER]
        self.assertGreater(len(middagar), 100)


class VardeforradetArStangt(unittest.TestCase):
    """Ett öppet fält blir en synonymsoppa inom en månad."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.store.close)

    def _recipe(self, **extra):
        return {"id": "prov", "slug": "prov", "name": "Provrätt", "servings": 4,
                "ingredients": [{"name": "Pasta", "amount": 400, "unit": "g"}],
                "instructions": ["Koka."], **extra}

    def test_ett_giltigt_varde_gar_runt(self):
        self.store.upsert_recipe(self._recipe(mealType="frukost"))
        self.assertEqual(self.store.get("prov")["mealType"], "frukost")

    def test_ett_okant_varde_avvisas_vid_skrivning(self):
        for trasigt in ("dinner", "Middag", "huvudrätt", "", "middagar"):
            with self.subTest(trasigt), self.assertRaises(UnknownMealType):
                self.store.upsert_recipe(self._recipe(mealType=trasigt))

    def test_en_delmangdsuppdatering_nollar_inte_klassificeringen(self):
        """Bildbakfyllningen skriver tillbaka recept den läst. Utelämnas
        fältet ska raden behålla sitt värde - annars tappar banken sin
        klassificering av en körning som bara skulle byta en bild."""
        self.store.upsert_recipe(self._recipe(mealType="lunch"))
        self.store.upsert_recipe(self._recipe(image="ny.jpg"))
        self.assertEqual(self.store.get("prov")["mealType"], "lunch")

    def test_ett_oklassat_recept_ar_inte_en_middag(self):
        self.store.upsert_recipe(self._recipe())
        self.assertIsNone(self.store.get("prov")["mealType"])
        self.assertEqual(self.store.search(meal_type=DINNER), [])

    def test_statistiken_visar_luckan(self):
        self.store.upsert_recipe(self._recipe())
        self.store.upsert_recipe(self._recipe(id="prov2", slug="prov2", mealType=DINNER))
        stats = self.store.stats()
        self.assertEqual(stats["withoutMealType"], 1)
        self.assertEqual(stats["byMealType"], {DINNER: 1})


class MigreringenTalEnBefintligDatabas(unittest.TestCase):
    """Produktionens recipes.db är äldre än kolumnen och får inte byggas om
    (en ombyggnad tappar de bakfyllda bilderna)."""

    def _gammal_databas(self, workdir: Path) -> Path:
        import sqlite3
        path = workdir / "gammal.db"
        connection = sqlite3.connect(path)
        connection.executescript(
            "CREATE TABLE recipes (id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, "
            "name TEXT NOT NULL, description TEXT, servings INTEGER NOT NULL DEFAULT 4, "
            "prep_time INTEGER, cook_time INTEGER, total_time INTEGER, difficulty TEXT, "
            "kcal REAL, protein REAL, carbs REAL, fat REAL, fiber REAL, image TEXT, "
            "image_source TEXT, image_source_url TEXT, image_credit TEXT, "
            "image_license TEXT, image_alt TEXT, image_status TEXT, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL);")
        connection.execute(
            "INSERT INTO recipes (id, slug, name, image, created_at, updated_at) "
            "VALUES ('gammal', 'gammal', 'Gammal', 'bakfylld.jpg', 1, 1)")
        connection.commit()
        connection.close()
        return path

    def test_kolumnen_laggs_till_och_raden_overlever(self):
        with tempfile.TemporaryDirectory() as workdir:
            path = self._gammal_databas(Path(workdir))
            store = RecipeStore(path)
            try:
                recipe = store.get("gammal")
                self.assertIsNone(recipe["mealType"])
                self.assertEqual(recipe["image"], "bakfylld.jpg")
            finally:
                store.close()

    def test_migreringen_tal_att_koras_om(self):
        """Samma databas öppnas två gånger i rad - en omstart, en rollback,
        en till deploy. Andra varvet får inte kasta och inte röra datan."""
        with tempfile.TemporaryDirectory() as workdir:
            path = self._gammal_databas(Path(workdir))
            forsta = RecipeStore(path)
            try:
                forsta.upsert_recipe({"id": "gammal", "slug": "gammal",
                                      "name": "Gammal", "mealType": DINNER,
                                      "servings": 4, "instructions": []})
            finally:
                forsta.close()
            andra = RecipeStore(path)
            try:
                self.assertEqual(andra.get("gammal")["mealType"], DINNER)
            finally:
                andra.close()

    def test_en_insert_med_bara_de_gamla_kolumnerna_gar_fortfarande_igenom(self):
        """K6: efter en rollback kör GAMMAL kod mot en migrerad databas.
        Kolumnen måste därför vara nullbar och utan NOT NULL."""
        with tempfile.TemporaryDirectory() as workdir:
            path = self._gammal_databas(Path(workdir))
            store = RecipeStore(path)
            try:
                store.connection.execute(
                    "INSERT INTO recipes (id, slug, name, created_at, updated_at) "
                    "VALUES ('efter-rollback', 'efter-rollback', 'Efter', 2, 2)")
                store.connection.commit()
            finally:
                store.close()


class VeckoplaneringenTarBaraMiddagar(unittest.TestCase):
    """Acceptanskriteriet, mot den RIKTIGA banken i en fixturkopia."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._db = Path(cls._tmp.name) / "recipes.db"
        store = RecipeStore(cls._db)
        try:
            for recipe in source_recipes():
                kopia = dict(recipe)
                nutrition = kopia.pop("nutrition", {}) or {}
                kopia.update({k: nutrition.get(k)
                              for k in ("kcal", "protein", "carbs", "fat", "fiber")})
                kopia["totalTime"] = (kopia.get("prepTime") or 0) + (kopia.get("cookTime") or 0)
                store.upsert_recipe(kopia)
        finally:
            store.close()
        cls._riktig_db = recipes_api.DB_PATH
        recipes_api.DB_PATH = cls._db
        recipes_api.clear_cache()

    @classmethod
    def tearDownClass(cls):
        recipes_api.DB_PATH = cls._riktig_db
        recipes_api.clear_cache()
        cls._tmp.cleanup()

    def test_hela_banken_kom_med_i_fixturen(self):
        self.assertEqual(recipes_api.stats()["total"], len(source_recipes()))

    def test_veckans_kandidater_ar_bara_middagar(self):
        kandidater = recipes_api.week_candidates()
        self.assertTrue(kandidater)
        fel = [(r["id"], r["mealType"]) for r in kandidater if r["mealType"] != DINNER]
        self.assertEqual(fel, [], "Veckoplaneringen fick något som inte är middag")

    def test_risgrynsgroten_finns_i_banken_men_aldrig_i_en_vecka(self):
        """Halva testet är att receptet FINNS: ett filter som råkar tömma
        banken hade annars sett ut som en lyckad grind."""
        self.assertIsNotNone(recipes_api.get(GROT_ID))
        self.assertIsNotNone(recipes_api.get(GROT_SLUG))
        ids = {r["id"] for r in recipes_api.week_candidates()}
        slugs = {r["slug"] for r in recipes_api.week_candidates()}
        self.assertNotIn(GROT_ID, ids)
        self.assertNotIn(GROT_SLUG, slugs)

    def test_receptfliken_visar_fortfarande_hela_banken(self):
        """Filtret hör hemma i veckoplaneringen, inte i katalogen. Gröten ska
        gå att hitta, laga och läsa - bara inte föreslås som middag."""
        alla = recipes_api.search(limit=500)["recipes"]
        self.assertIn(GROT_ID, {r["id"] for r in alla})

    def test_kortet_bar_faltet_hela_vagen_ut(self):
        """Appens veckoplanerare filtrerar på listprojektionen. Saknas
        mealType där kan den inte säga nej till någonting."""
        for recipe in recipes_api.search(limit=500)["recipes"]:
            self.assertIn(recipe["mealType"], MEAL_TYPES, recipe["id"])


if __name__ == "__main__":
    unittest.main()
