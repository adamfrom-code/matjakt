# -*- coding: utf-8 -*-
"""Kontrakt mellan frontend och backend som inte får glida isär.

Frontenden kan inte fråga backend om allt vid varje rendering; några
sanningar finns därför speglade i app.js. De här testen låser att speglingen
är exakt - annars skulle appen kunna bjuda på en kedja utan priser, eller
låsa upp en funktion som backend inte ger."""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.accounts import features  # noqa: E402
from services.grocery import api as grocery_api  # noqa: E402

APP_JS = Path(__file__).resolve().parents[2] / "frontend" / "app" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[2] / "frontend" / "app" / "index.html"


class FrontendMirrorsBackend(unittest.TestCase):
    def setUp(self):
        self.app = APP_JS.read_text(encoding="utf-8")

    def test_released_chains_are_identical(self):
        match = re.search(r"const RELEASED_CHAINS = (\[[^\]]*\]);", self.app)
        self.assertIsNotNone(match, "RELEASED_CHAINS saknas i app.js")
        self.assertEqual(set(json.loads(match.group(1))), set(grocery_api.RELEASED_CHAINS))

    def test_no_gated_chain_is_selectable_in_html(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        for chain in ("ICA", "Coop", "Lidl"):
            self.assertNotIn(f'<option value="{chain}"', html, f"{chain} är gated men valbar i index.html")

    def test_free_feature_matrix_is_identical(self):
        match = re.search(r"const FREE_FEATURES = \{(.*?)\};", self.app, re.S)
        self.assertIsNotNone(match)
        pairs = dict(re.findall(r"(\w+):\s*(true|false)", match.group(1)))
        expected = {key: str(bool(spec["free"])).lower() for key, spec in features.FEATURES.items()}
        self.assertEqual(pairs, expected)

    def test_no_emoji_icons_in_ui_strings(self):
        """Designregeln: inga emoji som ikoner. Texten säger vad den menar."""
        html = INDEX_HTML.read_text(encoding="utf-8")
        for char in "⏱🔒🏷🍕🥦✨🎉👍👎🍽👋":
            self.assertNotIn(char, self.app, f"emoji-ikon {char!r} i app.js")
            self.assertNotIn(char, html, f"emoji-ikon {char!r} i index.html")


class NoInlineScripts(unittest.TestCase):
    """Låsskriptet är borta: app/index.html har inga inline-skript alls, så
    CSP-headern behöver ingen hash och script-src är enbart 'self' (plus
    statistikvärdarna som laddas som externa skript)."""

    def test_app_shell_has_no_inline_script_and_csp_needs_no_hash(self):
        import re
        import api_server
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"<script>(.*?)</script>", html, re.S), [])
        self.assertNotIn("sha256-", api_server.ApiHandler.CONTENT_SECURITY_POLICY)
        self.assertNotIn("'unsafe-inline'", api_server.ApiHandler.CONTENT_SECURITY_POLICY.split("style-src")[0])
        meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        self.assertNotIn("frame-ancestors", meta)
        self.assertIn("frame-ancestors 'none'", api_server.ApiHandler.CONTENT_SECURITY_POLICY)


if __name__ == "__main__":
    unittest.main()
