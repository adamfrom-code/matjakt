# -*- coding: utf-8 -*-
"""EN canonical receptidentitet.

Appen får aldrig kunna planera in ett recept som backend inte kan öppna.

Bakgrund 2026-09-06: klientens medföljande receptbank
(`frontend/app/data/recipes.json`, fallbacken när backend inte går att nå)
bar fem id som de 241 recepten i `backend/recipe_sources/` aldrig känt till -
`chili`, `fiskgratang`, `kottbullar`, `kycklingwok` och `lax`. Veckogeneratorn
kunde planera in dem, receptsidan svarade 404, och `ensureWeekRecipeDetails`
försökte om på varje omritning eftersom `loadRecipe` inte kan skilja en 404
från ett nätfel. Resultatet var en oändlig 404-loop mot en rätt användaren
aldrig kunde öppna.

Testerna nedan är grinden som håller de två bankerna ihop. De läser filerna
direkt i stället för via HTTP, så de säger samma sak oavsett vad som råkar
ligga i en lokal recipes.db.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.recipes import api as recipes_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLIENT_BANK = ROOT / "frontend" / "app" / "data" / "recipes.json"
# De gamla mängd- och texttabellerna låg i app.js fram till F6; sedan dess i
# sin egen modul. Samma rader, samma nycklar - bara en annan fil att läsa
# dem ur.
LEGACY_CATALOG = ROOT / "frontend" / "app" / "src" / "data" / "legacy-catalog.js"


def _canonical_ids() -> set:
    """Varje id backend kan svara på, läst ur samma källor servern bygger
    receptbanken av (services/recipes/api.RECIPE_SOURCE_DIR)."""
    ids = set()
    for path in sorted(recipes_api.RECIPE_SOURCE_DIR.glob("*.json")):
        for recipe in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(recipe, dict) and recipe.get("id"):
                ids.add(recipe["id"])
    return ids


def _client_bank() -> list:
    return json.loads(CLIENT_BANK.read_text(encoding="utf-8"))


class RecipeIdentityTest(unittest.TestCase):
    def setUp(self):
        self.canonical = _canonical_ids()
        self.bank = _client_bank()

    def test_the_canonical_bank_is_actually_there(self):
        """Skyddar testerna nedan från att bli tomma och därmed meningslösa:
        en tom canonical bank hade fått allt att se grönt ut."""
        self.assertGreater(len(self.canonical), 200)
        self.assertGreater(len(self.bank), 40)

    def test_every_bundled_recipe_can_be_opened_by_the_backend(self):
        """Kärnregeln. Den medföljande banken är det veckogeneratorn planerar
        ur när backend inte svarar, och varje id där måste finnas i den
        canonical banken - annars 404:ar receptsidan för en rätt som redan
        ligger i användarens vecka."""
        orphans = sorted({r["id"] for r in self.bank if r.get("id")} - self.canonical)
        self.assertEqual(orphans, [], f"id som backend inte kan öppna: {orphans}")

    def test_bundled_ids_are_unique(self):
        ids = [r.get("id") for r in self.bank]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(ids), "ett recept utan id kan aldrig hämtas")

    def test_canonical_ids_are_unique(self):
        """Två recept med samma id gör vilket som helst av dem oåtkomligt."""
        seen, duplicates = set(), []
        for path in sorted(recipes_api.RECIPE_SOURCE_DIR.glob("*.json")):
            for recipe in json.loads(path.read_text(encoding="utf-8")):
                if not isinstance(recipe, dict) or not recipe.get("id"):
                    continue
                if recipe["id"] in seen:
                    duplicates.append(recipe["id"])
                seen.add(recipe["id"])
        self.assertEqual(duplicates, [])

    def test_the_legacy_quantity_tables_key_on_real_recipes(self):
        """RECIPE_QUANTITIES och RECIPE_DETAILS i src/data/legacy-catalog.js
        är nycklade på recept-id och används för recept UTAN strukturerade
        ingredienser.
        En nyckel som inte motsvarar något recept är död vikt, och - värre -
        ett tecken på att ett id bytts på ett ställe men inte på det andra,
        vilket är precis hur den femdelade glidningen uppstod.

        Bara nycklar som SER UT som recept-id kontrolleras: tabellerna
        innehåller även ingrediensnamn."""
        source = LEGACY_CATALOG.read_text(encoding="utf-8")
        known = self.canonical | {r["id"] for r in self.bank if r.get("id")}
        unknown = []
        for table in ("RECIPE_QUANTITIES", "RECIPE_DETAILS"):
            start = source.index(f"const {table} = {{")
            end = source.index("\n};", start)
            for line in source[start:end].split("\n"):
                stripped = line.strip()
                if not stripped.endswith("{") and ": {" not in stripped:
                    continue
                key = stripped.split(":")[0].strip().strip('"')
                # Ingrediensnamn har versal eller mellanslag; recept-id är
                # gemener, siffror och bindestreck.
                if key and key == key.lower() and " " not in key and key.replace("-", "").isalnum():
                    if key not in known:
                        unknown.append(f"{table}.{key}")
        self.assertEqual(unknown, [], f"tabellnycklar utan recept: {unknown}")

    def test_the_five_repaired_ids_point_at_the_same_dish(self):
        """Lås fast bytet: en framtida omdöpning ska inte tyst kunna peka om
        ett id till en annan rätt. Namnen jämförs, inte bara att id:t finns."""
        expected = {
            "chili-sin-carne-budget": "Chili sin carne",
            "fiskgratang-dill": "Fiskgratäng med räkor och dill",
            "kottbullar-potatismos": "Köttbullar med potatismos och lingon",
            "kycklingwok-nudlar-protein": "Kycklingwok med nudlar",
            "ugnslax-citron": "Ugnsbakad lax med potatis",
        }
        by_id = {r["id"]: r for r in self.bank}
        for recipe_id, name in expected.items():
            self.assertIn(recipe_id, by_id, f"{recipe_id} försvann ur den medföljande banken")
            self.assertEqual(by_id[recipe_id].get("namn"), name)
            self.assertIn(recipe_id, self.canonical)

    def test_no_bundled_recipe_keeps_one_of_the_old_broken_ids(self):
        broken = {"chili", "fiskgratang", "kottbullar", "kycklingwok", "lax"}
        still_there = broken & {r.get("id") for r in self.bank}
        self.assertEqual(still_there, set())


if __name__ == "__main__":
    unittest.main()
