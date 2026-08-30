"""Willys provider - a thin subclass of AxfoodProvider.

Willys and Hemköp run the same Axfood commerce platform and expose the same
public `/axfood/rest/v1/` REST API (verified live 2026-08-30 by comparing
full responses from both hosts: identical top-level keys, identical product
field sets). All request/parse/normalize logic therefore lives in
providers/axfood.py - see that module for the endpoint documentation, the
GTIN-from-image-URL derivation, and the campaign/member/multibuy semantics.

=============================================================================
PROVIDER STATUS: working / recurring import VERIFIED / national pricing
=============================================================================
No authentication of any kind: no key, no cookie, no session, no browser.

Verified import (2026-08-30), Willys Gävle Gestrike, storeId 2132 - two full
consecutive runs, no blocking:
    Run 1: 2054 products found, 100 saved, 100 new / 0 updated
    Run 2: 2054 products found, 100 saved, 0 new / 100 updated
    100/100 with image URL (sampled URLs return real JPEG/PNG, HTTP 200)
    100/100 with GTIN (derived + checksum-validated)
    100/100 with regular price
    100/100 with unit price (jämförpris)
    0 errors both runs
This is the first chain proven to tolerate a repeated automated import -
ICA is WAF-rate-limited and Coop needs a vendor API key.

LIMITATION - prices are NATIONAL, not per store. Verified: the same query
with storeId=2132 (Gävle Gestrike) and storeId=2223 (Gävle Hemsta) returns
byte-identical responses (35593 B both) with identical prices on every
product; the endpoint accepts but IGNORES storeId. Consistent with Willys
being a centrally-priced discount chain rather than independently-priced
franchises, but a Willys price must not be presented as independently
verified for one address.
=============================================================================
"""

from .axfood import (  # noqa: F401  (re-exported for existing callers/tests)
    AxfoodBlockedError as WillysBlockedError,
    AxfoodProvider,
    AxfoodRequestError as WillysRequestError,
    DEFAULT_SEARCH_TERMS,
    MAX_RETRIES,
    PAGE_SIZE,
    gtin_checksum_ok as _gtin_checksum_ok,
    gtin_from_image_url as _gtin_from_image_url,
    split_promotions,
    _parse_display_volume,
    _parse_swedish_price,
    _to_float,
)


class WillysProvider(AxfoodProvider):
    name = "Willys"
    base_url = "https://www.willys.se/axfood/rest/v1"
    status = "working"
    # Verified 2026-08-30: two consecutive full imports, the second reporting
    # 0 new / 100 updated, no block, no duplicate rows.
    recurring_import_verified = True
    pricing_scope = "national"
