# -*- coding: utf-8 -*-
"""M5:s acceptanskriterium: ingen middag under proteingolvet.

FYNDET M5 BYGGER PÅ

Två soppor stod som `middag` med sex respektive sju gram protein per portion:
`Morotssoppa med ingefära` (6 g, 290 kcal) och `Sötpotatissoppa med kokos och
lime` (7 g, 380 kcal). Verifierat mot `backend/recipe_sources/*.json`, som är
sanningen - `backend/data/recipes.db` byggs om ur dem.

Appen säljer inte näringsrådgivning, men den föreslår vad man ska äta, och en
huvudrätt på sex gram protein är inte en middag oavsett hur god den är.

GRÄNSEN ÄR EN KONSTANT, INTE EN ÅSIKT

`MIN_DINNER_PROTEIN_G` i `services/recipes/meal_types.py`. Den står på ETT
ställe och `test_golvet_star_pa_ett_enda_stalle` läser källkoden och kräver
att den gör det - ett tal som är utskrivet i klassificeringen, i butiken och i
importen igen är fyra tal som alla heter samma sak, och nästa gång det ska
ändras ändras tre av dem.

GOLVET FÅNGADE EN TREDJE

`Krämig tomatsoppa` ligger på 8 g. Uppdraget nämner den som "nästa i listan",
och det hade varit möjligt att lägga golvet på 8 så att den precis slapp
under. Då hade gränsen dragits runt datan i stället för runt frågan, och en
gräns man gör undantag från är ingen gräns. Den är därför med här.
"""

import json
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.recipes import DinnerTooLeanError, RecipeStore  # noqa: E402
from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.meal_types import (  # noqa: E402
    DINNER, LUNCH, MEAL_TYPES, MIN_DINNER_PROTEIN_G, protein_of)

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
FALLBACK_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"

# De två soppor uppdraget pekar ut vid namn, och den tredje golvet fångade.
MAGRA_SOPPOR = {
    "morotssoppa-ingefara": ("Morotssoppa med ingefära", 6),
    "sotpotatissoppa": ("Sötpotatissoppa med kokos och lime", 7),
    "tomatsoppa": ("Krämig tomatsoppa", 8),
}


def source_recipes() -> list[dict]:
    recipes = []
    for path in sorted(SOURCE_DIR.glob("*.json")):
        recipes.extend(json.loads(path.read_text(encoding="utf-8")))
    return recipes


def flat(recipe: dict) -> dict:
    """Källans form (nästlad `nutrition`) till butikens form (platta fält)."""
    kopia = dict(recipe)
    nutrition = kopia.pop("nutrition", {}) or {}
    kopia.update({key: nutrition.get(key)
                  for key in ("kcal", "protein", "carbs", "fat", "fiber")})
    kopia["totalTime"] = (kopia.get("prepTime") or 0) + (kopia.get("cookTime") or 0)
    return kopia


class GolvetAterFinnsSomEttTal(unittest.TestCase):
    """"Gränsen står som en namngiven konstant med en mening om varför just
    den" - acceptanskriteriets andra hälft."""

    def test_golvet_ar_ett_tal_med_ett_namn(self):
        self.assertIsInstance(MIN_DINNER_PROTEIN_G, int)
        self.assertGreater(MIN_DINNER_PROTEIN_G, 0)

    def test_golvet_har_ett_skal_skrivet_bredvid_sig(self):
        """Ett tal utan skäl är en åsikt som råkat bli kod. Kommentaren över
        konstanten ska namnge det den vilar på."""
        källa = (ROOT / "backend" / "services" / "recipes"
                 / "meal_types.py").read_text(encoding="utf-8")
        före = källa.split("MIN_DINNER_PROTEIN_G =")[0]
        motivering = före.rsplit("\n\n", 1)[-1]
        self.assertIn("Livsmedelsverket", motivering)
        self.assertIn("energiprocent", motivering)

    def test_golvet_star_pa_ett_enda_stalle(self):
        """Talet får inte skrivas ut i en proteinjämförelse någon annanstans.

        Sökningen är smal med flit: en rad som nämner protein OCH innehåller
        golvets tal utan att läsa konstanten är ett andra facit, och nästa
        gång talet ändras ändras det ena men inte det andra. En tia som
        handlar om något helt annat är inte det testet finns för."""
        hem = ROOT / "backend" / "services" / "recipes" / "meal_types.py"
        andra = [p for p in (ROOT / "backend" / "services" / "recipes").glob("*.py")
                 if p != hem]
        andra += [ROOT / "backend" / "scripts" / "classify_recipe_meal_type.py",
                  ROOT / "backend" / "scripts" / "import_recipes.py"]
        mönster = re.compile(rf"(?<![\w.]){MIN_DINNER_PROTEIN_G}(?![\w.])")
        for path in andra:
            for nummer, rad in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if "MIN_DINNER_PROTEIN_G" in rad or "protein" not in rad.lower():
                    continue
                self.assertIsNone(mönster.search(rad),
                                  f"{path.name}:{nummer} skriver ut golvet i stället "
                                  f"för att läsa MIN_DINNER_PROTEIN_G")

    def test_varje_konsument_foljer_konstanten(self):
        """Det lexikala testet ovan fångar en kopia av talet. Det här fångar
        en andra BEDÖMNING: ändras konstanten ska klassificeringen, butiken
        och importvalideringen alla ändra svar - utan att något av dem
        behöver röras."""
        import importlib.util

        from services.recipes import meal_types as modul
        spec = importlib.util.spec_from_file_location(
            "klassificering_konstant",
            ROOT / "backend" / "scripts" / "classify_recipe_meal_type.py")
        klassificering = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(klassificering)
        spec = importlib.util.spec_from_file_location(
            "import_konstant", ROOT / "backend" / "scripts" / "import_recipes.py")
        import_recipes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(import_recipes)

        gryta = {"id": "gryta", "name": "Gryta", "description": "Vardagsmiddag.",
                 "servings": 4, "tags": ["vardagsmat"],
                 "instructions": ["Fräs.", "Koka.", "Servera."],
                 "ingredients": [{"name": "Pasta", "amount": 400, "unit": "g"},
                                 {"name": "Krossade tomater", "amount": 400, "unit": "g"},
                                 {"name": "Vegofärs", "amount": 400, "unit": "g"}],
                 "nutrition": {"kcal": 500, "protein": 20, "carbs": 60, "fat": 18}}
        gryta["mealType"] = klassificering.classify(gryta).meal_type
        self.assertEqual(gryta["mealType"], DINNER)
        self.assertEqual(import_recipes.validate(gryta, set(), set()), [])

        with unittest.mock.patch.object(modul, "MIN_DINNER_PROTEIN_G", 25):
            self.assertEqual(klassificering.classify(gryta).meal_type, LUNCH)
            problem = import_recipes.validate(gryta, set(), set())
            self.assertTrue(any("proteingolvet" in p for p in problem), problem)
            with tempfile.TemporaryDirectory() as tmp:
                store = RecipeStore(Path(tmp) / "recipes.db")
                try:
                    with self.assertRaises(DinnerTooLeanError):
                        store.upsert_recipe(flat(gryta))
                finally:
                    store.close()


class IngenMiddagUnderGolvet(unittest.TestCase):
    """Acceptanskriteriet, mot den committade banken."""

    def setUp(self):
        self.recipes = source_recipes()

    def test_banken_ar_inte_tom(self):
        # Ett test som läser noll recept passerar allt nedanför utan att pröva
        # någonting alls.
        self.assertGreaterEqual(len(self.recipes), 200)

    def test_ingen_middag_i_kallorna_ar_under_golvet(self):
        magra = [(r["id"], protein_of(r)) for r in self.recipes
                 if r.get("mealType") == DINNER
                 and protein_of(r) is not None
                 and protein_of(r) < MIN_DINNER_PROTEIN_G]
        self.assertEqual(magra, [], (
            f"middagar under {MIN_DINNER_PROTEIN_G} g protein per portion"))

    def test_varje_middag_har_ett_proteinvarde_alls(self):
        """Golvet är värdelöst om "vet inte" räknas som godkänt. Okänt
        protein får inte bli en väg runt gränsen."""
        utan = [r["id"] for r in self.recipes
                if r.get("mealType") == DINNER and protein_of(r) is None]
        self.assertEqual(utan, [])

    def test_reservbanken_haller_samma_golv(self):
        """Appen faller tillbaka på den bundlade banken när backenden inte
        svarar. Håller den inte golvet beror middagsveckan på om nätet
        fungerade."""
        magra = [(r.get("id"), protein_of(r))
                 for r in json.loads(FALLBACK_JSON.read_text(encoding="utf-8"))
                 if r.get("mealType") == DINNER
                 and protein_of(r) is not None
                 and protein_of(r) < MIN_DINNER_PROTEIN_G]
        self.assertEqual(magra, [])

    def test_de_utpekade_sopporna_finns_kvar_men_ar_inte_middag(self):
        """Halva testet är att recepten FINNS. Ett filter som råkar radera
        dem hade annars sett ut som en lyckad grind."""
        by_id = {r["id"]: r for r in self.recipes}
        for recipe_id, (namn, protein) in MAGRA_SOPPOR.items():
            with self.subTest(recipe_id):
                recipe = by_id.get(recipe_id)
                self.assertIsNotNone(recipe, f"{recipe_id} försvann ur banken")
                self.assertEqual(recipe["name"], namn)
                # Näringen är ORÖRD: M5 hittade inte på några värden.
                self.assertEqual(protein_of(recipe), float(protein))
                self.assertNotEqual(recipe["mealType"], DINNER)
                self.assertEqual(recipe["mealType"], LUNCH)
                self.assertIn(recipe["mealType"], MEAL_TYPES)

    def test_middagarna_racker_fortfarande_till_en_hel_vecka(self):
        """En gräns som tömmer poolen byter ett fel mot ett värre."""
        middagar = [r for r in self.recipes if r.get("mealType") == DINNER]
        self.assertGreater(len(middagar), 100)


class ReglernaGerSammaSvarIgen(unittest.TestCase):
    """Klassificeringen är regler, inte en körning - även efter M5."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "klassificering_m5",
            ROOT / "backend" / "scripts" / "classify_recipe_meal_type.py")
        cls.modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.modul)

    def test_kallorna_stammer_med_reglerna(self):
        self.assertEqual(self.modul.check_sources(), [])

    def test_golvet_gar_fore_receptets_egen_uppfattning(self):
        """Morotssoppan bär taggen `vardagsmat`, som annars ensam gör ett
        recept till middag. En tagg är en åsikt; portionens innehåll är ett
        faktum, och regeln ligger därför före middagsbeviset."""
        soppa = next(r for r in source_recipes() if r["id"] == "morotssoppa-ingefara")
        self.assertIn("vardagsmat", soppa["tags"])
        fynd = self.modul.classify(soppa)
        self.assertEqual(fynd.rule, "under-proteingolvet")
        self.assertEqual(fynd.meal_type, LUNCH)

    def test_utan_kant_protein_gissar_regeln_inte(self):
        """Saknas näringen vet vi ingenting. Då ska receptet falla vidare
        till de gamla reglerna, inte klassas som lunch på en tomhet."""
        fynd = self.modul.classify(
            {"id": "okant", "name": "Gryta", "tags": ["vardagsmat"]})
        self.assertEqual(fynd.meal_type, DINNER)

    def test_en_mager_efterratt_ar_fortfarande_en_efterratt(self):
        """Regeln rör bara det som annars blivit middag. En efterrätt på tre
        gram protein är inte ett fel - det är vad en efterrätt är."""
        fynd = self.modul.classify({
            "id": "glass", "name": "Vaniljglass",
            "description": "En efterrätt till helgen.",
            "nutrition": {"protein": 3}})
        self.assertEqual(fynd.meal_type, "efterratt")


class ButikenVagrarSkrivaNerDet(unittest.TestCase):
    """Fail closed vid SKRIVNING, precis som det stängda värdeförrådet. En
    mager middag som hinner ner i databasen upptäcks annars först som en
    soppa på sex gram i någons middagsvecka."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.store.close)

    def _recipe(self, **extra):
        return {"id": "prov", "slug": "prov", "name": "Provrätt", "servings": 4,
                "ingredients": [{"name": "Pasta", "amount": 400, "unit": "g"}],
                "instructions": ["Koka."], **extra}

    def test_en_mager_middag_avvisas(self):
        with self.assertRaises(DinnerTooLeanError):
            self.store.upsert_recipe(
                self._recipe(mealType=DINNER, protein=MIN_DINNER_PROTEIN_G - 1))
        self.assertIsNone(self.store.get("prov"))

    def test_exakt_pa_golvet_gar_igenom(self):
        self.store.upsert_recipe(
            self._recipe(mealType=DINNER, protein=MIN_DINNER_PROTEIN_G))
        self.assertEqual(self.store.get("prov")["mealType"], DINNER)

    def test_samma_ratt_som_lunch_gar_igenom(self):
        self.store.upsert_recipe(self._recipe(mealType=LUNCH, protein=6))
        self.assertEqual(self.store.get("prov")["mealType"], LUNCH)

    def test_okant_protein_avvisas_inte(self):
        """Vet vi inte får vi inte låtsas. Bildbakfyllningen och de äldre
        migreringarna skriver rader utan näring, och en butik som vägrade
        dem hade stoppat drift för en regel den inte kan pröva."""
        self.store.upsert_recipe(self._recipe(mealType=DINNER))
        self.assertEqual(self.store.get("prov")["mealType"], DINNER)

    def test_en_delmangdsuppdatering_kan_inte_smyga_ner_proteinet(self):
        """Hålet som annars bara flyttat sig ett steg: raden står redan som
        middag, och skrivningen bär inget `mealType` - men väl ett nytt,
        lägre protein."""
        self.store.upsert_recipe(self._recipe(mealType=DINNER, protein=30))
        with self.assertRaises(DinnerTooLeanError):
            self.store.upsert_recipe(self._recipe(protein=4))
        self.assertEqual(self.store.get("prov")["nutrition"]["protein"], 30)


class VeckanFarAldrigNagonAvDem(unittest.TestCase):
    """Hela vägen ut: den riktiga banken, i en fixturkopia, genom samma
    väg som appen använder."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        db = Path(cls._tmp.name) / "recipes.db"
        store = RecipeStore(db)
        try:
            for recipe in source_recipes():
                store.upsert_recipe(flat(recipe))
        finally:
            store.close()
        cls._riktig_db = recipes_api.DB_PATH
        recipes_api.DB_PATH = db
        recipes_api.clear_cache()

    @classmethod
    def tearDownClass(cls):
        recipes_api.DB_PATH = cls._riktig_db
        recipes_api.clear_cache()
        cls._tmp.cleanup()

    def test_hela_banken_kom_med(self):
        self.assertEqual(recipes_api.stats()["total"], len(source_recipes()))

    def test_ingen_kandidat_till_veckan_ar_under_golvet(self):
        kandidater = recipes_api.week_candidates()
        self.assertTrue(kandidater)
        magra = [(r["id"], r.get("protein")) for r in kandidater
                 if r.get("protein") is not None
                 and r["protein"] < MIN_DINNER_PROTEIN_G]
        self.assertEqual(magra, [])

    def test_sopporna_gar_att_laga_men_aldrig_att_fa_foreslagen(self):
        ids = {r["id"] for r in recipes_api.week_candidates()}
        for recipe_id in MAGRA_SOPPOR:
            with self.subTest(recipe_id):
                self.assertIsNotNone(recipes_api.get(recipe_id),
                                     "receptet ska finnas kvar i katalogen")
                self.assertNotIn(recipe_id, ids)

    def test_receptfliken_visar_dem_fortfarande(self):
        alla = {r["id"] for r in recipes_api.search(limit=500)["recipes"]}
        for recipe_id in MAGRA_SOPPOR:
            self.assertIn(recipe_id, alla)


if __name__ == "__main__":
    unittest.main()
