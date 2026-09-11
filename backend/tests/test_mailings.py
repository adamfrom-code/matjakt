# -*- coding: utf-8 -*-
"""Utskicken (services/mailings): samtycke, verifiering, en gång, aldrig
tomt, av tills vidare - och avprenumerationslänken."""

import html as html_lib
import tempfile
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.accounts import AccountStore
from services.email import mailer
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
        subjects = [m["subject"] for m in self.sender.sent]
        # Ämnesraden är en av mallens A/B-varianter - vilken avgörs av
        # kontots id, inte av slumpen. Exakt vilken är inte det här testets
        # sak; att det är ETT mejl per steg ur RÄTT mall är det.
        for step in ("welcome_3", "welcome_7"):
            variants = mailings.subject_variants(step)
            self.assertEqual(sum(1 for s in subjects if s in variants), 1, step)
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
        # Ämnesraden bär fyndet, inte kedjeregistret: bästa rabatten över de
        # kedjor personen får är Kycklingfilé (-33 %) hos Willys i båda fallen.
        for mail in (by_to["willys@example.com"], by_to["alla@example.com"]):
            self.assertEqual(mail["subject"], "Veckans bästa fynd: Kycklingfilé för 79,90 kr hos Willys")
        self.assertNotIn("Hemköp", by_to["willys@example.com"]["text"])
        self.assertNotIn("Willys och Hemköp", by_to["alla@example.com"]["subject"])
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

    # ---- elva mallar, tre utskick ----
    def test_the_eight_new_templates_do_not_widen_what_actually_goes_out(self):
        """Att skriva en mall är inte att börja skicka den.

        KINDS växte från tre till elva. Utskicksreglerna gjorde det inte:
        schemaläggaren rör bara SCHEDULED_KINDS, och en mall utan
        mottagarregel vägrar svara på frågan "vem ska ha det här?" i stället
        för att gissa fram en mottagarkrets."""
        self.assertEqual(len(mailings.KINDS), 11)
        self.assertEqual(mailings.SCHEDULED_KINDS, ("welcome_3", "welcome_7", "kampanjtorget"))
        self._user("alla@example.com", days_ago=3, butik="Willys")
        summary = self.scheduler.run_due(self._thursday())
        self.assertEqual(set(summary["skickat"]), set(mailings.SCHEDULED_KINDS))
        for kind in mailings.KINDS:
            if kind in mailings.SCHEDULED_KINDS:
                continue
            with self.assertRaises(ValueError, msg=kind):
                self.store.recipients(kind, self._thursday().date())

    def test_every_template_can_be_rendered_without_sending_anything(self):
        """Ett mejl man inte har tittat på är inte klart - och det gäller
        även de åtta som väntar på data. Exempelvärdena är påhittade."""
        self.scheduler.enabled = False
        for kind in mailings.KINDS:
            subject, text, html = self.scheduler.render(kind, self._thursday())
            self.assertTrue(subject.strip(), kind)
            self.assertTrue(text.strip(), kind)
            self.assertIn("<!doctype html>", html, kind)
            self.assertEqual(self.sender.sent, [], "render skickar aldrig")


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


class MallarnasFormTest(unittest.TestCase):
    """I4: formen på mejlen, prövad mall för mall.

    Acceptanskriteriet för paketet är det här testet, inte en åsikt om att
    mejlen "känns bättre". Fyra saker ska gälla för ALLA elva mallarna, och
    en femte bara för Kampanjtorget:

      1. en dold preheader först - annars skriver inkorgen sin egen
      2. CTA som <table>-knapp, minst 44 px, aldrig en textlänk i brödtexten
      3. samma copy i text- och HTML-utgåvan
      4. avsändare Matjakt <hej@matjakt.store>, Reply-To support@matjakt.store
      5. Kampanjtorgets ämnesrad bär fyndets NAMN och PRIS
    """

    APP = "https://matjakt.store/app"
    UNSUB = "https://api.example/api/mail/unsubscribe?u=1&t=abc"
    # TESTDATA. Aldrig riktiga kunduppgifter - repot är publikt.
    DEALS = {
        "Willys": [{"name": "Kycklingfilé", "brand": "Kronfågel", "size": "900 g",
                    "campaignPrice": 79.9, "regularPrice": 119.0, "discountPercent": 33,
                    "lowestSeen": 79.9},
                   {"name": "Krossade tomater", "brand": "Mutti", "size": "400 g",
                    "campaignPrice": 9.9, "regularPrice": 14.9, "discountPercent": 34,
                    "lowestSeen": None}],
        "Hemköp": [{"name": "GB Glass Daim", "brand": "GB", "size": "4-pack",
                    "campaignPrice": 29.0, "regularPrice": 59.0, "discountPercent": 51,
                    "lowestSeen": 29.0}],
    }
    RECIPES = [
        {"name": "Kycklinggryta med paprika", "ingredients": ["kycklingfilé", "paprika", "ris"]},
        {"name": "Pasta med tomatsås", "ingredients": ["krossade tomater", "pasta", "vitlök"]},
        {"name": "Pannkakor", "ingredients": ["mjöl", "ägg", "mjölk"]},
    ]

    def _render(self, kind, variant=0):
        return mailings.render_preview(kind, self.APP, self.UNSUB, deals=self.DEALS,
                                       week=37, recipes=self.RECIPES, variant=variant)

    # ---- 1. preheadern ----
    def test_every_template_opens_with_a_hidden_preheader(self):
        """Preheadern är den tredje raden inkorgen visar. Utan den plockar
        Gmail den första synliga texten - som här var ordmärket MATJAKT
        följt av rubriken en gång till."""
        for kind in mailings.KINDS:
            _, _, html = self._render(kind)
            head = html.split("<body", 1)[1]
            first = head.split("<div", 1)[1].split("</div>", 1)[0]
            self.assertIn("display:none", first, kind)
            self.assertIn("mso-hide:all", first, kind)
            # Preheadern ligger FÖRE ordmärket, annars läser klienten fel rad.
            self.assertLess(head.index("display:none"), head.index("MATJAKT"), kind)
            # Och det är mallens egen preheadertext som står där.
            stomme = re.sub(r"\{[^}]*\}", "", mailings.TEMPLATES[kind]["preheader"])
            self.assertIn(html_lib.escape(stomme.split("{")[0].strip()[:40]), first, kind)

    # ---- 2. knappen ----
    def _buttons(self, html):
        return re.findall(r'<table role="presentation".*?</table>', html, re.S)

    def test_every_cta_is_a_table_button_of_at_least_44_pixels(self):
        """En <div> med padding är ingen knapp i Outlook - Word-motorn
        ignorerar både padding och border-radius, och kvar blir den
        understrukna textrad vi försökte komma bort ifrån. Höjden mäts där
        den faktiskt uppstår: 13 + 18 + 13 = 44."""
        for kind in mailings.KINDS:
            _, _, html = self._render(kind)
            buttons = self._buttons(html)
            self.assertTrue(buttons, f"{kind} saknar knapp")
            for button in buttons:
                self.assertRegex(button, r'<td[^>]*height="(\d+)"', kind)
                self.assertGreaterEqual(int(re.search(r'<td[^>]*height="(\d+)"', button).group(1)), 44, kind)
                padding = int(re.search(r"padding:(\d+)px", button).group(1))
                line = int(re.search(r"line-height:(\d+)px", button).group(1))
                self.assertGreaterEqual(2 * padding + line, 44, f"{kind}: knappen är för låg")
                self.assertIn("text-decoration:none", button, kind)

    def test_the_body_has_no_naked_cta_link_left_in_it(self):
        """Knappen ersätter textlänken, den kompletterar den inte. Enda
        länkarna utanför knapparna får vara fotens."""
        for kind in mailings.KINDS:
            _, _, html = self._render(kind)
            body = html.split("<hr")[0]
            for button in self._buttons(body):
                body = body.replace(button, "")
            self.assertNotIn("<a ", body, f"{kind} har kvar en textlänk i brödtexten")

    def test_the_button_target_is_repeated_in_the_text_version(self):
        """Den som läser utan HTML ska kunna göra samma sak. Knapptexten och
        adressen står därför i klartext sist i textutgåvan."""
        for kind in mailings.KINDS:
            _, text, _ = self._render(kind)
            label = mailings.TEMPLATES[kind]["button"].split("{")[0].strip()
            self.assertIn(label, text, kind)
            self.assertIn("https://", text, kind)

    # ---- 3. copyn ----
    def test_the_copy_is_the_one_from_bilaga_1(self):
        """Stickprov, en rad ur varje mall. Bilagan är skriven, inte
        utkastad - en omskrivning här är en regression."""
        prov = {
            "verify": "Roligt att du är här.",
            "welcome_3": "Ta två minuter i kväll. Nästa vecka går det på trettio sekunder.",
            "welcome_7": "Har du redan en vecka igång? Då är du längre än de flesta.",
            "kampanjtorget": "Trycker du in ett fynd i veckan byter Matjakt ut en rätt",
            "veckoplan": "Gillar du inte torsdagen byter du den.",
            "manadsrapport": "Siffran är en uppskattning",
            "vinn_tillbaka": "Allt ditt står kvar: budgeten, skafferiet",
            "overgiven_vecka": "sorterad efter hyllorna, inte efter recepten",
            "premium_uppgradering": "Sju middagar i stället för fem.",
            "hushallsinbjudan": "Ingen köper mjölk två gånger.",
            "dunning": "Det är oftast ett kort som gått ut, inget mer.",
        }
        self.assertEqual(set(prov), set(mailings.KINDS))
        for kind, rad in prov.items():
            _, text, html = self._render(kind)
            self.assertIn(rad, text, kind)
            self.assertIn(html_lib.escape(rad), html, kind)

    def test_every_ab_variant_from_bilaga_1_is_reachable_and_stable(self):
        """A/B betyder att varianten är vald, inte slumpad: samma konto får
        samma rad vid ett omtag, annars mäter man sin egen slump."""
        for kind in mailings.KINDS:
            variants = mailings.subject_variants(kind, {
                "vara": "x", "pris": "1 kr", "kedja": "y", "procent": 1, "v": 37, "n": 2,
                "belopp": 1, "månad": "maj", "namn": "A", "antal": 1, "hushåll": "H"})
            self.assertTrue(all(v.strip() for v in variants), kind)
            for user_id in range(1, 60):
                index = mailings.variant_for(kind, user_id)
                self.assertEqual(index, mailings.variant_for(kind, user_id), kind)
                self.assertLess(index, len(variants))
        # Över ett rimligt antal konton används alla armar, inte bara den första.
        arms = {mailings.variant_for("welcome_3", i) for i in range(1, 200)}
        self.assertEqual(arms, {0, 1, 2})

    # ---- 4. avsändaren ----
    def test_the_sender_is_matjakt_and_replies_go_to_support(self):
        """Ett svar på ett utskick ska landa i en läst brevlåda. hej@ skickar,
        support@ tar emot - och From-huvudet har ett namn, inte bara en
        adress, för det är namnet inkorgen visar."""
        _, message = mailer.build_message({"from_email": mailer.SENDER_EMAIL},
                                          "mottagare@example.com", "Ämne", "text")
        self.assertEqual(message["From"], "Matjakt <hej@matjakt.store>")
        self.assertEqual(message["Reply-To"], "support@matjakt.store")
        self.assertNotEqual(message["From"], message["Reply-To"])
        # Ett eget visningsnamn i konfigurationen vinner; en naken adress får
        # Matjakt som namn i stället för att visas som "hej@matjakt.store".
        _, named = mailer.build_message({"from_email": "Matjakt Drift <drift@matjakt.store>"},
                                        "m@example.com", "Ä", "t")
        self.assertEqual(named["From"], "Matjakt Drift <drift@matjakt.store>")
        # Marknadsföring bär List-Unsubscribe; ett kvitto gör det inte.
        _, marknad = mailer.build_message({"from_email": mailer.SENDER_EMAIL}, "m@example.com",
                                          "Ä", "t", "<p>t</p>", self.UNSUB)
        self.assertEqual(marknad["List-Unsubscribe"], f"<{self.UNSUB}>")
        self.assertEqual(marknad["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        self.assertIsNone(message["List-Unsubscribe"])

    def test_transactional_mail_has_no_unsubscribe_link_and_marketing_always_has_one(self):
        """Det går inte att avsäga sig ett kvitto. En avsluta-knapp som inte
        betyder något lär mottagaren att våra knappar inte betyder något."""
        for kind in mailings.KINDS:
            _, text, html = self._render(kind)
            if mailings.TEMPLATES[kind].get("transactional"):
                self.assertNotIn("Avsluta utskicken", html, kind)
                self.assertIn("support@matjakt.store", text, kind)
            else:
                self.assertIn("Avsluta utskicken", html, kind)
                self.assertIn(html_lib.escape(self.UNSUB), html, kind)

    # ---- 5. Kampanjtorgets ämnesrad ----
    def test_the_kampanjtorget_subject_carries_the_best_deals_name_and_price(self):
        """"bästa fynden hos Willys, Hemköp och City Gross" säger VAR något
        finns. "Kycklingfilé för 79,90 kr" säger VAD. Det senare öppnas.

        Regeln gäller varje ämnesrad mallen kan skicka, inte bara den första
        - därför roteras inte Kampanjtorgets A/B-varianter (två av bilagans
        tre bär varken vara eller pris)."""
        subject, _, _ = self._render("kampanjtorget")
        self.assertEqual(subject, "Veckans bästa fynd: GB Glass Daim för 29,00 kr hos Hemköp")
        for user_id in range(1, 80):
            self.assertEqual(mailings.variant_for("kampanjtorget", user_id), 0)
        for index in range(len(mailings.TEMPLATES["kampanjtorget"]["subjects"])):
            if index and mailings.TEMPLATES["kampanjtorget"].get("ab", True):
                skickad, _, _ = self._render("kampanjtorget", variant=index)
                self.assertIn("GB Glass Daim", skickad)
                self.assertIn("29,00 kr", skickad)
        # Och kedjeregistret är borta ur ämnesraden.
        self.assertNotIn("Willys och Hemköp", subject)

    # ---- låt fynden välja menyn ----
    def test_the_deals_pick_the_menu_and_skip_what_no_recipe_can_use(self):
        """Det omvända greppet mättes och höll inte: 19 av 240 recept berörs
        av en normal kampanjvecka, så "så många av veckans fynd finns i DIN
        plan" blir noll sju gånger av tio. Den här riktningen utgår från
        fynden i stället, och glassen - som vinner rabattävlingen varje vecka
        - faller bort av sig själv eftersom inget recept använder den."""
        menu = mailings.deals_menu(self.DEALS, self.RECIPES)
        self.assertEqual([post["recipe"] for post in menu],
                         ["Pasta med tomatsås", "Kycklinggryta med paprika"])
        self.assertNotIn("GB Glass Daim", [post["deal"]["name"] for post in menu])
        # Ett recept hamnar på menyn en gång, oavsett hur många fynd det matchar.
        self.assertEqual(len({post["recipe"] for post in menu}), len(menu))
        _, text, html = self._render("kampanjtorget")
        self.assertIn("TVÅ MIDDAGAR BYGGDA PÅ VECKANS REOR", text)   # versal som hero-etiketten
        self.assertIn("Två middagar byggda på veckans reor", html)
        self.assertIn("Pasta med tomatsås", text)
        # Utan receptbank ser mejlet ut som förut - menyn är en bonus, inte
        # ett krav, och ett fynd utan rätt tystar inte hela utskicket.
        utan = mailings.render_kampanjtorget(self.DEALS, list(self.DEALS), self.APP,
                                             self.UNSUB, 37)[2]
        self.assertNotIn("byggda på veckans reor", utan)
        self.assertEqual(mailings.deals_menu({}, self.RECIPES), [])
        self.assertEqual(mailings.deals_menu(self.DEALS, []), [])
