# -*- coding: utf-8 -*-
"""Browser-E2E: hushållet med TVÅ personer i två separata browser contexts.

Adam i ett context, Sara i ett annat - egna cookies, eget localStorage, egen
session. Det är den enda uppställning som faktiskt bevisar delningen: i en
och samma flik delas localStorage, och "två användare" blir en illusion.

    Adam skapar hushåll -> bjuder in -> Sara går med -> gemensam vecka ->
    Sara ändrar Handla -> Adam ser ändringen -> Har hemma -> Köpt ->
    Ångra -> Skafferi -> samtidiga ändringar -> Sara lämnar -> access borta

Servern, databaserna och prisdatan kommer från samma fixtur som
konsumentresan (_Server), så det här körs mot riktiga priser och riktiga
sessioner utan ett enda externt anrop.

SYNKEN ÄR SYNLIGHETSSTYRD. Appen hämtar var 20:e sekund när fliken är
synlig, plus direkt efter varje egen ändring och vid återkomst från
bakgrunden. Playwright-flikar rapporterar "visible", men att vänta ut 20
sekunder per steg skulle göra sviten outhärdlig - därför triggas
hämtningen med en visibilitychange, precis som när telefonen plockas upp.
"""

import contextlib
import os
import re
import unittest

from services.data_guard import test_mode_active

from .test_consumer_journey import HAVE_PLAYWRIGHT, MOBILE, _Server, _skip_reason

if test_mode_active():
    import api_server
    from services.accounts import ratelimit

if HAVE_PLAYWRIGHT:
    from playwright.sync_api import expect, sync_playwright


ARTIFACTS = os.environ.get("MATJAKT_E2E_ARTIFACTS")


class HouseholdJourney(unittest.TestCase):
    """Två riktiga webbläsarsessioner mot en riktig server."""

    server = None

    @classmethod
    def setUpClass(cls):
        reason = _skip_reason()
        if reason:
            raise unittest.SkipTest(reason)
        cls.server = _Server()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception as error:      # pragma: no cover - Chromium saknas
            cls.playwright.stop()
            cls.server.close()
            raise unittest.SkipTest(f"Chromium kunde inte startas: {str(error)[:120]}")

    @classmethod
    def tearDownClass(cls):
        if cls.server is None:
            return
        with contextlib.suppress(Exception):
            cls.browser.close()
        with contextlib.suppress(Exception):
            cls.playwright.stop()
        cls.server.close()

    def setUp(self):
        ratelimit.reset()
        self.addCleanup(ratelimit.reset)
        self.contexts = []

    def tearDown(self):
        for context in self.contexts:
            with contextlib.suppress(Exception):
                context.close()

    # ---- hjälpare --------------------------------------------------------

    def _person(self, name):
        """En egen browser context = en egen person. Separat localStorage är
        hela poängen; två flikar i samma context vore samma användare."""
        context = self.browser.new_context(viewport=MOBILE, locale="sv-SE",
                                           service_workers="block")
        self.contexts.append(context)
        page = context.new_page()
        page.goto(f"{self.server.base}/app/", wait_until="domcontentloaded")
        page.wait_for_function("() => window.localStorage !== undefined")
        # Onboardingen är inte det som testas här.
        page.evaluate("() => { const m = document.getElementById('onboardingModal'); if (m) m.hidden = true; }")
        email = f"{name}-{os.urandom(4).hex()}@example.com"
        page.evaluate(
            """async ({email}) => {
                const res = await fetch('/api/auth/register', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({email, password: 'hemligt123'})});
                const data = await res.json();
                localStorage.setItem('matjakt-auth-token', data.token);
            }""", {"email": email})
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("() => document.getElementById('profileBtn') !== null")
        page.evaluate("() => { const m = document.getElementById('onboardingModal'); if (m) m.hidden = true; }")
        return page, email

    def _open_household(self, page):
        """Hushållspanelen i kontoarket.

        G11: profilknappen leder till INSTÄLLNINGAR, inte rakt in i kontoarket
        - och hushållet har en egen rad där ("Delas med"), som öppnar arket på
        rätt ställe. Det är två tryck i stället för ett, men det första tar en
        till en skärm som SÄGER vad den innehåller.
        """
        page.click("#profileBtn")
        page.click('[data-settings="hushall"]')
        expect(page.locator("#accountModal")).to_be_visible()

    def _sync(self, page):
        """Väck synken som när telefonen plockas upp, och vänta in svaret."""
        page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(900)

    def _shopping_rows(self, page):
        return page.evaluate(
            """() => [...document.querySelectorAll('#shoppingList .shopping-item')]
                 .map(el => el.querySelector('strong')?.textContent || '')""")

    def _api(self, page, path, body=None):
        return page.evaluate(
            """async ({path, body}) => {
                const token = localStorage.getItem('matjakt-auth-token');
                const res = await fetch(path, {
                    method: body ? 'POST' : 'GET',
                    headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + token},
                    body: body ? JSON.stringify(body) : undefined});
                return {status: res.status, body: await res.json().catch(() => null)};
            }""", {"path": path, "body": body})

    def _screenshot(self, page, name):
        if not ARTIFACTS:
            return
        with contextlib.suppress(Exception):
            page.screenshot(path=os.path.join(ARTIFACTS, f"household-{name}.png"), full_page=True)

    # ---- resan -----------------------------------------------------------

    def test_two_people_share_one_household(self):
        adam, adam_email = self._person("adam")
        sara, sara_email = self._person("sara")

        # --- Adam skapar hushåll ------------------------------------------
        self._open_household(adam)
        adam.fill("#householdNameInput", "Familjen From")
        adam.click("#householdCreateForm button[type=submit]")
        expect(adam.locator("#householdNameLabel")).to_have_text("Familjen From", timeout=8000)
        # Egen rad ska INTE ha "Ta bort" - man kastar inte ut sig själv.
        self.assertEqual(adam.locator("#householdMembers [data-remove-member]").count(), 0)

        # --- ...bjuder in --------------------------------------------------
        adam.click("#householdInviteBtn")
        expect(adam.locator("#householdInviteBox")).to_be_visible(timeout=8000)
        invite_url = adam.input_value("#householdInviteLink")
        token = re.search(r"invite=([A-Za-z0-9_-]+)", invite_url).group(1)
        self._screenshot(adam, "invite")

        # --- Sara går med via länken ---------------------------------------
        sara.goto(f"{self.server.base}/app/?invite={token}", wait_until="domcontentloaded")
        sara.evaluate("() => { const m = document.getElementById('onboardingModal'); if (m) m.hidden = true; }")
        expect(sara.locator("#inviteLandingTitle")).to_contain_text("Familjen From", timeout=8000)
        self._screenshot(sara, "landing")
        sara.click("#inviteJoinBtn")
        sara.wait_for_timeout(1500)
        self._open_household(sara)
        expect(sara.locator("#householdNameLabel")).to_have_text("Familjen From", timeout=8000)
        # Sara är medlem, inte admin: ingen inbjudningsknapp.
        expect(sara.locator("#householdInviteBtn")).to_be_hidden()
        sara.click(".account-modal-close")
        adam.click(".account-modal-close")

        # --- gemensam vecka -------------------------------------------------
        self._api(adam, "/api/household/doc",
                  {"doc": "week", "body": {"weekPlan": ["tacos", "kottfarssas"]}})
        self._sync(sara)
        week = self._api(sara, "/api/household/sync")
        self.assertEqual(week["body"]["docs"]["week"]["body"]["weekPlan"],
                         ["tacos", "kottfarssas"], "Sara ser inte Adams vecka")

        # --- gemensam Handla -------------------------------------------------
        self._api(adam, "/api/household/shopping/week", {"items": [
            {"name": "Mjölk", "amount": 1, "unit": "l", "category": "Mejeri"},
            {"name": "Kaffe", "amount": 500, "unit": "g", "category": "Skafferi"},
            {"name": "Ketchup", "amount": 1, "unit": "st", "category": "Skafferi"},
        ]})
        for page in (adam, sara):
            page.click("[data-view='basket']")
            self._sync(page)
        expect(adam.locator("#basketHouseholdNote")).to_contain_text("Familjen From")
        self.assertEqual(len(self._shopping_rows(sara)), 3, "Sara ser inte den delade listan")

        # --- Sara ändrar, Adam ser ------------------------------------------
        rows = self._api(sara, "/api/household/sync?since=0")["body"]["shopping"]
        milk = next(r for r in rows if r["name"] == "Mjölk")
        sara_bought = self._api(sara, "/api/household/shopping/purchased",
                                {"key": milk["key"], "addToInventory": True, "location": "kyl"})
        self.assertEqual(sara_bought["body"]["item"]["status"], "PURCHASED")
        self._sync(adam)
        # L3: en avbockad vara lyfts inte längre UR listan till ett eget
        # "Klart"-block under den. Den ligger kvar i sin avdelning,
        # genomstruken och tonad - i butik ska raden man just bockade av
        # stanna vid hyllan man står vid, inte hoppa till skärmens fot.
        # Saras köp syns alltså hos Adam PÅ RADEN, och testet mäter det i
        # stället för att mäta var raden råkade flytta.
        self.assertIn("Mjölk", self._shopping_rows(adam), "Adam ser inte Saras köp")
        milk = adam.locator("#shoppingList .shopping-item", has_text="Mjölk").first
        expect(milk).to_have_class(re.compile(r"vara--klar"))
        expect(milk.locator("button.vara")).to_have_attribute("aria-pressed", "true")
        self.assertEqual(adam.locator(".shopping-handled-row").count(), 0,
                         "det gamla Klart-blocket ritas fortfarande")
        self._screenshot(adam, "kopt")

        # --- Har hemma i Adams UI --------------------------------------------
        adam.click("#shoppingList [data-at-home]")
        adam.wait_for_timeout(1500)
        at_home = [r for r in self._api(adam, "/api/household/sync?since=0")["body"]["shopping"]
                   if r["status"] == "ALREADY_HAVE"]
        self.assertEqual(len(at_home), 1, "Har hemma ändrade ingen rad")
        expect(adam.locator("#undoToast")).to_be_visible()

        # --- Ångra ------------------------------------------------------------
        adam.click("#undoToast button")
        adam.wait_for_timeout(1500)
        after_undo = self._api(adam, "/api/household/sync?since=0")["body"]
        self.assertEqual([r for r in after_undo["shopping"] if r["status"] == "ALREADY_HAVE"], [],
                         "Ångra tog inte tillbaka statusen")
        pantry_names = {r["name"] for r in after_undo["inventory"] if not r["deleted"]}
        self.assertEqual(pantry_names, {"Mjölk"},
                         "Ångra ska bara ta bort raden HANDLINGEN skapade - Saras köp ligger kvar")

        # --- × och Ångra i hushållsläge ------------------------------------
        # REMOVED är serverns status; ångra-remsan måste gå samma väg tillbaka,
        # annars låg raden osynlig kvar utan väg hem (granskningen 2026-09-07).
        remove_button = adam.locator("#shoppingList [data-remove-item]").first
        removed_name = remove_button.get_attribute("data-remove-item")
        remove_button.click()
        adam.wait_for_timeout(1500)
        statuses = {r["name"]: r["status"] for r in self._api(adam, "/api/household/sync?since=0")["body"]["shopping"]}
        self.assertEqual(statuses.get(removed_name), "REMOVED", f"× nådde inte servern för {removed_name}")
        expect(adam.locator("#undoToast")).to_be_visible()
        adam.click("#undoToast button")
        adam.wait_for_timeout(1500)
        statuses = {r["name"]: r["status"] for r in self._api(adam, "/api/household/sync?since=0")["body"]["shopping"]}
        self.assertEqual(statuses.get(removed_name), "NEED_TO_BUY", "Ångra efter × gav inte tillbaka raden i hushållet")
        expect(adam.locator(f'#shoppingList [data-remove-item="{removed_name}"]')).to_be_visible()

        # --- Skafferiet delas -------------------------------------------------
        for page in (adam, sara):
            page.click("[data-view='pantry']")
            self._sync(page)
            page.click("[data-pantry-tab='kyl']")
            page.wait_for_timeout(400)
        for who, page in (("Adam", adam), ("Sara", sara)):
            names = page.evaluate(
                """() => [...document.querySelectorAll('#pantryList .pantry-item strong')]
                     .map(el => el.textContent)""")
            self.assertIn("Mjölk", names, f"{who} ser inte mjölken i kylen")
        expect(adam.locator("#pantryHouseholdNote")).to_contain_text("Familjen From")
        self._screenshot(sara, "skafferi")

        # --- samtidiga ändringar ----------------------------------------------
        rows = self._api(adam, "/api/household/sync?since=0")["body"]["shopping"]
        coffee = next(r for r in rows if r["name"] == "Kaffe")
        ketchup = next(r for r in rows if r["name"] == "Ketchup")
        self._api(adam, "/api/household/shopping/purchased", {"key": coffee["key"]})
        self._api(sara, "/api/household/shopping/at-home", {"key": ketchup["key"]})
        statuses = {r["name"]: r["status"]
                    for r in self._api(adam, "/api/household/sync?since=0")["body"]["shopping"]}
        self.assertEqual(statuses["Kaffe"], "PURCHASED", "Adams ändring försvann")
        self.assertEqual(statuses["Ketchup"], "ALREADY_HAVE", "Saras ändring försvann")

        # --- Sara lämnar, access försvinner -------------------------------------
        self._open_household(sara)
        sara.evaluate("() => { window.confirm = () => true; }")
        sara.click("#householdLeaveBtn")
        sara.wait_for_timeout(1500)
        self.assertEqual(self._api(sara, "/api/household/sync")["status"], 404,
                         "Sara har kvar åtkomst efter att ha lämnat")
        self.assertEqual(
            self._api(sara, "/api/household/shopping/status",
                      {"key": coffee["key"], "status": "NEED_TO_BUY"})["status"], 404,
            "Sara kan fortfarande skriva i hushållet")
        # ...och Adams hushåll är orört.
        adams = self._api(adam, "/api/household/sync?since=0")["body"]
        self.assertEqual(len(adams["members"]), 1)
        self.assertEqual({r["name"]: r["status"] for r in adams["shopping"]}["Kaffe"], "PURCHASED")
        self._screenshot(adam, "efter-utträde")

    def test_an_outsider_never_sees_the_household(self):
        """Tredje personen, egen session, inget hushåll: 404 hela vägen -
        även med ett giltigt rad-id ur familjens lista."""
        adam, _ = self._person("adam")
        outsider, _ = self._person("frammande")

        self._open_household(adam)
        adam.fill("#householdNameInput", "Familjen From")
        adam.click("#householdCreateForm button[type=submit]")
        expect(adam.locator("#householdNameLabel")).to_have_text("Familjen From", timeout=8000)
        self._api(adam, "/api/household/shopping/item", {"name": "Mjölk", "source": "manual"})
        row = self._api(adam, "/api/household/sync?since=0")["body"]["shopping"][0]

        self.assertEqual(self._api(outsider, "/api/household/sync")["status"], 404)
        self.assertIsNone(self._api(outsider, "/api/household")["body"]["household"])
        for path, body in (
            ("/api/household/shopping/status", {"key": row["key"], "status": "PURCHASED"}),
            ("/api/household/shopping/at-home", {"id": row["id"]}),
            ("/api/household/doc", {"doc": "week", "body": {"weekPlan": ["kapad"]}}),
        ):
            self.assertIn(self._api(outsider, path, body)["status"], (400, 404), path)
        still = self._api(adam, "/api/household/sync?since=0")["body"]
        self.assertEqual(still["shopping"][0]["status"], "NEED_TO_BUY")
        self.assertEqual(still["docs"], {})


if __name__ == "__main__":
    unittest.main()
