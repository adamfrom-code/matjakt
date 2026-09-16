# -*- coding: utf-8 -*-
"""P04b: ett recept-id är för alltid.

docs/RECEPTIDENTITET.md avgjorde att tio rätter låg i banken under två id
var. Det receptet som blev kvar bär det andra id:t som alias, och allt som
någonsin sparat det gamla id:t - en favorit, en vecka, en historikpost, en
delad länk - ska fortsätta öppna samma rätt. Testerna nedan är acceptansen:

  - ett alias öppnar rätt recept, i lagret och genom /api/recipes/<id>,
    transparent (200 med det kanoniska id:t, ingen omdirigering)
  - en vecka med ett gammalt id överlever prissättningen på serversidan
  - två id ur samma grupp planeras aldrig samma vecka: ett alias är ingen
    rad, så det finns inte bland veckokandidaterna
  - raden vinner över aliaset - det är återställningsplanen
  - reservbanken bär aliasen, så offlineläget kan peka om lika bra
  - schemat är stämplat 3 och fixturen regenererad
"""

import http.client
import json
import re
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
from services.recipes.store import RecipeStore  # noqa: E402
from services.schema_version import RECEPT, läs  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOKUMENT = ROOT / "docs" / "RECEPTIDENTITET.md"
RESERVBANK = ROOT / "frontend" / "app" / "data" / "recipes.json"
FIXTUR = ROOT / "backend" / "tests" / "fixturer" / "scheman" / "recept.sql"

_ID = re.compile(r"`([a-z0-9-]+)`")


def kallorna():
    """{id: recept} och {alias: kanoniskt} ur källfilerna."""
    recept, alias = {}, {}
    for path in sorted(recipes_api.RECIPE_SOURCE_DIR.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            recept[r["id"]] = r
            for gammalt in r.get("aliases") or []:
                alias[gammalt] = r["id"]
    return recept, alias


def dokumentets_grupper():
    text = DOKUMENT.read_text(encoding="utf-8")
    start = text.index("<!-- aliasgrupper:start -->")
    slut = text.index("<!-- aliasgrupper:slut -->", start)
    grupper = {}
    for rad in text[start:slut].splitlines():
        celler = [c.strip() for c in rad.strip().strip("|").split("|")]
        if len(celler) < 3 or celler[0] == "kanoniskt" or celler[0].startswith("---"):
            continue
        kanoniskt, alias = _ID.findall(celler[0]), _ID.findall(celler[1])
        if kanoniskt and alias:
            grupper[alias[0]] = kanoniskt[0]
    return grupper


KANONISKT = {
    "id": "rakpasta-vitlok", "name": "Räkpasta med vitlök och citron", "servings": 4,
    "mealType": "middag", "protein": 28, "kcal": 510, "totalTime": 22,
    "ingredients": [{"name": "Räkor", "amount": 400, "unit": "g"},
                    {"name": "Spaghetti", "amount": 400, "unit": "g"}],
    "instructions": ["Koka pastan.", "Vänd ner räkorna."],
    "labels": ["fisk", "pasta"], "allergens": ["skaldjur"], "dietFlags": ["blandkost"],
    "aliases": ["scampi"],
}


class KallornaDeklarerarAliasen(unittest.TestCase):
    def setUp(self):
        self.recept, self.alias = kallorna()

    def test_aliasen_ar_exakt_dokumentets_tio_grupper(self):
        self.assertEqual(self.alias, dokumentets_grupper())
        self.assertEqual(len(self.alias), 10)

    def test_ett_alias_ar_aldrig_ocksa_ett_recept(self):
        """Det finns bara ett recept per rätt. Ett id som är både rad och
        alias i KÄLLORNA är ett fel - i databasen tolereras det bara som ett
        mellanläge under import och återställning."""
        self.assertEqual(sorted(set(self.alias) & set(self.recept)), [])

    def test_ett_alias_ser_ut_som_ett_id(self):
        for alias in self.alias:
            self.assertRegex(alias, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_banken_har_230_kanoniska_recept(self):
        # 240 före P04b, tio blev alias. Talet står här för att en oavsiktlig
        # radering (eller en återuppväckt dubblett) ska synas som ett tal.
        self.assertEqual(len(self.recept), 230)


class LagretLoserAlias(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RecipeStore(Path(self._tmp.name) / "recipes.db")
        self.addCleanup(self.store.close)
        self.store.upsert_recipe(dict(KANONISKT))

    def test_aliaset_oppnar_det_kanoniska_receptet(self):
        recept = self.store.get("scampi")
        self.assertIsNotNone(recept)
        self.assertEqual(recept["id"], "rakpasta-vitlok")
        self.assertEqual(recept["canonicalId"], "rakpasta-vitlok")
        self.assertEqual(recept["aliases"], ["scampi"])

    def test_id_slug_och_alias_ger_samma_kanoniska_id(self):
        for fraga in ("rakpasta-vitlok", "rakpasta-med-vitlok-och-citron", "scampi"):
            with self.subTest(fraga=fraga):
                self.assertEqual(self.store.canonical_id(fraga), "rakpasta-vitlok")
        self.assertIsNone(self.store.canonical_id("finns-inte"))
        self.assertIsNone(self.store.get("finns-inte"))

    def test_ett_alias_ar_ingen_rad(self):
        """Sökningen, hyllorna och veckokandidaterna läser `recipes`. Att
        aliaset inte finns där är det som gör att planeraren aldrig kan
        föreslå samma rätt två gånger under två namn."""
        ids = [r["id"] for r in self.store.search()]
        self.assertEqual(ids, ["rakpasta-vitlok"])
        self.assertEqual(self.store.count(), 1)
        self.assertEqual(self.store.stats()["aliases"], 1)

    def test_raden_vinner_over_aliaset(self):
        """Återställningsplanen. Återställs `scampi` ur git finns id:t både
        som rad och som alias - och raden ska svara, inte pekaren."""
        self.store.upsert_recipe({**KANONISKT, "id": "scampi", "name": "Scampi pasta",
                                  "aliases": []})
        self.assertEqual(self.store.get("scampi")["id"], "scampi")
        self.assertEqual(self.store.get("scampi")["name"], "Scampi pasta")
        # Beskärningen tar raden igen - då är det pekaren som gäller.
        self.assertTrue(self.store.delete("scampi"))
        self.assertEqual(self.store.get("scampi")["id"], "rakpasta-vitlok")

    def test_en_skrivning_utan_faltet_behaller_aliasen(self):
        """Bildbakfyllningen skriver hela recept den läst ur databasen; ett
        äldre skript skriver recept utan `aliases`. Ingen av dem får koppla
        loss tio gamla id från sina rätter."""
        utan = {k: v for k, v in KANONISKT.items() if k != "aliases"}
        self.store.upsert_recipe(utan)
        self.assertEqual(self.store.get("scampi")["id"], "rakpasta-vitlok")
        # Ett MEDSKICKAT tomt fält är däremot en avsikt.
        self.store.upsert_recipe({**KANONISKT, "aliases": []})
        self.assertIsNone(self.store.get("scampi"))

    def test_ett_alias_far_inte_peka_pa_sig_sjalvt(self):
        with self.assertRaises(ValueError):
            self.store.upsert_recipe({**KANONISKT, "aliases": ["rakpasta-vitlok"]})
        with self.assertRaises(ValueError):
            self.store.upsert_recipe({**KANONISKT, "aliases": [""]})

    def test_aliaset_flyttar_med_den_senaste_importen(self):
        """Källorna är sanningen: pekar en nyare källa aliaset på ett annat
        recept följer pekaren med, i stället för att den första skrivningen
        låser den för alltid."""
        self.store.upsert_recipe({**KANONISKT, "id": "annan-pasta", "name": "Annan pasta"})
        self.assertEqual(self.store.get("scampi")["id"], "annan-pasta")

    def test_aliasen_forsvinner_med_receptet(self):
        self.assertTrue(self.store.delete("rakpasta-vitlok"))
        self.assertIsNone(self.store.get("scampi"))
        self.assertEqual(self.store.stats()["aliases"], 0)

    def test_databasen_ar_stamplad_3_och_bar_tabellen(self):
        self.assertEqual(RECEPT, 3)
        self.assertEqual(läs(self.store.connection), 3)
        tabeller = {row[0] for row in self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("recipe_aliases", tabeller)


class BankenUrKallorna(unittest.TestCase):
    """Samma krav på banken importen bygger - vägen in kan tappa fältet."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.store = RecipeStore(Path(cls._tmp.name) / "recipes.db")
        recipes_api.import_sources(cls.store)
        cls.recept, cls.alias = kallorna()

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls._tmp.cleanup()

    def test_varje_alias_oppnar_sitt_kanoniska_recept(self):
        for alias, kanoniskt in self.alias.items():
            with self.subTest(alias=alias):
                self.assertEqual(self.store.get(alias)["id"], kanoniskt)
                self.assertIn(alias, self.store.get(kanoniskt)["aliases"])

    def test_inget_alias_finns_bland_middagskandidaterna(self):
        kandidater = {r["id"] for r in self.store.search(meal_type="middag", limit=500)}
        self.assertEqual(sorted(set(self.alias) & kandidater), [])
        for alias, kanoniskt in self.alias.items():
            with self.subTest(grupp=f"{kanoniskt}/{alias}"):
                self.assertLessEqual(len({alias, kanoniskt} & kandidater), 1,
                                     "två id ur samma grupp bland kandidaterna")

    def test_stats_raknar_tio_alias_och_230_recept(self):
        stats = self.store.stats()
        self.assertEqual(stats["aliases"], 10)
        self.assertEqual(stats["total"], 230)


class ServernSvararTransparent(unittest.TestCase):
    """/api/recipes/<alias>: 200 med det kanoniska receptet. Inte 302 -
    fetch följer en omdirigering ändå, service workern cachar på exakt
    URL, och delade länkar bär det gamla id:t."""

    @classmethod
    def setUpClass(cls):
        recipes_api.bootstrap_if_empty()
        recipes_api.clear_cache()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.recept, cls.alias = kallorna()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=json.dumps(body) if body is not None else None,
                         headers=headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            conn.close()

    def test_ett_alias_ger_200_och_det_kanoniska_receptet(self):
        for alias, kanoniskt in self.alias.items():
            with self.subTest(alias=alias):
                status, payload = self._request("GET", f"/api/recipes/{alias}")
                self.assertEqual(status, 200, payload)
                self.assertEqual(payload["recipe"]["id"], kanoniskt)
                self.assertEqual(payload["recipe"]["canonicalId"], kanoniskt)
                self.assertIn(alias, payload["recipe"]["aliases"])

    def test_ett_okant_id_ar_fortfarande_404(self):
        status, _ = self._request("GET", "/api/recipes/finns-inte-alls")
        self.assertEqual(status, 404)

    def test_listan_bar_aliasen_pa_varje_kort(self):
        """Appen bygger sin karta gammalt -> kanoniskt ur just den här listan."""
        status, payload = self._request("GET", "/api/recipes?limit=500")
        self.assertEqual(status, 200)
        kort = {r["id"]: r for r in payload["recipes"]}
        self.assertEqual(sorted(set(self.alias) & set(kort)), [], "ett alias ligger i listan")
        for alias, kanoniskt in self.alias.items():
            self.assertIn(alias, kort[kanoniskt]["aliases"], kanoniskt)
        self.assertTrue(all("aliases" in r and "canonicalId" in r for r in payload["recipes"]))

    def test_veckokandidaterna_har_hogst_ett_id_per_grupp(self):
        kandidater = {r["id"] for r in recipes_api.week_candidates()}
        self.assertGreater(len(kandidater), 100)
        for alias, kanoniskt in self.alias.items():
            self.assertNotIn(alias, kandidater)
            self.assertLessEqual(len({alias, kanoniskt} & kandidater), 1)

    def test_en_vecka_med_ett_gammalt_id_prissatts_som_sin_ratt(self):
        """Serverns prissättning slår upp varje recipeId i banken. Ett okänt
        id hoppas över tyst - och en vecka som bara bar gamla id blev
        'Inga av recepten finns i receptbanken'. Med alias är det samma
        vecka som förut."""
        alias = next(iter(self.alias))
        status, payload = self._request("POST", "/api/pricing/week",
                                        {"recipeIds": [alias], "people": 2})
        self.assertNotEqual((payload or {}).get("error"), "Inga av recepten finns i receptbanken",
                            (status, payload))
        # Kontrollen: ett id som inte är någonting alls ger just det felet.
        status, payload = self._request("POST", "/api/pricing/week",
                                        {"recipeIds": ["finns-inte-alls"], "people": 2})
        self.assertEqual((payload or {}).get("error"), "Inga av recepten finns i receptbanken",
                         (status, payload))


class ReservbankenBarAliasen(unittest.TestCase):
    def test_reservbanken_ar_kanonisk_och_bar_aliasen(self):
        bank = {r["id"]: r for r in json.loads(RESERVBANK.read_text(encoding="utf-8"))}
        _, alias = kallorna()
        self.assertEqual(sorted(set(alias) & set(bank)), [], "ett alias ligger i reservbanken")
        for gammalt, kanoniskt in alias.items():
            self.assertIn(gammalt, bank[kanoniskt].get("aliases") or [], kanoniskt)


class FixturenArDagensSchema(unittest.TestCase):
    """Baslinjen ska vara det schema som står i drift efter den här mergen
    (varje merge deployas) - annars prövas den här migrationen aldrig."""

    def test_recept_sql_bar_aliastabellen_och_version_3(self):
        text = FIXTUR.read_text(encoding="utf-8")
        self.assertIn("recipe_aliases", text)
        self.assertIn("PRAGMA user_version = 3;", text)


if __name__ == "__main__":
    unittest.main()
