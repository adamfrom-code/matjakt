# -*- coding: utf-8 -*-
"""Utskicken (services/mailings): samtycke, verifiering, en gång, aldrig
tomt, av tills vidare - och avprenumerationslänken."""

import tempfile
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.accounts import AccountStore
from services import mailings

RELEASED = ("Willys", "Hemköp", "City Gross")
# Fast klocka: kontona skapas relativt måndagen 2026-09-07 och körningarna
# görs på fasta datum, så testet betyder samma sak oavsett när det körs.
BASE = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
DEALS = {
    "Willys": [{"name": "Kycklingfilé", "brand": "Kronfågel", "size": "900 g", "campaignPrice": 79.9,
                "regularPrice": 119.0, "discountPercent": 33, "lowestSeen": 79.9}],
    "Hemköp": [{"name": "Vispgrädde", "brand": "Arla", "size": "5 dl", "campaignPrice": 19.9,
                "regularPrice": 27.9, "discountPercent": 29, "lowestSeen": 17.5}],
    "City Gross": [],
}


class FakeSender:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def __call__(self, to, subject, text, body_html, unsub):
        if to in self.fail_for:
            raise RuntimeError("SMTP nere")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": body_html, "unsub": unsub})


class MailingsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.accounts = AccountStore(Path(self._tmpdir.name) / "test.db")
        self.store = mailings.MailingStore(self.accounts.connection)
        self.sender = FakeSender()
        self.deals_calls = 0

        def deals():
            self.deals_calls += 1
            return DEALS
        self.scheduler = mailings.MailingScheduler(
            self.store, self.sender, deals, api_base="https://api.example/api",
            app_url="https://app.example", secret="hemlig", enabled=True,
            mail_configured=lambda: True, released_chains=RELEASED, pause_seconds=0)

    def tearDown(self):
        self.accounts.close()
        self._tmpdir.cleanup()

    def _user(self, email, *, days_ago=0, consent=True, verified=True, butik=None):
        self.accounts.register(email, "hemligt123", marketing=consent)
        conn = self.accounts.connection
        user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
        created = (BASE - timedelta(days=days_ago)).isoformat()
        conn.execute("UPDATE users SET created_at = ?, email_verified = ? WHERE id = ?",
                     (created, 1 if verified else 0, user_id))
        if butik:
            conn.execute("UPDATE users SET synced_state = ? WHERE id = ?", ('{"butik": "%s"}' % butik, user_id))
        conn.commit()
        return user_id

    def _thursday(self):
        now = datetime(2026, 9, 10, 8, 0)  # en torsdag
        self.assertEqual(now.weekday(), mailings.KAMPANJTORGET_WEEKDAY)
        return now

    # ---- spärrarna ----
    def test_nothing_goes_out_when_disabled_unconfigured_or_without_secret(self):
        self._user("a@example.com", days_ago=3)
        for attr, value, reason in (("enabled", False, "MATJAKT_MAILINGS_ENABLED"),
                                    ("mail_configured", lambda: False, "SMTP"),
                                    ("secret", "", "hemlighet")):
            original = getattr(self.scheduler, attr)
            setattr(self.scheduler, attr, value)
            summary = self.scheduler.run_due(self._thursday())
            setattr(self.scheduler, attr, original)
            self.assertIn(reason, summary["blockerat"])
            self.assertEqual(self.sender.sent, [])

    def test_only_consenting_and_verified_accounts_get_marketing(self):
        self._user("ja@example.com", days_ago=3)
        self._user("nej@example.com", days_ago=3, consent=False)
        self._user("overifierad@example.com", days_ago=3, verified=False)
        summary = self.scheduler.run_due(datetime(2026, 9, 7, 8, 0))  # måndag
        self.assertEqual(summary["skickat"], {"welcome_3": 1, "welcome_7": 0})
        self.assertEqual([m["to"] for m in self.sender.sent], ["ja@example.com"])

    # ---- välkomstserien ----
    def test_welcome_steps_are_sent_once_and_only_inside_their_window(self):
        self._user("tre@example.com", days_ago=4)
        self._user("sju@example.com", days_ago=9)
        self._user("gammal@example.com", days_ago=40)   # missade fönstret - får inget i efterhand
        self._user("ny@example.com", days_ago=1)
        monday = datetime(2026, 9, 7, 8, 0)
        first = self.scheduler.run_due(monday)
        # tre: dag 3-fönstret. sju: bara dag 7 (dag 3-fönstret är passerat -
        # ingen får "tre dagar"-mejlet nio dagar in). gammal och ny: inget.
        self.assertEqual(first["skickat"], {"welcome_3": 1, "welcome_7": 1})
        subjects = sorted(m["subject"] for m in self.sender.sent)
        self.assertEqual(subjects.count("Tre dagar med Matjakt: tre saker som sparar mest"), 1)
        self.assertEqual(subjects.count("En vecka med Matjakt"), 1)
        # Samma dag igen, och nästa dag: inget dubbleras.
        again = self.scheduler.run_due(monday)
        self.assertEqual(again["skickat"], {"welcome_3": 0, "welcome_7": 0})
        tomorrow = self.scheduler.run_due(monday + timedelta(days=1))
        self.assertEqual(tomorrow["skickat"], {"welcome_3": 0, "welcome_7": 0})

    def test_every_marketing_mail_carries_a_working_unsubscribe_link(self):
        user_id = self._user("u@example.com", days_ago=3)
        self.scheduler.run_due(datetime(2026, 9, 7, 8, 0))
        mail = self.sender.sent[0]
        import html as html_lib
        self.assertIn(mail["unsub"], mail["text"])
        self.assertIn(html_lib.escape(mail["unsub"]), mail["html"])
        self.assertTrue(mail["unsub"].startswith("https://api.example/api/mail/unsubscribe?u=%d&t=" % user_id))
        token = mail["unsub"].split("&t=")[1]
        self.assertTrue(mailings.unsubscribe_valid(user_id, token, "hemlig"))
        self.assertFalse(mailings.unsubscribe_valid(user_id, token, "annan-hemlighet"))
        self.assertFalse(mailings.unsubscribe_valid(user_id + 1, token, "hemlig"))
        self.assertFalse(mailings.unsubscribe_valid("abc", token, "hemlig"))
        # Avprenumererad -> inga fler steg.
        self.assertTrue(self.accounts.set_marketing_consent(user_id, False))
        self.sender.sent.clear()
        self.scheduler.run_due(datetime(2026, 9, 14, 8, 0))
        self.assertEqual(self.sender.sent, [])

    # ---- Kampanjtorget ----
    def test_kampanjtorget_goes_out_on_thursdays_with_the_users_chain(self):
        self._user("willys@example.com", days_ago=30, butik="Willys")
        self._user("alla@example.com", days_ago=30, butik="auto")
        self._user("coop@example.com", days_ago=30, butik="Coop")   # ingen Coop-data -> alla släppta
        summary = self.scheduler.run_due(self._thursday())
        self.assertEqual(summary["skickat"]["kampanjtorget"], 3)
        self.assertEqual(self.deals_calls, 1, "fynden hämtas en gång per körning, inte per mottagare")
        by_to = {m["to"]: m for m in self.sender.sent}
        self.assertIn("bästa fynden hos Willys", by_to["willys@example.com"]["subject"])
        self.assertNotIn("Hemköp", by_to["willys@example.com"]["text"])
        self.assertIn("Willys och Hemköp", by_to["alla@example.com"]["subject"])
        self.assertIn("Vispgrädde 5 dl, Arla: 19,90 kr (ord. 27,90 kr, -29 %)", by_to["alla@example.com"]["text"])
        self.assertIn("Lägsta vi sett", by_to["willys@example.com"]["text"])
        self.assertNotIn("Lägsta vi sett", by_to["alla@example.com"]["html"].split("Vispgr")[1][:200])
        self.assertIn("Kampanjtorget vecka 37", by_to["alla@example.com"]["html"])
        # Inte på en onsdag, och inte två gånger samma torsdag.
        self.sender.sent.clear()
        self.assertNotIn("kampanjtorget", self.scheduler.run_due(datetime(2026, 9, 9, 8, 0))["skickat"])
        self.assertEqual(self.scheduler.run_due(self._thursday())["skickat"]["kampanjtorget"], 0)

    def test_an_empty_torg_is_never_sent(self):
        self._user("cg@example.com", days_ago=30, butik="City Gross")   # kedjan finns men har inga fynd
        summary = self.scheduler.run_due(self._thursday())
        self.assertEqual(summary["skickat"]["kampanjtorget"], 0)
        self.assertEqual(self.sender.sent, [])
        self.assertIsNone(mailings.render_kampanjtorget({}, list(RELEASED), "u", "x", 37))

    def test_a_failed_send_is_not_logged_and_does_not_stop_the_others(self):
        self._user("nere@example.com", days_ago=3)
        self._user("ok@example.com", days_ago=3)
        self.sender.fail_for.add("nere@example.com")
        summary = self.scheduler.run_due(datetime(2026, 9, 7, 8, 0))
        self.assertEqual(summary["skickat"]["welcome_3"], 1)
        self.assertEqual(summary["fel"]["welcome_3"], 1)
        self.assertEqual(self.store.counts()["welcome_3"], 1)
        # Nästa körning försöker igen med den som misslyckades.
        self.sender.fail_for.clear()
        self.assertEqual(self.scheduler.run_due(datetime(2026, 9, 8, 8, 0))["skickat"]["welcome_3"], 1)

    def test_tick_fires_once_per_day_at_send_time(self):
        self._user("t@example.com", days_ago=3)
        self.scheduler._tick(datetime(2026, 9, 7, 7, 59))
        self.assertEqual(self.sender.sent, [])
        self.scheduler._tick(datetime(2026, 9, 7, 8, 0))
        self.scheduler._tick(datetime(2026, 9, 7, 8, 0))
        self.assertEqual(len(self.sender.sent), 1)

    def test_preview_needs_only_smtp_and_never_logs(self):
        self.scheduler.enabled = False
        result = self.scheduler.preview("kampanjtorget", "adam@example.com", self._thursday())
        self.assertTrue(result["ok"])
        self.assertEqual(self.sender.sent[0]["to"], "adam@example.com")
        self.assertEqual(self.store.counts()["kampanjtorget"], 0)
        with self.assertRaises(ValueError):
            self.scheduler.preview("nagot_annat", "adam@example.com")
        self.scheduler.mail_configured = lambda: False
        with self.assertRaises(RuntimeError):
            self.scheduler.preview("welcome_3", "adam@example.com")

    def test_status_is_honest_about_why_nothing_goes_out(self):
        self._user("s@example.com", days_ago=1)
        self._user("o@example.com", days_ago=1, verified=False)
        status = self.scheduler.status()
        self.assertIsNone(status["blockerat"])
        self.assertEqual(status["mottagare"], {"tackatJa": 2, "tackatJaOchVerifierade": 1})
        self.scheduler.enabled = False
        self.assertIn("MATJAKT_MAILINGS_ENABLED", self.scheduler.status()["blockerat"])


if __name__ == "__main__":
    unittest.main()


class KampanjtorgetBilderTest(unittest.TestCase):
    """Bilder i Kampanjtorget.

    Gmail och Outlook blockerar bilder som standard. Varje test här handlar
    därför om samma sak från olika håll: mejlet ska bära sitt budskap i text
    och bli finare av bilderna, aldrig beroende av dem.
    """

    def _deal(self, name, campaign, regular, percent, chain="Willys", image=None, size=None):
        return {"name": name, "campaignPrice": campaign, "regularPrice": regular,
                "discountPercent": percent, "chain": chain, "imageUrl": image,
                "size": size, "brand": None, "lowestSeen": None}

    def _render(self, deals_by_chain, chains=("Willys", "Hemköp")):
        return mailings.render_kampanjtorget(deals_by_chain, list(chains),
                                             "https://matjakt.store/app", "https://x/u", 37)

    def test_the_biggest_discount_across_chains_becomes_the_hero(self):
        """Bästa fyndet lyfts ut oavsett vilken kedja det ligger i - annars
        avgörs "veckans bästa" av kedjornas ordning i listan."""
        _, text, html = self._render({
            "Willys": [self._deal("Kaffe", 39.0, 59.0, 34)],
            "Hemköp": [self._deal("Ost", 45.0, 90.0, 50, chain="Hemköp")],
        })
        self.assertIn("VECKANS BÄSTA FYND", html)
        hero = html.split("VECKANS BÄSTA FYND")[1][:600]
        self.assertIn("Ost", hero)
        self.assertIn("Hemköp", hero)
        # Även textversionen ska ha det bästa fyndet - den som läser utan
        # HTML får annars ett sämre mejl.
        self.assertIn("VECKANS BÄSTA FYND", text)
        self.assertIn("Ost", text)

    def test_the_hero_still_reads_when_the_image_is_blocked(self):
        """Namn, pris och rabatt står som TEXT bredvid bilden. Blockeras den
        tappar mejlet ett foto, inte sitt innehåll."""
        _, _, html = self._render({"Willys": [
            self._deal("Kaffe", 39.0, 59.0, 34, image="https://bild.example/k.jpg")]})
        utan_bilder = re.sub(r"<img[^>]*>", "", html)
        self.assertIn("Kaffe", utan_bilder)
        self.assertIn("39,00 kr", utan_bilder)
        self.assertIn("34 %", utan_bilder)

    def test_a_deal_without_an_image_still_renders(self):
        _, _, html = self._render({"Willys": [self._deal("Mjölk", 12.0, 18.0, 33)]})
        self.assertIn("Mjölk", html)
        self.assertIn("12,00 kr", html)

    def test_only_https_images_are_allowed(self):
        """En url ur providerdata är inte vår att lita på. Allt utom https
        släpps inte in - raden renderas hellre utan bild än med en attackyta."""
        for ful in ("javascript:alert(1)", "data:text/html;base64,x",
                    "http://osaker.example/x.jpg", "//protokollos.example/x.jpg"):
            _, _, html = self._render({"Willys": [
                self._deal("Vara", 10.0, 20.0, 50, image=ful)]})
            self.assertNotIn(ful, html, ful)
        _, _, html = self._render({"Willys": [
            self._deal("Vara", 10.0, 20.0, 50, image="https://bild.example/v.jpg")]})
        self.assertIn("https://bild.example/v.jpg", html)

    def test_images_are_decorative_because_the_name_is_already_next_to_them(self):
        """Varunamnet står som rubrik direkt under hero-bilden. En alt-text
        med samma namn skulle läsas upp två gånger av en skärmläsare och
        synas dubbelt när bilden blockeras - upptäckt genom att faktiskt
        titta på mejlet med bilden bruten."""
        _, _, html = self._render({"Willys": [
            self._deal("Kaffe Mellanrost", 39.0, 59.0, 34,
                       image="https://bild.example/k.jpg", size="450 g")]})
        self.assertIn('alt=""', html)
        self.assertNotIn('alt="Kaffe Mellanrost 450 g"', html)
        # Namnet finns kvar som text - det är det som bär budskapet.
        self.assertIn("Kaffe Mellanrost 450 g", re.sub(r"<img[^>]*>", "", html))
