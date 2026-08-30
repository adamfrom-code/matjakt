"""The GroceryProvider interface - one implementation per chain (ICA, Coop,
Willys, Hemköp, City Gross, Lidl), each entirely self-contained. Nothing
outside a provider's own file may know that chain's API shapes, request
patterns, or markup - the collector, the database, and the rest of the
backend only ever see RawProduct/Store, never a chain's raw response.

Mirrors services/recipe_providers/base.py's RecipeProvider pattern - same
"one small ABC, one file per source" shape, already proven out in this
codebase for TheMealDB.
"""

from abc import ABC, abstractmethod

from .models import RawProduct, Store


class GroceryProvider(ABC):
    name: str

    @abstractmethod
    def get_stores(self) -> list[Store]:
        """Every store this chain has that the collector could target. A
        provider free to return a partial/regional list on its first cut
        (see FAS B: one chain, one store) - the caller decides which of
        these to actually collect from, this method just answers "what's
        available"."""

    @abstractmethod
    def get_products(self, store_id: str) -> list[RawProduct]:
        """Every product this store carries, or as much of it as this
        provider can reach in one collector run. store_id is this chain's
        OWN store identifier (Store.external_store_id), not GroceryStore's
        internal database id - a provider never needs to know about the
        shared database at all."""

    @abstractmethod
    def get_product_details(self, product_id: str, store_id: str) -> RawProduct | None:
        """One product at one store, freshly fetched - used to refresh a
        single known item without re-walking the whole store (e.g. a price-
        check on demand). None if the product/store combination doesn't
        resolve to anything on this chain's site."""

    @abstractmethod
    def normalize_product(self, raw_product) -> RawProduct:
        """Turns this chain's own response shape (whatever get_products/
        get_product_details fetched internally) into a RawProduct. Every
        other method above should already return RawProduct instances built
        via this - it's exposed separately so a collector can normalize
        incrementally while paging through a large catalog, without needing
        to hold the chain's raw shape in memory for the whole store at once."""

    @abstractmethod
    def health_check(self) -> bool:
        """True if this chain's source is currently reachable and answering
        in the shape this provider expects - a cheap, fast check (one small
        request, not a full catalog walk), meant to back the status panel
        (FAS 13) and a collector's own circuit breaker (see FAS 8: stop
        instead of hammering a source that's already failing)."""
