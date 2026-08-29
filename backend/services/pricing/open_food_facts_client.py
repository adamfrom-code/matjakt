"""Minimal Open Food Facts client - stdlib only, matching this project's
existing pattern (see services/billing/stripe_client.py). Used for exactly
one thing: filling in a product photo when Primat has none (Primat never
returns images at all - see primat_client.to_matjakt_product).

No API key, no account, no cost - verified directly against the real API
before building this. Commercial use is explicitly permitted in Open Food
Facts' terms (ODbL for data, CC BY-SA for images), with one required
condition: visible attribution wherever the data/image is shown. Swedish
private-label products (a store's own generic groceries, not a branded item)
are frequently missing entirely - this is expected, not a bug, and callers
must treat "no image found" as a normal, common outcome, not an error.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://world.openfoodfacts.org/api/v2"
USER_AGENT = "Matjakt/1.0 (+https://adamfrom-code.github.io/matjakt)"
ATTRIBUTION = {"text": "Bilddata från Open Food Facts (CC BY-SA)", "url": "https://openfoodfacts.org"}


class OpenFoodFactsError(Exception):
    """Raised for network/HTTP failures - callers should treat this exactly
    like "no image found" (fall back to the placeholder icon), never as a
    reason to fail the request it's supplementing."""


def image_url_for_gtin(gtin):
    """Returns an image URL for a GTIN, or None if Open Food Facts doesn't
    have this product (common for Swedish private-label groceries) or the
    request fails outright."""
    if not gtin:
        return None
    url = f"{API_BASE}/product/{urllib.parse.quote(str(gtin))}.json?fields=image_front_url,image_url"
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise OpenFoodFactsError(str(error))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise OpenFoodFactsError(str(error))
    if data.get("status") != 1:
        return None
    product = data.get("product") or {}
    return product.get("image_front_url") or product.get("image_url") or None
