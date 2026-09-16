# -*- coding: utf-8 -*-
"""P04a: `docs/RECEPTIDENTITET.md` påstår saker om källfilerna — då prövas de.

Dokumentet klassificerar 29 par (plus paren utanför tröskeln) som exakt
dubblett, samma rätt, legitim variant eller olika rätter, och föreslår vilka
id som blir alias för vilka. Ett sådant dokument är värt något bara så länge
det stämmer med `backend/recipe_sources/*.json`. Ett omdöpt id, en ändrad
ingredienslista eller ett nytt recept som råkar likna ett gammalt gör
dokumentet inaktuellt utan att någon ser det — så här räknas allt om.

Tre tabeller läses ur dokumentet, avgränsade med HTML-kommentarer:

    <!-- par29:start -->        de 29 paren, med Jaccard och namnlikhet
    <!-- extra:start -->        paren utanför de 29
    <!-- aliasgrupper:start --> kanoniskt id -> alias

Testerna tål paket 2: ett id som tagits ur källorna som recept godkänns om
det står som `aliases` på ett kanoniskt recept, och likhetstalen räknas bara
om för par där båda recepten fortfarande finns.
"""

import json
import re
import sys
import unittest
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.recipes import api as recipes_api  # noqa: E402
from services.recipes.store import normalize_ingredient_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOKUMENT = ROOT / "docs" / "RECEPTIDENTITET.md"

KLASSER = ("EXAKT DUBBLETT", "SAMMA RÄTT, NAMNVARIANT", "LEGITIM VARIANT", "OLIKA RÄTTER")
SLAS_IHOP = ("EXAKT DUBBLETT", "SAMMA RÄTT, NAMNVARIANT")
AXLAR = ("klassisk", "billig", "snabb", "protein", "vego")
TROSKEL = 0.70

_ID = re.compile(r"`([a-z0-9-]+)`")


def _kallor():
    """{id: recept} ur källfilerna, plus {alias: kanoniskt} för alias som
    deklarerats på ett recept (paket 2:s form)."""
    recept, alias = {}, {}
    for path in sorted(recipes_api.RECIPE_SOURCE_DIR.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            recept[r["id"]] = r
            for gammalt in r.get("aliases") or []:
                alias[gammalt] = r["id"]
    return recept, alias


def _ingrediens_id(recept):
    return {normalize_ingredient_id(i["name"]) for i in recept.get("ingredients") or []}


def jaccard(a, b):
    ia, ib = _ingrediens_id(a), _ingrediens_id(b)
    return len(ia & ib) / len(ia | ib) if (ia | ib) else 0.0


def namnlikhet(a, b):
    return SequenceMatcher(None, a["name"].lower(), b["name"].lower()).ratio()


def _avsnitt(text, namn):
    start = text.index(f"<!-- {namn}:start -->")
    slut = text.index(f"<!-- {namn}:slut -->", start)
    return text[start:slut]


def _tabellrader(avsnitt):
    """Cellerna i varje datarad (rubrik- och strecklinjer bort)."""
    rader = []
    for rad in avsnitt.splitlines():
        rad = rad.strip()
        if not rad.startswith("|") or rad.startswith("|---"):
            continue
        celler = [c.strip() for c in rad.strip("|").split("|")]
        if celler[0] in ("#", "kanoniskt"):
            continue
        rader.append(celler)
    return rader


def _par(avsnitt):
    """[(a, b, jaccard, namn, klass)] ur en partabell."""
    ut = []
    for celler in _tabellrader(avsnitt):
        ids = _ID.findall(celler[1])
        assert len(ids) == 2, f"raden bär inte två id: {celler[1]!r}"
        ut.append((ids[0], ids[1], float(celler[2]), float(celler[3]), celler[4]))
    return ut


def _aliasgrupper(avsnitt):
    """[(kanoniskt, alias, klass)]."""
    ut = []
    for celler in _tabellrader(avsnitt):
        kanoniskt, alias = _ID.findall(celler[0]), _ID.findall(celler[1])
        assert len(kanoniskt) == 1 and len(alias) == 1, f"raden är inte ett par: {celler[:2]!r}"
        ut.append((kanoniskt[0], alias[0], celler[2]))
    return ut


class Dokumentet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOKUMENT.read_text(encoding="utf-8")
        cls.recept, cls.alias = _kallor()
        cls.par29 = _par(_avsnitt(cls.text, "par29"))
        cls.extra = _par(_avsnitt(cls.text, "extra"))
        cls.grupper = _aliasgrupper(_avsnitt(cls.text, "aliasgrupper"))

    def _finns(self, recept_id):
        return recept_id in self.recept or recept_id in self.alias


class TabellernaArFulla(Dokumentet):
    def test_de_29_paren_ar_29(self):
        self.assertEqual(len(self.par29), 29)

    def test_paren_utanfor_och_aliasgrupperna_finns(self):
        self.assertGreater(len(self.extra), 0)
        self.assertGreater(len(self.grupper), 0)

    def test_inget_par_star_tva_ganger(self):
        alla = [frozenset((a, b)) for a, b, *_ in self.par29 + self.extra]
        self.assertEqual(len(alla), len(set(alla)))


class VarjeIdFinns(Dokumentet):
    def test_varje_id_i_partabellerna_finns_i_kallorna(self):
        for a, b, *_ in self.par29 + self.extra:
            for recept_id in (a, b):
                self.assertTrue(self._finns(recept_id),
                                f"{recept_id} finns varken som recept eller som alias i källorna")

    def test_varje_id_i_aliastabellen_finns_i_kallorna(self):
        for kanoniskt, alias, _ in self.grupper:
            self.assertIn(kanoniskt, self.recept, f"det kanoniska {kanoniskt} är inget recept")
            self.assertTrue(self._finns(alias), f"aliaset {alias} finns inte i källorna")


class LikhetstalenStammer(Dokumentet):
    """Talen i dokumentet är räknade med bankens egen nyckel. Ändras en
    ingredienslista ändras talet - och då ska dokumentet säga till."""

    def _prova(self, par):
        for a, b, jac, namn, _ in par:
            if a in self.recept and b in self.recept:
                with self.subTest(par=f"{a} <-> {b}"):
                    self.assertAlmostEqual(jaccard(self.recept[a], self.recept[b]), jac, places=3)
                    self.assertAlmostEqual(namnlikhet(self.recept[a], self.recept[b]), namn, places=3)
            else:
                # Paket 2 har slagit ihop dem: då ska det ena vara alias för
                # det andra, inte bara borta.
                with self.subTest(par=f"{a} <-> {b}"):
                    self.assertTrue(self.alias.get(a) == b or self.alias.get(b) == a,
                                    f"{a}/{b}: ett av recepten är borta utan att vara alias")

    def test_de_29_paren(self):
        self._prova(self.par29)

    def test_paren_utanfor(self):
        self._prova(self.extra)

    def test_de_29_ligger_over_troskeln_och_de_andra_under(self):
        for a, b, jac, *_ in self.par29:
            self.assertGreaterEqual(jac, TROSKEL, f"{a}/{b} hör inte till de 29")
        for a, b, jac, *_ in self.extra:
            self.assertLess(jac, TROSKEL, f"{a}/{b} hör till de 29, inte till paren utanför")


class KlassernaArDeFyra(Dokumentet):
    def test_varje_par_har_en_av_fyra_klasser(self):
        for a, b, _, _, klass in self.par29 + self.extra:
            with self.subTest(par=f"{a} <-> {b}"):
                self.assertTrue(klass.startswith(KLASSER), f"okänd klass {klass!r}")
                if klass.startswith("LEGITIM VARIANT"):
                    axel = re.search(r"\((\w+)\)", klass)
                    self.assertIsNotNone(axel, f"{klass!r} anger ingen axel")
                    self.assertIn(axel.group(1), AXLAR)


class AliasgruppernaFoljerKlassificeringen(Dokumentet):
    """Slå aldrig ihop blint: bara par som är samma rätt får bli alias, och
    varje par som är samma rätt ska ha en grupp."""

    def test_aliastabellen_bar_bara_samma_ratt(self):
        for kanoniskt, alias, klass in self.grupper:
            self.assertTrue(klass.startswith(SLAS_IHOP),
                            f"{kanoniskt}/{alias} är {klass!r} och får inte bli alias")

    def test_grupperna_ar_disjunkta_och_kanoniskt_ar_aldrig_alias(self):
        kanoniska = [k for k, _, _ in self.grupper]
        alias = [a for _, a, _ in self.grupper]
        self.assertEqual(len(alias), len(set(alias)), "samma alias i två grupper")
        self.assertEqual(set(kanoniska) & set(alias), set(), "ett kanoniskt id är alias någon annanstans")
        for kanoniskt, a, _ in self.grupper:
            self.assertNotEqual(kanoniskt, a)

    def test_varje_par_som_ar_samma_ratt_har_en_grupp_och_inget_annat_par_har_det(self):
        grupper = {frozenset((k, a)) for k, a, _ in self.grupper}
        for a, b, _, _, klass in self.par29 + self.extra:
            with self.subTest(par=f"{a} <-> {b}"):
                if klass.startswith(SLAS_IHOP):
                    self.assertIn(frozenset((a, b)), grupper, f"{a}/{b} är samma rätt men har ingen aliasgrupp")
                else:
                    self.assertNotIn(frozenset((a, b)), grupper, f"{a}/{b} är {klass!r} men står som alias")

    def test_deklarerade_alias_i_kallorna_ar_dokumentets(self):
        # Paket 2 skriver `aliases` i källfilerna. De ska vara exakt de här.
        dokumentets = {a: k for k, a, _ in self.grupper}
        for alias, kanoniskt in self.alias.items():
            self.assertEqual(dokumentets.get(alias), kanoniskt,
                             f"källorna deklarerar {alias} -> {kanoniskt}, dokumentet säger "
                             f"{dokumentets.get(alias)}")


class SammanfattningenArTabellerna(Dokumentet):
    def _rakna(self, par):
        return tuple(sum(1 for *_, klass in par if klass.startswith(k))
                     for k in ("EXAKT DUBBLETT", "SAMMA RÄTT", "LEGITIM VARIANT", "OLIKA RÄTTER"))

    def test_utfallet_for_de_29(self):
        träff = re.search(r"Utfall för de 29 paren: \*\*(\d+)\*\* exakta dubbletter · \*\*(\d+)\*\* "
                          r"samma rätt,\s+namnvariant · \*\*(\d+)\*\* legitima varianter · "
                          r"\*\*(\d+)\*\* olika rätter", self.text)
        self.assertIsNotNone(träff, "sammanfattningsraden för de 29 saknas")
        self.assertEqual(tuple(int(x) for x in träff.groups()), self._rakna(self.par29))

    def test_utfallet_utanfor(self):
        träff = re.search(r"Utanför de 29 \(.*?\): \*\*(\d+)\*\* exakta dubbletter · \*\*(\d+)\*\* "
                          r"samma rätt,\s+namnvariant · \*\*(\d+)\*\*\s+legitima varianter · "
                          r"\*\*(\d+)\*\* olika rätter", self.text, re.S)
        self.assertIsNotNone(träff, "sammanfattningsraden för paren utanför saknas")
        self.assertEqual(tuple(int(x) for x in träff.groups()), self._rakna(self.extra))

    def test_antalet_aliasgrupper(self):
        träff = re.search(r"Totalt föreslås \*\*(\d+) aliasgrupper\*\*", self.text)
        self.assertIsNotNone(träff)
        self.assertEqual(int(träff.group(1)), len(self.grupper))


class KallornaSjalva(Dokumentet):
    """Två påståenden om banken som inte beror på dokumentets siffror."""

    def test_ingen_exakt_dubblett_finns_i_kallorna(self):
        # Samma köp (namn, mängd, enhet) OCH samma steg = samma recept under
        # två id. Fanns inte när dokumentet skrevs; ska inte kunna smyga in.
        def avtryck(r):
            rader = tuple((i["name"], i.get("amount"), i.get("unit")) for i in r.get("ingredients") or [])
            return rader, tuple(r.get("instructions") or [])
        sedda = {}
        for recept_id, r in self.recept.items():
            nyckel = avtryck(r)
            self.assertNotIn(nyckel, sedda, f"{recept_id} är en exakt dubblett av {sedda.get(nyckel)}")
            sedda[nyckel] = recept_id

    def test_varje_par_over_troskeln_ar_klassificerat(self):
        # Importkontrollen roadmapen efterlyser, i sin enklaste form: ett nytt
        # recept som liknar ett gammalt till 0,70 på ingrediens-id måste
        # klassificeras i dokumentet innan det får ligga i banken.
        klassade = {frozenset((a, b)) for a, b, *_ in self.par29 + self.extra}
        oklassade = []
        for a, b in combinations(sorted(self.recept), 2):
            if jaccard(self.recept[a], self.recept[b]) >= TROSKEL and frozenset((a, b)) not in klassade:
                oklassade.append(f"{a} <-> {b}")
        self.assertEqual(oklassade, [],
                         "par över tröskeln utan klassificering - avgör dem i "
                         f"docs/RECEPTIDENTITET.md: {oklassade}")


if __name__ == "__main__":
    unittest.main()
