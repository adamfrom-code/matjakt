# -*- coding: utf-8 -*-
"""I7: mätningen som når fram till kronor.

Tratten var genuint bra - kohorter, betalande skilt från kompenserad,
mognadsflagga - men den räknade **konton, aldrig kronor**. Ingen MRR, ingen
ARPU, ingen churn. Och `ANALYTICS_EVENTS` saknade hela betalsteget, kontot,
hushållsinbjudan och mejlklicket, så trattens dyraste steg var osynligt.

Testet prövar tre saker:

  1. Att händelserna finns och tas emot - inklusive de tre `view_*` som appen
     redan skickade och servern svarade 400 på.
  2. Att kronorna är RÄKNADE och inte gissade: årsplanen periodiseras, en
     kompenserad Premium är noll kronor, och ett betalande konto med okänd
     plan räknas som noll och rapporteras separat i stället för att gömmas.
  3. Att de fem talen Adam ska se varje vecka går att räkna ur en
     fixturdatabas, med sina nämnare.

Nämnaren är inte en detalj. En andel räknad på konton som inte hunnit få sin
chans sjunker varje gång någon registrerar sig - det ser ut som en försämring
och är en artefakt. Flera tester nedan finns bara för att hålla fast det.
"""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.accounts import AccountStore, features
from services.analytics import (ACTIVATION_WINDOW_DAYS, ANALYTICS_EVENTS, MOMSSATS,
                                AnalyticsStore, manadsvarden)


def _dag(dagar_sedan: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=dagar_sedan)).isoformat()


class Bas(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.konton = AccountStore(Path(self._tmp.name) / "test.db")
        self.matning = AnalyticsStore(self.konton.connection, lock=self.konton.lock)

    def tearDown(self):
        self.konton.close()
        self._tmp.cleanup()

    def konto(self, epost: str, skapad_dagar_sedan: int = 30) -> int:
        self.konton.register(epost, "hemligt123")
        user_id = self.konton.connection.execute(
            "SELECT id FROM users WHERE email = ?", (epost,)).fetchone()[0]
        skapad = (datetime.now(timezone.utc) - timedelta(days=skapad_dagar_sedan)).isoformat()
        self.konton.connection.execute("UPDATE users SET created_at = ? WHERE id = ?",
                                       (skapad, user_id))
        self.konton.connection.commit()
        return user_id

    def betalande(self, user_id: int, plan: str = "monthly", *, cancel=False, sub="sub_1"):
        """Ett konto som betalleverantören säger är aktivt. Samma kolumner
        som Stripe-webhooken skriver - inte en egen sanning för testet."""
        slut = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
        self.konton.connection.execute(
            "UPDATE users SET subscription_status = 'active', subscription_plan = ?, "
            "subscription_period_end = ?, stripe_subscription_id = ?, "
            "subscription_cancel_at_period_end = ? WHERE id = ?",
            (plan, slut, sub, 1 if cancel else 0, user_id))
        self.konton.connection.commit()

    def tratt(self, **extra):
        return self.matning.funnel(
            premium_of=lambda row: AccountStore._to_public(row)["premium"],
            premium_source_of=lambda row: AccountStore._to_public(row)["premiumSource"],
            **extra)


class HandelserSomSaknades(Bas):
    def test_hela_betalsteget_gar_att_rakna(self):
        for händelse in ("konto_skapat", "premium_kop", "inbjudan_skickad",
                         "inbjudan_accepterad", "mail_klick", "checkout_startad",
                         "checkout_avbruten", "betalning_genomford",
                         "plan_vald_manad", "plan_vald_ar", "uppsagning_paborjad"):
            self.assertIn(händelse, ANALYTICS_EVENTS, f"{händelse} saknas i listan")
            self.assertTrue(self.matning.record(händelse, user_id=1), händelse)

    def test_vyerna_appen_redan_skickade_avvisas_inte_langre(self):
        """setView() i app.js skickar view_<vy> för VARJE vy. De tre nedan
        fanns inte i listan, så varje gång någon öppnade sparstatistiken,
        butiksjämförelsen eller kedjelistan svarade servern 400 och siffran
        försvann. Verifierat i produktionsloggen."""
        for vy in ("view_stats", "view_comparison", "view_chainlist"):
            self.assertTrue(self.matning.record(vy, user_id=1), vy)

    def test_listan_ar_fortfarande_stangd(self):
        """Klienten får inte hitta på namn - tabellerna ska aldrig kunna bli
        en plats att smuggla in identifierande data genom."""
        self.assertFalse(self.matning.record("konto_skapat_extra", user_id=1))
        self.assertFalse(self.matning.record("<script>", user_id=1))


class KronorRaknasInteGissas(Bas):
    def test_manadsvardena_kommer_ur_prislistan_inte_ur_en_kopia(self):
        """59 och 399 finns i services/accounts/features.py och ingen
        annanstans. Läser mätningen en egen kopia blir den fel dagen
        paketeringen ändras (J3)."""
        priser = manadsvarden()
        self.assertEqual(priser["monthly"], float(features.PRICING["monthly"]["pricePerMonth"]))
        self.assertAlmostEqual(priser["yearly"],
                               float(features.PRICING["yearly"]["pricePerYear"]) / 12.0, places=6)

    def test_arsplanen_periodiseras_i_stallet_for_att_bli_en_raket(self):
        """399 kr i MRR den månad någon betalar årsvis, och noll resten av
        året, hade fått varje mars att se ut som en raket."""
        self.betalande(self.konto("ar@example.com"), "yearly")
        totalt = self.tratt()["totalt"]
        self.assertAlmostEqual(totalt["mrrKronor"], round(399 / 12, 2), places=2)
        self.assertLess(totalt["mrrKronor"], 399)

    def test_mrr_arpu_och_moms(self):
        self.betalande(self.konto("a@example.com"), "monthly")
        self.betalande(self.konto("b@example.com"), "monthly", sub="sub_2")
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["premiumBetalande"], 2)
        self.assertAlmostEqual(totalt["mrrKronor"], 118.0, places=2)
        self.assertAlmostEqual(totalt["arpuKronor"], 59.0, places=2)
        # Priserna är satta inklusive moms (prisinformationslagen). Nettot -
        # det som blir intäkt - är brutto delat med 1,25.
        self.assertAlmostEqual(totalt["mrrExMomsKronor"], round(118.0 / (1 + MOMSSATS), 2), places=2)

    def test_kompenserad_premium_ar_noll_kronor(self):
        """En inlöst kod och en betalande prenumerant såg likadana ut i
        kontoräkningen. I kronor får de aldrig göra det."""
        user_id = self.konto("gratis@example.com")
        self.konton.connection.execute("UPDATE users SET premium = 1 WHERE id = ?", (user_id,))
        self.konton.connection.commit()
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["premium"], 1)
        self.assertEqual(totalt["premiumKompenserad"], 1)
        self.assertEqual(totalt["premiumBetalande"], 0)
        self.assertEqual(totalt["mrrKronor"], 0.0)

    def test_okand_plan_blir_noll_kronor_och_en_flagga_inte_en_gissning(self):
        """Ett okänt pris-id är en felkonfiguration (fel id i miljön, pris
        utbytt i Stripe). MRR blir då för LÅG - och en för låg intäktssiffra
        som ser exakt ut är sämre än ingen. Därför räknas kontot separat."""
        self.betalande(self.konto("okand@example.com"), plan=None)
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["premiumBetalande"], 1)
        self.assertEqual(totalt["mrrKronor"], 0.0)
        self.assertEqual(totalt["betalandeUtanKandPlan"], 1)

    def test_uppsagd_till_periodslut_rakas_med_i_mrr_men_flaggas(self):
        """Hon betalar fortfarande den här månaden. Att stryka henne ur MRR
        i förväg gör siffran fel åt andra hållet - men den som läser ska
        veta att intäkten är på väg bort."""
        self.betalande(self.konto("slutar@example.com"), "monthly", cancel=True)
        totalt = self.tratt()["totalt"]
        self.assertAlmostEqual(totalt["mrrKronor"], 59.0, places=2)
        self.assertEqual(totalt["sagerUppVidPeriodslut"], 1)

    def test_tappad_premium_ar_den_som_haft_en_prenumeration_och_inte_har_en(self):
        kvar = self.konto("kvar@example.com")
        borta = self.konto("borta@example.com")
        self.betalande(kvar, "monthly")
        self.betalande(borta, "monthly", sub="sub_borta")
        self.konton.connection.execute(
            "UPDATE users SET subscription_status = 'canceled' WHERE id = ?", (borta,))
        self.konton.connection.commit()
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["premiumBetalande"], 1)
        self.assertEqual(totalt["harHaftPrenumeration"], 2)
        self.assertEqual(totalt["tappadePremium"], 1)
        self.assertAlmostEqual(totalt["mrrKronor"], 59.0, places=2)

    def test_ingen_betalande_ger_noll_och_inte_en_division_med_noll(self):
        self.konto("gratis@example.com")
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["mrrKronor"], 0.0)
        self.assertEqual(totalt["arpuKronor"], 0.0)


class AktiveringInomTvaDygn(Bas):
    """Adam ville ha "inom 48 h". Tabellen lagrar DAG, aldrig klockslag - det
    är ett medvetet val i integritetspolicyn. Talet heter därför det det är."""

    def _konto_som_aktiverade(self, epost, skapad_dagar_sedan, aktiverad_dagar_sedan):
        user_id = self.konto(epost, skapad_dagar_sedan)
        self.matning.record("vecka_skapad", user_id=user_id, day=_dag(aktiverad_dagar_sedan))
        return user_id

    def test_fonstret_ar_tva_kalenderdagar_och_stangs(self):
        self.assertEqual(ACTIVATION_WINDOW_DAYS, 2)
        self._konto_som_aktiverade("dag0@example.com", 10, 10)
        self._konto_som_aktiverade("dag2@example.com", 10, 8)
        self._konto_som_aktiverade("dag3@example.com", 10, 7)   # en dag för sent
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["skapadeVeckaInomTvaDygn"], 2)
        self.assertEqual(totalt["mognaForSnabbfragan"], 3)

    def test_den_som_inte_hunnit_fa_sin_chans_rakas_inte_i_namnaren(self):
        """Registrerade sig i dag. Räknas hon in i nämnaren sjunker andelen
        varje gång någon nyfiken skapar ett konto - en försämring som inte
        hänt."""
        self._konto_som_aktiverade("gammal@example.com", 10, 10)
        self.konto("alldeles_ny@example.com", 0)
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["mognaForSnabbfragan"], 1)
        self.assertEqual(totalt["skapadeVeckaInomTvaDygn"], 1)

    def test_den_som_aldrig_aktiverade_rakas_i_namnaren(self):
        self.konto("tittade@example.com", 10)
        totalt = self.tratt()["totalt"]
        self.assertEqual(totalt["mognaForSnabbfragan"], 1)
        self.assertEqual(totalt["skapadeVeckaInomTvaDygn"], 0)


class HushallMedFlerAnEn(Bas):
    """household_members ligger i samma SQLite-fil som users."""

    def _hushall(self, household_id: int, *user_ids: int):
        self.konton.connection.execute(
            "CREATE TABLE IF NOT EXISTS household_members ("
            "household_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "role TEXT, display_name TEXT, profile TEXT, joined_at TEXT, revision INTEGER, "
            "PRIMARY KEY (household_id, user_id))")
        for user_id in user_ids:
            self.konton.connection.execute(
                "INSERT OR REPLACE INTO household_members (household_id, user_id, joined_at) "
                "VALUES (?, ?, ?)", (household_id, user_id, _dag(0)))
        self.konton.connection.commit()

    def test_tva_medlemmar_och_nagon_aktiv_rakas(self):
        a, b = self.konto("a@example.com", 10), self.konto("b@example.com", 10)
        self.matning.record("view_home", user_id=a, day=_dag(1))
        self._hushall(1, a, b)
        self.assertEqual(self.tratt()["totalt"]["aktivaHushallMedFlerAnEn"], 1)

    def test_ensam_i_sitt_hushall_rakas_inte(self):
        a = self.konto("ensam@example.com", 10)
        self.matning.record("view_home", user_id=a, day=_dag(1))
        self._hushall(2, a)
        self.assertEqual(self.tratt()["totalt"]["aktivaHushallMedFlerAnEn"], 0)

    def test_hushall_ingen_oppnat_pa_en_manad_ar_tva_gamla_rader(self):
        a = self.konto("gammal_a@example.com", 90)
        b = self.konto("gammal_b@example.com", 90)
        self._hushall(3, a, b)
        self.assertEqual(self.tratt()["totalt"]["aktivaHushallMedFlerAnEn"], 0)

    def test_databas_utan_hushallstabell_ger_noll_inte_ett_undantag(self):
        """Kontrollrummet ska inte falla för att hushållstjänsten aldrig
        körts i den här miljön."""
        self.konto("ensam@example.com", 10)
        with self.assertRaises(sqlite3.OperationalError):
            self.konton.connection.execute("SELECT 1 FROM household_members")
        self.assertEqual(self.tratt()["totalt"]["aktivaHushallMedFlerAnEn"], 0)


class DeFemTalen(Bas):
    """De fem talen Adam ska se varje vecka, räknade ur en fixturdatabas."""

    def setUp(self):
        super().setUp()
        ny = self.konto("ny@example.com", 2)
        gammal = self.konto("gammal@example.com", 20)
        betalande = self.konto("betalar@example.com", 30)
        self.matning.record("vecka_skapad", user_id=gammal, day=_dag(19))
        self.matning.record("view_home", user_id=gammal, day=_dag(1))
        self.matning.record("vecka_skapad", user_id=ny, day=_dag(2))
        self.betalande(betalande, "yearly")
        self.tal = self.matning.veckans_tal(
            premium_of=lambda row: AccountStore._to_public(row)["premium"],
            premium_source_of=lambda row: AccountStore._to_public(row)["premiumSource"])

    def test_alla_fem_talen_finns_och_heter_nagot(self):
        self.assertEqual(sorted(self.tal), sorted([
            "nyaKonton", "skapadeVeckaInomTvaDygn", "tillbakaEfterSjuDagar",
            "aktivaHushallMedFlerAnEn", "betalandeOchMrr"]))

    def test_varje_andel_bar_sin_namnare(self):
        """En andel utan nämnare är en gissning med decimaler."""
        for nyckel in ("skapadeVeckaInomTvaDygn", "tillbakaEfterSjuDagar"):
            self.assertIn("av", self.tal[nyckel], nyckel)
            self.assertIn("andel", self.tal[nyckel], nyckel)

    def test_nya_konton_raknas_pa_sju_dagar(self):
        self.assertEqual(self.tal["nyaKonton"]["tal"], 1)
        self.assertEqual(self.tal["nyaKonton"]["totaltSedanStart"], 3)

    def test_andelen_som_skapar_en_vecka_inom_tva_dygn(self):
        snabb = self.tal["skapadeVeckaInomTvaDygn"]
        self.assertEqual((snabb["tal"], snabb["av"]), (2, 3))
        self.assertAlmostEqual(snabb["andel"], 2 / 3, places=3)

    def test_andelen_tillbaka_efter_sju_dagar_raknas_bara_pa_mogna_kohorter(self):
        kvar = self.tal["tillbakaEfterSjuDagar"]
        self.assertEqual(kvar["tal"], 1)
        self.assertGreaterEqual(kvar["av"], 1)
        self.assertLessEqual(kvar["tal"], kvar["av"])

    def test_betalande_och_mrr_i_kronor(self):
        betalande = self.tal["betalandeOchMrr"]
        self.assertEqual(betalande["tal"], 1)
        self.assertAlmostEqual(betalande["mrrKronor"], round(399 / 12, 2), places=2)
        self.assertGreater(betalande["mrrExMomsKronor"], 0)
        self.assertEqual(betalande["utanKandPlan"], 0)

    def test_en_andel_utan_underlag_ar_none_inte_noll(self):
        """Noll procent och "vet inte" är olika svar, och bara det ena går
        att fatta beslut på."""
        tom = AnalyticsStore(self.konton.connection, lock=self.konton.lock)
        self.konton.connection.execute("DELETE FROM users")
        self.konton.connection.commit()
        tal = tom.veckans_tal()
        self.assertIsNone(tal["skapadeVeckaInomTvaDygn"]["andel"])


class KohorternaBarKronor(Bas):
    def test_varje_kohort_har_mrr_betalande_och_tappade(self):
        self.betalande(self.konto("a@example.com", 10), "monthly")
        kohort = self.tratt()["kohorter"][0]
        for fält in ("mrrKronor", "premiumBetalande", "tappadePremium",
                     "skapadeVeckaInomTvaDygn", "mognaForSnabbfragan"):
            self.assertIn(fält, kohort, f"kohorten saknar {fält}")
        self.assertAlmostEqual(kohort["mrrKronor"], 59.0, places=2)

    def test_kohorternas_mrr_summerar_till_totalen(self):
        """Två ställen som räknar samma kronor måste komma fram till samma
        summa, annars är ett av dem fel och ingen vet vilket."""
        self.betalande(self.konto("a@example.com", 5), "monthly")
        self.betalande(self.konto("b@example.com", 12), "yearly", sub="sub_2")
        tratt = self.tratt()
        self.assertAlmostEqual(sum(k["mrrKronor"] for k in tratt["kohorter"]),
                               tratt["totalt"]["mrrKronor"], places=2)


class DefinitionernaStarBredvidTalen(Bas):
    def test_varje_nytt_tal_har_en_definition(self):
        """Ett tal utan definition blir tolkat, och två personer tolkar det
        olika."""
        definitioner = self.tratt()["definitioner"]
        for nyckel in ("skapadeVeckaInomTvaDygn", "mognaForSnabbfragan",
                       "aktivaHushallMedFlerAnEn", "mrrKronor", "tappadePremium"):
            self.assertIn(nyckel, definitioner, f"{nyckel} saknar definition")
            self.assertGreater(len(definitioner[nyckel]), 20)

    def test_definitionen_sager_att_tva_dygn_ar_kalenderdagar(self):
        text = self.tratt()["definitioner"]["skapadeVeckaInomTvaDygn"]
        self.assertIn("kalenderdagar", text)
        self.assertIn("48 timmar", text)


if __name__ == "__main__":
    unittest.main()
