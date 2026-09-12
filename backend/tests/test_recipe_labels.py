# -*- coding: utf-8 -*-
"""M4: ett etikettfält, ett format - och ingen etikett förlorad på vägen.

Receptbanken bar TVÅ fält med överlappande innehåll, `categories` och `tags`.
Nio etiketter fanns i båda i var sin versalisering, och `RecipeStore.search`
jämförde med likhet. Alltså:

    filter "kott"            gav 39 recept     "Kött"           gav 18
    filter "husmanskost"     gav 74            "Husmanskost"    gav 69
    filter "familjefavorit"  gav 0             "Familjefavorit" gav 54

Den sista raden är felets hela form: den normaliserade formen gav NOLL recept,
och en tom lista ser ut som ett ärligt "vi har inga sådana". Hyllan
"Familjemiddag" i `api.SHELVES` var därför tvungen att stavas med versal.

Grinden prövas mot de spårade källorna och mot en bank byggd ur dem under
tempkatalogen. `data_guard.py` stoppar med rätta ett test som försöker öppna
backend/data/recipes.db, och den filen finns inte i CI.
"""

import collections
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from services.recipes import RecipeStore, normalize_ingredient_id  # noqa: E402
from services.recipes.api import SHELVES  # noqa: E402
from services.recipes.labels import (  # noqa: E402
    DISPLAY_NAMES, LABELS, LEGACY_KINDS, display, merge, normalize_label_id)

SOURCE_DIR = ROOT / "backend" / "recipe_sources"

# VOKABULÄRET FÖRE M4, mätt ur källorna: varje SKRIVNING och hur många recept
# den satt på. Trettiotvå skrivningar av tjugofyra etiketter - nio av dem
# stavade åt två håll. Tabellen står här för att uppdragets andra krav ska gå
# att pröva mot något: "varje etikett som fanns före migreringen finns efter".
# Utan den hade testet bara kunnat säga att banken är konsekvent MED SIG SJÄLV,
# vilket en tom bank också är.
FORE_M4 = {
    "billigt": 107, "vardagsmat": 97, "barn": 86, "snabbt": 84,
    "husmanskost": 74, "Husmanskost": 69, "mealprep": 68, "vegetariskt": 66,
    "Vegetariskt": 65, "proteinrikt": 64, "Familjefavorit": 54,
    "helgmiddag": 47, "kott": 39, "Fisk": 38, "Kyckling": 34, "kyckling": 34,
    "fisk": 30, "Pasta": 25, "Kött": 18, "lunch": 17, "Grytor": 16,
    "familj": 16, "veganskt": 16, "Soppor": 15, "bulk": 14, "Familj": 11,
    "Ris": 6, "Snabbt & enkelt": 6, "Helg": 4, "Helgmiddag": 3, "Lunch": 3,
    "Soppa": 3,
}

# BADGEN FÖRE M4: `categories[0]` blir `typ` i frontendens receptmodell och
# ritas ut på kortet i Ikväll, i bytesvyn och på hemskärmen. Fördelningen är
# mätt på de 240 recepten före sammanslagningen och ska vara oförändrad efter
# den. En etikettstädning får inte byta text på ett receptkort.
BADGE_FORE_M4 = {
    "Husmanskost": 49, "Fisk": 37, "Vegetariskt": 36, "Kyckling": 29,
    "Familjefavorit": 16, "Grytor": 16, "Kött": 12, "Familj": 11, "Pasta": 11,
    "Soppor": 7, "Snabbt & enkelt": 6, "Helg": 4, "Ris": 4, "Helgmiddag": 1,
    "Lunch": 1,
}

# Fem recept där källordningen och den alfabetiska ordningen skiljer sig åt -
# alltså precis de fall där en slarvig sammanslagning hade bytt badge.
BADGE_PER_RECEPT = {
    "kottbullar-potatismos": "Familj",
    "spaghetti-kottfarssas": "Familj",
    "biff-sotpotatis": "Helgmiddag",
    "kikartscurry-protein": "Ris",
    "torsk-potatismos": "Familj",
}


def las_kallor():
    for path in sorted(SOURCE_DIR.glob("*.json")):
        for recipe in json.loads(path.read_text(encoding="utf-8")):
            yield path, recipe


def skriptet():
    spec = importlib.util.spec_from_file_location(
        "normalisera_etiketter",
        ROOT / "backend" / "scripts" / "normalize_recipe_labels.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


class KallornaTest(unittest.TestCase):
    """Källorna är sanningen: `bootstrap_if_empty` bygger om banken ur dem så
    snart deras fingeravtryck ändras."""

    @classmethod
    def setUpClass(cls):
        cls.recept = [recipe for _, recipe in las_kallor()]

    def test_kallorna_ar_faktiskt_lasta(self):
        """Skyddar kraven nedan från att bli tomma och därmed meningslösa."""
        self.assertGreater(len(self.recept), 200)
        self.assertTrue(all(r.get(LABELS) for r in self.recept))

    def test_de_gamla_falten_finns_inte_kvar(self):
        """ACCEPTANSEN, första halvan: ETT fält."""
        kvar = [(r["id"], f) for r in self.recept for f in LEGACY_KINDS if r.get(f)]
        self.assertEqual(kvar, [], f"recept med kvarvarande gamla fält: {kvar[:5]}")

    def test_varje_etikett_ar_i_nyckelform(self):
        fel = [(r["id"], v) for r in self.recept for v in r[LABELS]
               if normalize_label_id(v) != v]
        self.assertEqual(fel, [], f"etiketter som inte är nycklar: {fel[:5]}")

    def test_ingen_etikett_forekommer_i_tva_versaliseringar(self):
        """ACCEPTANSEN, andra halvan. `Kött` mot `kott` var felet."""
        per_nyckel = collections.defaultdict(set)
        for r in self.recept:
            for v in r[LABELS]:
                per_nyckel[normalize_label_id(v)].add(v)
        blandade = {k: sorted(v) for k, v in per_nyckel.items() if len(v) > 1}
        self.assertEqual(blandade, {}, f"etiketter med flera skrivningar: {blandade}")

    def test_varje_etikett_som_fanns_fore_finns_efter(self):
        """ACCEPTANSEN, tredje halvan: ingenting kastades bort.

        Prövas per SKRIVNING, inte per nyckel: `Pasta`, `Grytor`, `Soppor`,
        `Ris`, `Helg` och `Snabbt & enkelt` fanns BARA i `categories`, och
        `bulk`, `mealprog` och de andra bara i `tags`. En sammanslagning som
        behållit det ena fältet hade tappat det andra utan att bli rödare."""
        finns = {normalize_label_id(v) for r in self.recept for v in r[LABELS]}
        saknas = sorted({s for s in FORE_M4 if normalize_label_id(s) not in finns})
        self.assertEqual(saknas, [], f"etiketter som försvann i migreringen: {saknas}")

    def test_ingen_etikett_tappade_recept(self):
        """Etiketten kan finnas kvar och ändå ha lossnat från sina recept."""
        per_nyckel = collections.Counter()
        for r in self.recept:
            for v in r[LABELS]:
                per_nyckel[normalize_label_id(v)] += 1
        forlorade = []
        for skrivning, antal in FORE_M4.items():
            nyckel = normalize_label_id(skrivning)
            if per_nyckel[nyckel] < antal:
                forlorade.append((skrivning, antal, per_nyckel[nyckel]))
        self.assertEqual(forlorade, [], f"färre recept än före: {forlorade}")

    def test_sammanslagningen_gav_farre_rader_an_de_tva_falten(self):
        """Dubbletterna SLOGS IHOP - de dubblerades inte. 2 012 etikettrader
        var 2 012 just för att `Husmanskost` och `husmanskost` räknades två
        gånger."""
        rader = sum(len(r[LABELS]) for r in self.recept)
        self.assertLess(rader, sum(FORE_M4.values()))
        self.assertGreater(rader, 1000)

    def test_skriptet_ar_gront(self):
        """Samma fråga en gång till, genom skriptet som rättar."""
        self.assertEqual(skriptet().granska(), [])


class BadgenTest(unittest.TestCase):
    """Den första etiketten är DATA, inte ordning på måfå.

    Före M4 lästes etiketterna med `ORDER BY kind, value`, och eftersom
    'categories' < 'tags' kom kategorierna först. Appen visar den första som
    badge på kortet. Ändras ordningen byter 240 receptkort text - en
    datastädning som syns som en produktförändring."""

    @classmethod
    def setUpClass(cls):
        cls.recept = [recipe for _, recipe in las_kallor()]

    def test_fordelningen_av_badges_ar_oforandrad(self):
        fordelning = collections.Counter(display(r[LABELS][0]) for r in self.recept)
        self.assertEqual(dict(fordelning), BADGE_FORE_M4)

    def test_de_kanliga_recepten_har_kvar_sin_badge(self):
        """Fem recept där källordningen och den alfabetiska skiljer sig åt."""
        for recipe_id, badge in BADGE_PER_RECEPT.items():
            recipe = next((r for r in self.recept if r["id"] == recipe_id), None)
            self.assertIsNotNone(recipe, recipe_id)
            self.assertEqual(display(recipe[LABELS][0]), badge, recipe_id)


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

    def test_banken_ar_byggd(self):
        self.assertGreater(self.store.count(), 200)

    def test_de_gamla_kinderna_finns_inte_i_databasen(self):
        kvar = [rad["kind"] for rad in self.store.connection.execute(
            "SELECT DISTINCT kind FROM recipe_labels")]
        self.assertEqual(sorted(kvar), sorted([LABELS, "allergens", "dietFlags"]))

    def test_varje_lagrad_etikett_ar_en_nyckel(self):
        fel = [rad["value"] for rad in self.store.connection.execute(
            f"SELECT DISTINCT value FROM recipe_labels WHERE kind = '{LABELS}'")
            if normalize_label_id(rad["value"]) != rad["value"]]
        self.assertEqual(fel, [])

    def test_filtret_hittar_samma_recept_oavsett_versalisering(self):
        """FELET, prövat direkt. `kott` gav 39 recept och `Kött` gav 18."""
        for a, b in (("kott", "Kött"), ("husmanskost", "Husmanskost"),
                     ("familjefavorit", "Familjefavorit"), ("fisk", "Fisk"),
                     ("kyckling", "KYCKLING "), ("lunch", "Lunch")):
            forst = [r["id"] for r in self.store.search(tags=[a], limit=500)]
            sedan = [r["id"] for r in self.store.search(tags=[b], limit=500)]
            self.assertEqual(forst, sedan, f"{a!r} och {b!r} ger olika recept")
            self.assertTrue(forst, f"{a!r} gav inga recept alls")

    def test_etiketten_som_bara_fanns_som_kategori_gar_att_filtrera_pa(self):
        """`Pasta`, `Grytor`, `Soppor`, `Ris`, `Helg` och `Snabbt & enkelt`
        fanns bara i `categories`, och `categories` var inte det fält appen
        filtrerade på i praktiken - hyllorna frågar efter taggar."""
        for nyckel, minst in (("pasta", 20), ("grytor", 10), ("soppor", 10),
                              ("ris", 5), ("helg", 3), ("snabbt-enkelt", 5)):
            träffar = self.store.search(tags=[nyckel], limit=500)
            self.assertGreaterEqual(len(träffar), minst, nyckel)

    def test_familjefavorit_hittas_nu_pa_sin_nyckel(self):
        """Den skarpaste av dem: etiketten satt på 54 recept och den
        normaliserade formen gav noll."""
        self.assertEqual(len(self.store.search(tags=["familjefavorit"], limit=500)), 54)

    def test_de_tre_faltnamnen_ar_vyer_av_en_enda_lista(self):
        """`labels` är fältet; `tags` är nycklarna och `categories` namnen ur
        SAMMA lista i samma ordning. Det går inte längre att lägga en etikett
        i det ena utan att den syns i det andra."""
        for recipe_id in ("kottbullar-potatismos", "tomatsoppa", "butterchicken"):
            recipe = self.store.get(recipe_id)
            self.assertTrue(recipe[LABELS], recipe_id)
            self.assertEqual(recipe["tags"], [e["key"] for e in recipe[LABELS]])
            self.assertEqual(recipe["categories"], [e["name"] for e in recipe[LABELS]])

    def test_statistiken_raknar_en_etikett_en_gang(self):
        """Adminpanelen räknade `Kött` och `kott` som två olika etiketter,
        vilket gjorde varje siffra om katalogen till en halv siffra."""
        by_label = self.store.stats()["byLabel"]
        self.assertEqual(by_label["Husmanskost"], 81)
        self.assertNotIn("husmanskost", by_label)
        self.assertEqual(by_label["Kött"], 39)

    def test_allergener_och_kosttyper_ror_ingen(self):
        """De är egna vokabulärer som svarar på andra frågor, och de var
        aldrig klassade åt två håll."""
        recipe = self.store.get("kottbullar-potatismos")
        self.assertIsInstance(recipe["allergens"], list)
        self.assertIsInstance(recipe["dietFlags"], list)
        allergener = {rad["value"] for rad in self.store.connection.execute(
            "SELECT DISTINCT value FROM recipe_labels WHERE kind = 'allergens'")}
        self.assertIn("ägg", allergener, "allergenerna ska bära sin egen form")


class EnGammalBankTest(unittest.TestCase):
    """En redan driftsatt bank ska bli konsekvent av att ÖPPNAS.

    Källorna skrivs om av sitt skript, men produktionens databas ligger på en
    disk och importeras bara när källornas fingeravtryck ändras. Bygger man
    inte om den lever felet kvar tills nästa receptändring."""

    def _gammal_bank(self, katalog: Path, etiketter: dict) -> Path:
        """En bank med FÖRE-M4-form: kind 'categories' och 'tags', ingen
        position, visningsnamn i `value`."""
        väg = katalog / "gammal.db"
        store = RecipeStore(väg)
        for recipe_id in etiketter:
            store.upsert_recipe({
                "id": recipe_id, "slug": recipe_id, "name": recipe_id.title(),
                "servings": 4, "mealType": "middag",
                "ingredients": [{"name": "Pasta", "amount": 400, "unit": "g"}],
                "instructions": ["Koka."]})
        store.close()
        anslutning = sqlite3.connect(väg)
        anslutning.execute("DELETE FROM recipe_labels")
        for recipe_id, (kategorier, taggar) in etiketter.items():
            for kind, värden in (("categories", kategorier), ("tags", taggar)):
                for värde in värden:
                    anslutning.execute(
                        "INSERT INTO recipe_labels (recipe_id, kind, value) "
                        "VALUES (?, ?, ?)", (recipe_id, kind, värde))
        anslutning.commit()
        anslutning.close()
        return väg

    def test_felet_reproduceras_i_den_gamla_formen(self):
        """Först: visa att det GAMLA sättet att fråga verkligen halverar.

        Ett facit som bara stämmer när testet räknar ut det själv är inget
        facit - så felet ställs upp i miniatyr och mäts."""
        with tempfile.TemporaryDirectory() as tmp:
            väg = self._gammal_bank(Path(tmp), {
                "en": (["Kött"], []), "tva": ([], ["kott"])})
            anslutning = sqlite3.connect(väg)
            self.addCleanup(anslutning.close)
            gamla_fragan = anslutning.execute(
                "SELECT COUNT(DISTINCT recipe_id) FROM recipe_labels "
                "WHERE kind IN ('tags','categories') AND value = ?", ("kott",))
            self.assertEqual(gamla_fragan.fetchone()[0], 1,
                             "den gamla likhetsfrågan hittade båda - då finns "
                             "inget fel att rätta och testet bevisar ingenting")
            anslutning.close()
            store = RecipeStore(väg)
            self.addCleanup(store.close)
            self.assertEqual(len(store.search(tags=["kott"])), 2)
            self.assertEqual(len(store.search(tags=["Kött"])), 2)

    def test_en_gammal_bank_blir_ett_falt_av_att_oppnas(self):
        with tempfile.TemporaryDirectory() as tmp:
            väg = self._gammal_bank(Path(tmp), {
                "en": (["Husmanskost", "Kött"], ["husmanskost", "barn"]),
                "tva": (["Pasta"], ["snabbt"])})
            store = RecipeStore(väg)
            self.addCleanup(store.close)
            kinder = sorted({rad["kind"] for rad in store.connection.execute(
                "SELECT DISTINCT kind FROM recipe_labels")})
            self.assertEqual(kinder, [LABELS])
            self.assertEqual(store.get("en")["tags"], ["husmanskost", "kott", "barn"])
            self.assertEqual(store.get("en")["categories"],
                             ["Husmanskost", "Kött", "Barn"])
            self.assertEqual(store.get("tva")["tags"], ["pasta", "snabbt"])

    def test_ordningen_overlever_migreringen(self):
        """Kategorierna först, i den ordning `ORDER BY kind, value` gav dem -
        så att badgen på kortet är samma text efter som före."""
        with tempfile.TemporaryDirectory() as tmp:
            väg = self._gammal_bank(Path(tmp), {
                "en": (["Kött", "Familj"], ["vardagsmat", "barn"])})
            store = RecipeStore(väg)
            self.addCleanup(store.close)
            self.assertEqual(store.get("en")["categories"][0], "Familj")
            self.assertEqual(store.get("en")["tags"],
                             ["familj", "kott", "barn", "vardagsmat"])

    def test_migreringen_tal_att_koras_om(self):
        """Render startar om, en deploy körs om, ett rollback följs av en ny
        framåtdeploy. Samma migration körs flera gånger mot samma databas."""
        with tempfile.TemporaryDirectory() as tmp:
            väg = self._gammal_bank(Path(tmp), {
                "en": (["Husmanskost"], ["husmanskost", "barn"])})
            forst = RecipeStore(väg)
            etiketter = forst.get("en")["tags"]
            forst.close()
            for _ in range(3):
                igen = RecipeStore(väg)
                self.assertEqual(igen.get("en")["tags"], etiketter)
                igen.close()

    def test_ingen_etikett_forsvinner_i_migreringen(self):
        with tempfile.TemporaryDirectory() as tmp:
            väg = self._gammal_bank(Path(tmp), {
                "en": (["Soppor", "Ris"], ["billigt", "mealprep", "bulk"])})
            store = RecipeStore(väg)
            self.addCleanup(store.close)
            self.assertEqual(sorted(store.get("en")["tags"]),
                             ["billigt", "bulk", "mealprep", "ris", "soppor"])


class ListanTest(unittest.TestCase):
    """Modulen som är facit."""

    def test_nyckeln_har_samma_harledning_som_ingrediens_id(self):
        """Uppdraget säger "samma form som `normalize_ingredient_id` redan
        använder". Två kopior av en regel driver isär - den här håller ihop
        dem."""
        for text in ("Kött", "Snabbt & enkelt", "  HUSMANSKOST  ", "Ägg och äpple",
                     "mealprep", "Crème fraîche"):
            self.assertEqual(normalize_label_id(text), normalize_ingredient_id(text))

    def test_versalisering_och_diakriter_ger_samma_nyckel(self):
        self.assertEqual(normalize_label_id("Kött"), "kott")
        self.assertEqual(normalize_label_id("KÖTT "), "kott")
        self.assertEqual(normalize_label_id("kott"), "kott")
        self.assertEqual(normalize_label_id("Snabbt & enkelt"), "snabbt-enkelt")

    def test_namnet_ar_en_funktion_av_nyckeln(self):
        """Namnet lagras inte per rad. Två rader kan därför inte bära olika
        namn för samma etikett - det är just den driften M4 städar bort."""
        for text in ("Kött", "kott", "KÖTT", " kött "):
            self.assertEqual(display(text), "Kött")

    def test_namnet_bar_tillbaka_det_nyckeln_tappade(self):
        """`snabbt-enkelt` är skälet till att tabellen inte kan ersättas av
        `.title()`: nyckeln har tappat sitt "&"."""
        self.assertEqual(display("snabbt-enkelt"), "Snabbt & enkelt")
        self.assertEqual(display("Snabbt & enkelt"), "Snabbt & enkelt")

    def test_en_okand_etikett_far_ett_lasbart_namn(self):
        """Värdeförrådet är öppet - bara formatet är stängt."""
        self.assertEqual(display("nyttig-vardag"), "Nyttig vardag")
        self.assertEqual(display("Nyttig Vardag"), "Nyttig vardag")
        self.assertEqual(display(""), "")
        self.assertEqual(display(None), "")

    def test_varje_namn_i_listan_normaliserar_tillbaka_till_sin_nyckel(self):
        fel = [(k, v) for k, v in DISPLAY_NAMES.items() if normalize_label_id(v) != k]
        self.assertEqual(fel, [], f"namn som inte hör till sin nyckel: {fel}")

    def test_sammanslagningen_behaller_ordningen_och_tar_bort_dubbletten(self):
        self.assertEqual(merge(["Husmanskost", "Kött"], ["husmanskost", "barn"]),
                         ["husmanskost", "kott", "barn"])
        self.assertEqual(merge(None, [], ["a"]), ["a"])
        self.assertEqual(merge([{"key": "kott", "name": "Kött"}], ["Kött"]), ["kott"])


class HyllornaTest(unittest.TestCase):
    """Hyllorna på receptsidan är frågor, och en fråga i fel format ger en tom
    hylla - som ser ut som "vi har inga sådana recept"."""

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

    def test_varje_hylla_fragar_i_nyckelform(self):
        fel = [(hylla["key"], tag) for hylla in SHELVES
               for tag in hylla.get("tags") or [] if normalize_label_id(tag) != tag]
        self.assertEqual(fel, [], f"hyllor som frågar i fel format: {fel}")

    def test_ingen_taggad_hylla_ar_tom(self):
        for hylla in SHELVES:
            if not hylla.get("tags"):
                continue
            träffar = self.store.search(tags=hylla["tags"], limit=500)
            self.assertTrue(träffar, f"hyllan {hylla['key']} är tom")


if __name__ == "__main__":
    unittest.main()
