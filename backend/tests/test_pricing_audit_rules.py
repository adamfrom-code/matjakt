# -*- coding: utf-8 -*-
"""Prisauditens egna regler - att gaten är röd av RÄTT skäl.

Bakgrund 2026-09-06. Auditen flaggade 317 rader som "kilopris visat som
paketpris" och höll releasegaten röd. Vid granskning hade samtliga 317
`perKg=True`: prismotorn hade räknat kr/kg × behovet, alltså helt rätt.
Regeln undantog `weightPriced` (vägen för paket över 150 g) men hade aldrig
uppdaterats med `perKg` (lösviktsvägen för småstyck, som kom senare).

En gate som står röd av fel skäl är farligare än en som står röd av rätt
skäl: den slutar betyda något, och nästa riktiga fel drunknar i bruset.
Testerna nedan låser fast båda undantagen OCH att regeln fortfarande
fångar det den finns för.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.data_guard import isolated_test_data_dir  # noqa: E402
isolated_test_data_dir()

from services.grocery.audit import run_pricing_audit  # noqa: E402


class _FakeRecipeStore:
    """Ett recept med en ingrediens - precis så mycket som auditen behöver."""

    class _Connection:
        def execute(self, _sql):
            return [{"id": "testrecept"}]

    connection = _Connection()

    def get(self, _recipe_id):
        return {"id": "testrecept", "servings": 4,
                "ingredients": [{"name": "Tomat", "amount": 2, "unit": "st"}]}


class _FakeEngineStore:
    """Bär bara raden auditen ska bedöma."""

    def __init__(self, row):
        self.row = row


def _audit_with(row, monkeypatch_target=None):
    """Kör auditen med EN förutbestämd prisrad och returnerar flaggorna."""
    from services.grocery import audit as audit_module
    from services.grocery import api as grocery_api

    original_engine = audit_module.RecipePricingEngine
    original_store_row = grocery_api._store_row_for

    class _Engine:
        def __init__(self, _store):
            pass

        def price_item(self, *_args, **_kwargs):
            return row

    audit_module.RecipePricingEngine = _Engine
    grocery_api._store_row_for = lambda _store, chain: {"id": 1, "name": chain}
    try:
        return run_pricing_audit(None, _FakeRecipeStore(), ["Willys"])
    finally:
        audit_module.RecipePricingEngine = original_engine
        grocery_api._store_row_for = original_store_row


# En viktvara med cirkavikt vars pris ÄR kilopriset. Skiljer sig bara i
# vilken väg motorn tog för att prissätta den.
def _variable_weight_row(**overrides):
    row = {
        "productName": "Tomat Runda Sverige Klass 1",
        "packageSize": "ca: 98g",
        "packageAmount": 98,
        "packageUnit": "g",
        "comparisonPrice": 44.9,
        "unitPrice": 44.9,
        "totalCost": 8.8,
        "packages": 1,
        "exactPackaging": True,
        "weightPriced": False,
        "perKg": False,
    }
    row.update(overrides)
    return row


class KiloPriceRuleTest(unittest.TestCase):
    def test_a_loose_weight_row_priced_per_kilo_is_not_flagged(self):
        """perKg=True betyder att motorn räknade kr/kg × behovet. Det är
        rätt pris, och exakt de 317 rader som höll gaten röd i onödan."""
        result = _audit_with(_variable_weight_row(perKg=True))
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 0)
        self.assertEqual(result["gate"], "GRÖN")

    def test_a_repriced_package_is_not_flagged(self):
        """weightPriced=True: paketpriset räknades om till kr/kg × cirkavikt.
        Undantaget som redan fanns - det får inte försvinna."""
        result = _audit_with(_variable_weight_row(weightPriced=True))
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 0)

    def test_an_actually_mispriced_row_is_still_caught(self):
        """Regeln finns för det HÄR: kilopriset taget rakt av som
        paketpris, utan att någon av motorns två vägar hanterat det.
        Fångas den inte längre är undantagen för breda."""
        result = _audit_with(_variable_weight_row())
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 1)
        self.assertEqual(result["gate"], "RÖD")

    def test_a_normal_package_is_never_flagged(self):
        """En vanlig förpackning utan cirkavikt ska aldrig träffas, oavsett
        vad priserna råkar vara."""
        result = _audit_with(_variable_weight_row(packageSize="500 g", packageAmount=500))
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 0)

    def test_a_one_kilo_package_is_not_flagged(self):
        """Ett kilopaket SKA ha pris == jämförpris. Det är aritmetik, inte
        ett fel."""
        result = _audit_with(_variable_weight_row(packageSize="ca: 1000g", packageAmount=1000))
        self.assertEqual(result["flaggor"]["kilopris_som_paketpris"], 0)


class GateDefinitionTest(unittest.TestCase):
    def test_the_gate_ignores_the_two_advisory_flags(self):
        """smakords_misstanke och saknade är VARNINGAR, inte fel: ett
        misstänkt smakord kan vara ett varumärke ("Familjefavoriter"), och
        en saknad rad är fail-closed - varan står kvar oprissatt i stället
        för att gissas. Ingen av dem får fälla gaten."""
        row = _variable_weight_row(perKg=True, productName="Grekisk Matyoghurt 10% Familjefavoriter")
        result = _audit_with(row)
        self.assertGreater(result["flaggor"]["smakords_misstanke"], 0)
        self.assertEqual(result["gate"], "GRÖN")

    def test_an_estimate_still_fails_the_gate(self):
        """Ett gissat antal får aldrig passera som ett pris."""
        result = _audit_with(_variable_weight_row(perKg=True, exactPackaging=False))
        self.assertEqual(result["flaggor"]["estimat"], 1)
        self.assertEqual(result["gate"], "RÖD")

    def test_an_unparsed_package_size_still_fails_the_gate(self):
        result = _audit_with(_variable_weight_row(perKg=False, packageAmount=None,
                                                 packageSize="okänd", comparisonPrice=None))
        self.assertEqual(result["flaggor"]["otolkad_paketstorlek"], 1)
        self.assertEqual(result["gate"], "RÖD")


if __name__ == "__main__":
    unittest.main()
