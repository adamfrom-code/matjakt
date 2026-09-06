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


class InlineGateScriptHash(unittest.TestCase):
    """index.html:s inline-låsskript måste vara tillåtet av serverns CSP-
    header via sin sha256-hash - ändras skriptet måste hashen följa med,
    annars blockeras omdirigeringen tyst."""

    def test_csp_header_carries_the_current_inline_script_hash(self):
        import base64
        import hashlib
        import re
        import api_server
        html = INDEX_HTML.read_text(encoding="utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertEqual(len(scripts), 1, "exakt ett inline-skript (låset) är tillåtet")
        digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
        self.assertIn(f"'sha256-{digest}'", api_server.ApiHandler.CONTENT_SECURITY_POLICY)
        # frame-ancestors verkar bara som header - i meta-taggen ger den
        # bara ett konsolfel.
        meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        self.assertNotIn("frame-ancestors", meta)
        self.assertIn("frame-ancestors 'none'", api_server.ApiHandler.CONTENT_SECURITY_POLICY)


if __name__ == "__main__":
    unittest.main()
