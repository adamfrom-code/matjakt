# -*- coding: utf-8 -*-
"""A01: gratis och kompenserad Premium får inte räknas som betalande.

Tratten räknade en boolean, så en inlöst kod och en betalande prenumerant
blev samma siffra. För en ägare som ska avgöra om affären bär är det just
den siffran som inte får blandas ihop - och felet syns inte i ett tal som
bara blir större."""

import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.accounts.store import AccountStore  # noqa: E402
from services.analytics.store import AnalyticsStore  # noqa: E402


def _rad(**fält):
    """En users-rad som _to_public kan läsa. Bara nycklarna den rör."""
    grund = {"email": "a@b.se", "premium": 0, "trial_ends_at": None, "trial_used": 0,
             "subscription_status": None, "subscription_plan": None,
             "subscription_period_end": None, "subscription_cancel_at_period_end": 0,
             "email_verified": 1, "marketing_consent": 0}
    grund.update(fält)
    return grund


class PremiumKalla(unittest.TestCase):

    def _källa(self, **fält):
        return AccountStore._to_public(_rad(**fält))["premiumSource"]

    def test_en_betalande_prenumeration_heter_subscription(self):
        framtid = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        self.assertEqual(self._källa(subscription_status="active",
                                     subscription_period_end=framtid), "subscription")

    def test_en_inlost_kod_heter_comped_och_inte_betalande(self):
        self.assertEqual(self._källa(premium=1), "comped")

    def test_ett_prov_heter_trial(self):
        framtid = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        self.assertEqual(self._källa(trial_ends_at=framtid), "trial")

    def test_ett_gratiskonto_har_ingen_kalla(self):
        self.assertIsNone(self._källa())

    def test_den_som_bade_har_kod_och_betalar_raknas_som_betalande(self):
        # Sanningsordning, inte prioritetsordning: den som HAR en aktiv
        # prenumeration betalar, oavsett vilka andra flaggor som är satta.
        framtid = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        self.assertEqual(self._källa(premium=1, subscription_status="active",
                                     subscription_period_end=framtid), "subscription")

    def test_en_utgangen_prenumeration_ar_inte_betalande(self):
        # Fail closed: perioden har passerat utan att leverantören hört av
        # sig, alltså är kontot inte betalande - och inte Premium alls.
        dåtid = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        self.assertIsNone(self._källa(subscription_status="active",
                                      subscription_period_end=dåtid))


class TrattenSkiljerKallorna(unittest.TestCase):

    def test_tratten_delar_upp_premium_per_kalla(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            konto = AccountStore(Path(tmp) / "m.db")
            try:
                idag = datetime.now(timezone.utc)
                framtid = (idag + timedelta(days=20)).isoformat()
                for adress in ("betalar@x.se", "kod@x.se", "gratis@x.se"):
                    konto.register(adress, "hemligt123")
                konto.connection.execute(
                    "UPDATE users SET subscription_status='active', subscription_period_end=? WHERE email=?",
                    (framtid, "betalar@x.se"))
                konto.connection.execute("UPDATE users SET premium=1 WHERE email=?", ("kod@x.se",))
                konto.connection.commit()

                analys = AnalyticsStore(konto.connection)
                tratt = analys.funnel(
                    premium_of=lambda r: AccountStore._to_public(r)["premium"],
                    premium_source_of=lambda r: AccountStore._to_public(r)["premiumSource"])
            finally:
                konto.close()
        totalt = tratt["totalt"]
        self.assertEqual(totalt["premium"], 2, totalt)
        self.assertEqual(totalt["premiumBetalande"], 1, totalt)
        self.assertEqual(totalt["premiumKompenserad"], 1, totalt)
        self.assertEqual(totalt["premiumProv"], 0, totalt)
        # Det gamla talet finns kvar och är fortfarande summan av de premium
        # som finns - uppdelningen ersätter det inte, den förklarar det.
        self.assertGreaterEqual(totalt["premium"],
                                totalt["premiumBetalande"] + totalt["premiumKompenserad"])


if __name__ == "__main__":
    unittest.main()
