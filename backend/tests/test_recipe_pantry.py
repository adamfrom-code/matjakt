# -*- coding: utf-8 -*-
"""M3: samma ingrediens, samma skafferiklassning - i varje recept.

`pantry_staple = 1` betyder "antas finnas hemma": raden prissätts aldrig och
hamnar i `rows.home` i stället för `rows.buy`. Före M3 avgjordes det per rad,
och då blev samma ingrediens klassad åt två håll: ägg prissattes i 34 recept
och antogs finnas hemma i 2, vitlök i 70 mot 9, ris i 50 mot 1. Tjugoen
ingredienser var klassade åt båda hållen, över 489 rader.

Det är ingen smaksak. I de recept där ingrediensen låg på skafferisidan blev
portionspriset för lågt OCH inköpslistan för kort - en rätt som behöver ägg
gav inga ägg.

Grinden prövas mot en fixturkopia av de riktiga 240 recepten, byggd ur de
spårade källorna under tempkatalogen. `data_guard.py` stoppar med rätta ett
test som försöker öppna backend/data/recipes.db, och den filen finns inte i
CI.
"""

import collections
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.recipes import RecipeStore, normalize_ingredient_id  # noqa: E402
from services.recipes.pantry import (  # noqa: E402
    ALDRIG_SKAFFERI, PANTRY_STAPLES, PantryStapleConflict, is_pantry_staple,
    require,
)

SOURCE_DIR = ROOT / "backend" / "recipe_sources"
FALLBACK_JSON = ROOT / "frontend" / "app" / "data" / "recipes.json"


def las_kallor():
    """De spårade receptkällorna - bankens sanning, inte en byggd databas."""
    for path in sorted(SOURCE_DIR.glob("*.json")):
        for recipe in json.loads(path.read_text(encoding="utf-8")):
            yield path, recipe


def klassificeringsskriptet():
    spec = importlib.util.spec_from_file_location(
        "klassificera_skafferi",
        ROOT / "backend" / "scripts" / "classify_recipe_pantry.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


class KallornaTest(unittest.TestCase):
    """Källorna är sanningen: `bootstrap_if_empty` bygger om banken ur dem så
    snart deras fingeravtryck ändras. En rättning som bara fanns i databasen
    hade inte överlevt nästa receptändring."""

    @classmethod
    def setUpClass(cls):
        cls.rader = [(path.name, recipe, ingredient)
                     for path, recipe in las_kallor()
                     for ingredient in recipe.get("ingredients") or []]

    def test_kallorna_ar_faktiskt_lasta(self):
        """Skyddar kraven nedan från att bli tomma och därmed meningslösa."""
        self.assertGreater(len({r["id"] for _, r, _ in self.rader}), 200)
        self.assertGreater(len(self.rader), 2000)

    def test_varje_ingrediens_har_samma_skafferiklassning_overallt(self):
        """ACCEPTANSEN. Ägg var skafferivara i 2 recept och köpvara i 34."""
        per_ingrediens = collections.defaultdict(collections.Counter)
        exempel = collections.defaultdict(lambda: {0: [], 1: []})
        for _, recipe, ingredient in self.rader:
            nyckel = normalize_ingredient_id(ingredient["name"])
            flagga = 1 if ingredient.get("pantryStaple") else 0
            per_ingrediens[nyckel][flagga] += 1
            exempel[nyckel][flagga].append(recipe["id"])

        blandade = {k: v for k, v in per_ingrediens.items() if len(v) > 1}
        if blandade:
            rader = [f"{k}: skafferi i {v[1]} recept ({exempel[k][1][0]} …), "
                     f"köpvara i {v[0]} ({exempel[k][0][0]} …)"
                     for k, v in sorted(blandade.items())]
            self.fail(f"{len(blandade)} ingredienser är klassade åt två håll:\n  "
                      + "\n  ".join(rader))

    def test_agg_lok_och_vitlok_har_mangd_i_varje_rad(self):
        """ACCEPTANSEN, andra halvan. Uppdraget pekar ut de tre vid namn: de
        är varor man köper, och en vara man köper har en mängd."""
        utan = [(r["id"], i["name"]) for _, r, i in self.rader
                if normalize_ingredient_id(i["name"]) in ALDRIG_SKAFFERI
                and i.get("amount") is None]
        self.assertEqual(utan, [], f"rader utan mängd: {utan}")

    def test_ingen_av_de_tre_ar_markt_som_skafferivara(self):
        markta = [(r["id"], i["name"]) for _, r, i in self.rader
                  if normalize_ingredient_id(i["name"]) in ALDRIG_SKAFFERI
                  and i.get("pantryStaple")]
        self.assertEqual(markta, [], f"märkta som skafferi: {markta}")

    def test_skafferiraderna_bar_ingen_mangd(self):
        """De två uppgifterna säger samma sak, och två uppgifter som säger
        samma sak kan säga emot varandra. Frontend läser `rows.home` som en
        ren namnlista - en mängd där visas för ingen och räknas av ingen."""
        med_mangd = [(r["id"], i["name"], i.get("amount")) for _, r, i in self.rader
                     if i.get("pantryStaple") and i.get("amount") is not None]
        self.assertEqual(med_mangd, [])

    def test_varje_kopvarurad_har_en_mangd(self):
        """En rad utan mängd går inte att prissätta. Före M3 fanns noll
        sådana rader - just för att allt utan mängd var märkt skafferi."""
        utan = [(r["id"], i["name"]) for _, r, i in self.rader
                if not i.get("pantryStaple") and i.get("amount") is None]
        self.assertEqual(utan, [], f"{len(utan)} köpvarurader utan mängd: {utan[:10]}")

    def test_vitloken_raknas_fortfarande_i_klyftor(self):
        """C3 räknade om banken från knoppar till klyftor. De nio rader M3
        flyttade tillbaka till köpsidan måste bära samma enhet - annars läser
        prismotorn dem som hela knoppar, 70 g styck."""
        enheter = {i.get("unit") for _, _, i in self.rader
                   if normalize_ingredient_id(i["name"]) == "vitlok"
                   and i.get("amount") is not None}
        self.assertEqual(enheter, {"klyfta"})

    def test_klassificeringsskriptet_ar_gront(self):
        """Samma fråga en gång till, genom skriptet som rättar. Ett facit som
        bara stämmer när ett test räknar ut det själv är inget facit."""
        self.assertEqual(klassificeringsskriptet().granska(), [])


class BankenTest(unittest.TestCase):
    """Samma krav på den byggda banken. Källorna kan vara rätt och vägen in i
    databasen ändå tappa bort det."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = RecipeStore(Path(cls._tmp.name) / "recipes.db")
        for _, recipe in las_kallor():
            cls.store.upsert_recipe(recipe)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls._tmp.cleanup()

    def _rader(self):
        return list(self.store.connection.execute(
            "SELECT recipe_id, name, normalized_id, amount, unit, pantry_staple "
            "FROM recipe_ingredients"))

    def test_banken_ar_byggd(self):
        self.assertGreater(len(self._rader()), 2000)

    def test_varje_ingrediens_har_en_enda_klassning_i_databasen(self):
        blandade = list(self.store.connection.execute(
            "SELECT normalized_id, COUNT(DISTINCT pantry_staple) AS varianter "
            "FROM recipe_ingredients GROUP BY normalized_id HAVING varianter > 1"))
        self.assertEqual([rad["normalized_id"] for rad in blandade], [])

    def test_agget_prissatts_i_varje_recept_det_finns_i(self):
        """Det konkreta fallet uppdraget räknar upp: 36 ägg-rader, varav 2
        låg på skafferisidan."""
        rader = [r for r in self._rader() if r["normalized_id"] == "agg"]
        self.assertGreaterEqual(len(rader), 30)
        self.assertEqual([r["recipe_id"] for r in rader if r["pantry_staple"]], [])
        self.assertEqual([r["recipe_id"] for r in rader if r["amount"] is None], [])

    def test_skafferiraderna_i_databasen_bar_ingen_mangd(self):
        med_mangd = [(r["recipe_id"], r["name"]) for r in self._rader()
                     if r["pantry_staple"] and r["amount"] is not None]
        self.assertEqual(med_mangd, [])

    def test_salt_och_peppar_ligger_kvar_pa_skafferisidan(self):
        """Grinden får inte vara grön för att allt blev en köpvara: då står
        salt på inköpslistan varje vecka, vilket är felet fältet finns för."""
        for nyckel in ("salt", "peppar", "olja"):
            rader = [r for r in self._rader() if r["normalized_id"] == nyckel]
            self.assertTrue(rader, nyckel)
            self.assertTrue(all(r["pantry_staple"] for r in rader), nyckel)


class ButikenTest(unittest.TestCase):
    """Butiken HÄRLEDER flaggan ur listan i stället för att kopiera raden."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self.store.close)

    def _spara(self, *ingredients):
        self.store.upsert_recipe({
            "id": "prov", "slug": "prov", "name": "Provrätt", "servings": 4,
            "mealType": "middag", "ingredients": list(ingredients),
            "instructions": ["Koka."]})
        return {i["name"]: i for i in self.store.get("prov")["ingredients"]}

    def test_en_kallfil_som_pastar_att_agg_finns_hemma_far_inte_igenom(self):
        rader = self._spara({"name": "Ägg", "amount": 2, "unit": "st",
                             "pantryStaple": True})
        self.assertFalse(rader["Ägg"]["pantryStaple"])

    def test_salt_blir_skafferivara_aven_utan_flaggan(self):
        rader = self._spara({"name": "Salt"})
        self.assertTrue(rader["Salt"]["pantryStaple"])

    def test_namnet_normaliseras_som_ingrediens_id(self):
        """"SMÖR " och "Smör" är samma vara. Listan slår upp på det
        normaliserade id:t, inte på strängen."""
        rader = self._spara({"name": "SMÖR "})
        self.assertTrue(rader["SMÖR "]["pantryStaple"])


class ListanTest(unittest.TestCase):
    def test_de_tre_uppdraget_pekar_ut_star_aldrig_i_listan(self):
        for nyckel in ALDRIG_SKAFFERI:
            self.assertNotIn(nyckel, PANTRY_STAPLES)
            self.assertFalse(is_pantry_staple(nyckel))

    def test_uppdragets_skafferivaror_star_i_listan(self):
        """Uppdraget räknar upp dem: salt, peppar, olja, smör, socker,
        ättika, vanliga torra kryddor."""
        for namn in ("Salt", "Peppar", "Olja", "Olivolja", "Smör", "Socker",
                     "Ättika", "Chilipulver", "Spiskummin"):
            self.assertTrue(is_pantry_staple(namn), namn)

    def test_en_okand_ingrediens_ar_en_kopvara(self):
        """Listan är stängd, och det obeslutade felar åt rätt håll: en ny
        ingrediens hamnar på inköpslistan i stället för att tyst antas finnas
        hemma och försvinna ur både pris och lista."""
        self.assertFalse(is_pantry_staple("Struntprat"))
        self.assertFalse(is_pantry_staple(""))
        self.assertFalse(is_pantry_staple(None))

    def test_varje_post_i_listan_har_ett_skal(self):
        tomma = [k for k, v in PANTRY_STAPLES.items() if not (v or "").strip()]
        self.assertEqual(tomma, [])

    def test_require_avvisar_en_rad_som_sager_emot_listan(self):
        with self.assertRaises(PantryStapleConflict):
            require("Ägg", True)
        with self.assertRaises(PantryStapleConflict):
            require("Salt", False)
        self.assertTrue(require("Salt", True))
        self.assertFalse(require("Ägg", False))


class ImportgrindenTest(unittest.TestCase):
    """Butiken rättar tyst; importen ska gnälla högt.

    Förut räckte det att en rad kallade sig skafferivara för att slippa
    mängdkravet i `validate()` - och det var precis den luckan som lät ägg
    slinka in utan mängd i två recept."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "importera_recept", ROOT / "backend" / "scripts" / "import_recipes.py")
        cls.importera = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.importera)

    def _problem(self, *ingredients):
        recept = {"id": "prov", "name": "Provrätt", "description": "Prov.",
                  "servings": 4, "tags": ["vardag"],
                  "nutrition": {"kcal": 600, "protein": 30, "carbs": 60, "fat": 25},
                  "instructions": ["Koka.", "Rör.", "Servera."],
                  "ingredients": list(ingredients)}
        return self.importera.validate(recept, set(), set())

    def test_agg_utan_mangd_slipper_inte_undan_genom_att_kalla_sig_skafferi(self):
        problem = self._problem({"name": "Pasta", "amount": 400, "unit": "g"},
                                {"name": "Salt"},
                                {"name": "Ägg", "pantryStaple": True})
        self.assertTrue([p for p in problem if "PANTRY_STAPLES" in p], problem)
        self.assertTrue([p for p in problem if "utan mängd: Ägg" in p], problem)

    def test_en_skafferivara_med_mangd_ar_ocksa_ett_fel(self):
        problem = self._problem({"name": "Pasta", "amount": 400, "unit": "g"},
                                {"name": "Salt", "amount": 5, "unit": "g"},
                                {"name": "Ägg", "amount": 2, "unit": "st"})
        self.assertTrue([p for p in problem if "skafferivara med mängd: Salt" in p],
                        problem)

    def test_ett_riktigt_recept_gar_igenom(self):
        self.assertEqual(
            self._problem({"name": "Pasta", "amount": 400, "unit": "g"},
                          {"name": "Ägg", "amount": 2, "unit": "st"},
                          {"name": "Salt"}), [])


class ReservbankenTest(unittest.TestCase):
    """Reservbanken är samma recept i appens egna fältnamn, med `hemma` i
    stället för `pantryStaple`. Utan den halvan ger ett backendavbrott en
    inköpslista utan ägg för precis de recept M3 rättade."""

    @classmethod
    def setUpClass(cls):
        cls.recept = json.loads(FALLBACK_JSON.read_text(encoding="utf-8"))

    def test_reservbanken_ar_last(self):
        self.assertGreater(len(self.recept), 50)

    def test_hemma_innehaller_bara_skafferivaror(self):
        fel = [(r["id"], namn) for r in self.recept
               for namn in r.get("hemma") or [] if not is_pantry_staple(namn)]
        self.assertEqual(fel, [], f"varor man köper som ligger i hemma: {fel}")

    def test_ingredienserna_innehaller_ingen_skafferivara(self):
        fel = [(r["id"], namn) for r in self.recept
               for namn in r.get("ingredienser") or [] if is_pantry_staple(namn)]
        self.assertEqual(fel, [])

    def test_samma_ingrediens_ligger_pa_samma_sida_i_bada_bankerna(self):
        """Samma rätt ska ge samma inköpslista oavsett om backenden svarade.

        Bara ingredienser som finns i BÅDA bankerna jämförs: de två bankerna
        har på sina håll olika råvaror för samma id (offline har
        `chili-sin-carne-budget` kidneybönor, online svarta bönor), och den
        skillnaden är inte M3:s fråga. Sidan de hamnar på är det."""
        online = {}
        for _, recipe in las_kallor():
            online[recipe["id"]] = {
                normalize_ingredient_id(i["name"]): bool(i.get("pantryStaple"))
                for i in recipe["ingredients"]}
        jamforda = 0
        for recipe in self.recept:
            rader = online.get(recipe["id"])
            if rader is None:
                continue
            for namn, offline_hemma in ([(n, False) for n in recipe.get("ingredienser") or []]
                                        + [(n, True) for n in recipe.get("hemma") or []]):
                nyckel = normalize_ingredient_id(namn)
                if nyckel not in rader:
                    continue
                jamforda += 1
                self.assertEqual(
                    rader[nyckel], offline_hemma,
                    f"{recipe['id']}: {namn} ligger på olika sidor i de två bankerna")
        self.assertGreater(jamforda, 150)


if __name__ == "__main__":
    unittest.main()
