# -*- coding: utf-8 -*-
"""En släppt kedja måste kunna prissätta en kund som står var som helst.

D11 släppte ICA. Det är ett annat löfte än de tre tidigare: Willys och
Hemköp är centralt prissatta, så ett rikspris ÄR priset. ICA är handlarägt
och priserna skiljer sig bevisat mellan butiker, så ICA vilar på ett RIKTPRIS
byggt ur en referensbutik.

Den konstruktionen håller bara om två saker är sanna, och båda prövas här:

  1. Varje STORE_SPECIFIC-kedja i RELEASED_CHAINS har en referensbutik
     konfigurerad. Utan den publiceras aldrig några referenspriser
     (publish.publish_run sätter publish_reference bara för NATIONAL eller
     för kedjans egen referensbutik), och då står 462 av 463 ICA-butiker
     utan pris medan appen påstår att de är prisbara.

  2. Kunden får veta vad kröningen vilar på. En korg helt på riktpriser ska
     rapportera basis "reference", aldrig "verified".

Det andra är det som gör det ärligt. Ett riktpris som presenteras som ett
butikspris vore precis det fel hela prismotorn är byggd för att undvika.
"""

import unittest

from services.grocery.api import RELEASED_CHAINS
from services.grocery.pricing import (PRICING_BASIS_MIXED, PRICING_BASIS_REFERENCE,
                                      PRICING_BASIS_VERIFIED, _pricing_basis)
from services.grocery.register import CHAIN_OWNERSHIP, CHAIN_PRICING_SCOPE, CHAIN_REFERENCE_STORE


class SlapptKedjaKanPrissattaHelaLandet(unittest.TestCase):
    def test_varje_slappt_butiksspecifik_kedja_har_en_referensbutik(self):
        for kedja in RELEASED_CHAINS:
            scope = CHAIN_PRICING_SCOPE.get(kedja, "STORE_SPECIFIC")
            if scope != "STORE_SPECIFIC":
                continue
            self.assertIn(
                kedja, CHAIN_REFERENCE_STORE,
                f"{kedja} är släppt och butiksspecifik men saknar referensbutik. "
                f"Utan den publiceras inga referenspriser, och kedjans butiker "
                f"märks prisbara utan att kunna prissättas.")
            self.assertTrue(
                CHAIN_REFERENCE_STORE[kedja],
                f"{kedja}s referensbutik är tom")

    def test_ica_ar_slappt_och_vilar_pa_en_referensbutik(self):
        # ICA är fallet paketet gäller: rikstäckande genom riktpris, inte
        # genom att vi låtsas ha 463 butikskataloger.
        self.assertIn("ICA", RELEASED_CHAINS)
        self.assertEqual(CHAIN_PRICING_SCOPE["ICA"], "STORE_SPECIFIC")
        self.assertEqual(CHAIN_OWNERSHIP["ICA"], "FRANCHISE")
        self.assertTrue(CHAIN_REFERENCE_STORE.get("ICA"))

    def test_en_korg_helt_pa_riktpriser_rapporteras_som_referens(self):
        rader = [{"priceTier": "REFERENCE_PRICE"}, {"priceTier": "REFERENCE_PRICE"}]
        self.assertEqual(_pricing_basis(rader), PRICING_BASIS_REFERENCE)

    def test_en_enda_riktprisrad_racker_for_att_korgen_inte_ar_verifierad(self):
        # Det här är den viktiga riktningen: en korg får inte kallas
        # verifierad för att MESTADELS av raderna är det.
        rader = [{"priceTier": "VERIFIED_STORE_PRICE"}] * 9 + [{"priceTier": "REFERENCE_PRICE"}]
        self.assertEqual(_pricing_basis(rader), PRICING_BASIS_MIXED)
        self.assertNotEqual(_pricing_basis(rader), PRICING_BASIS_VERIFIED)

    def test_partnervagen_finns_for_en_handlarkedja(self):
        # Uppgraderingsvägen från riktpris till butiksverifierat pris: en
        # handlare tecknar per butik. Utan den är riktpriset en återvändsgränd.
        from services.grocery.register import CHAIN_PARTNER_MODEL
        self.assertEqual(CHAIN_PARTNER_MODEL.get("ICA"), "PER_STORE")


if __name__ == "__main__":
    unittest.main()
