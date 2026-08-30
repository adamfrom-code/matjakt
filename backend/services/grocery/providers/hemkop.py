"""Hemköp provider - a thin subclass of AxfoodProvider.

Hemköp runs the same Axfood platform as Willys. VERIFIED live rather than
assumed (2026-08-30): full responses from www.hemkop.se and www.willys.se
were compared field by field and have identical top-level keys and identical
product field sets, so the shared logic in providers/axfood.py applies
unchanged.

What genuinely DIFFERS between the two chains:

1. PRICES. The same product (GTIN 07340083443893, "Mellanmjölk Längre
   Hållbarhet 1,5%", product code 101233933_ST) was 16.50 at Willys and
   17.70 at Hemköp on the same day. That is a real chain price difference -
   exactly the comparison Matjakt exists to make - and it cross-matches
   cleanly because both chains key their images by the same GTIN.

2. PROMOTION LABELLING. Hemköp leaves conditionLabelFormatted EMPTY on
   promotions that are really multibuys (e.g. "Bryggkaffe Mellanrost Eko
   Fairtrade": ordinary 66.20, qualifyingCount 2, rewardLabel "129 kr",
   per-unit promotion price 64.50), whereas Willys fills it in with "2 för".
   This is why providers/axfood.py keys multibuy detection off
   qualifyingCount and NOT off conditionLabelFormatted - see that module's
   docstring. Getting this wrong would have reported a two-for price as a
   single-item campaign price on Hemköp.

3. LOYALTY OFFERS ARE PRESENT. Hemköp's sample contained promotions with
   campaignType "LOYALTY" (member-only pricing) alongside "GENERAL" ones.
   Those are stored as member_price, never as campaign_price, so a
   member-only deal is never shown as the price everyone pays.

=============================================================================
PROVIDER STATUS: see the class attributes below.
=============================================================================
No authentication of any kind: no key, no cookie, no session, no browser.

Store note: there is no Hemköp store in Gävle. The nearest online store to
Gävle is Hemköp Uppsala Svava C (storeId 4256, ~95 km), used for the
verification import. 205 stores total, 66 of them online.

Pricing scope: NATIONAL. Verified the same way as Willys - storeId=4256
(Uppsala Svava) and storeId=4203 (Falun C) return byte-identical responses
(27221 B both) with identical prices on every product. The endpoint accepts
but ignores storeId.
"""

from .axfood import (  # noqa: F401  (re-exported for symmetry with willys.py)
    AxfoodBlockedError as HemkopBlockedError,
    AxfoodProvider,
    AxfoodRequestError as HemkopRequestError,
)


class HemkopProvider(AxfoodProvider):
    name = "Hemköp"
    base_url = "https://www.hemkop.se/axfood/rest/v1"
    status = "working"
    # Verified 2026-08-30: two consecutive full imports against Hemköp Uppsala
    # Svava C (4256). 2216 products found each time; run 2 reported
    # 0 new / 100 updated, no block, no duplicate rows.
    recurring_import_verified = True
    pricing_scope = "national"
