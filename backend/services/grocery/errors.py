"""Shared error types for grocery providers.

These exist so provider-agnostic code (the collectors, and later the
scheduler) can react to "the source refused us" without knowing which chain
it was talking to. Each provider still defines its own named subclass, so
chain-specific handling and clearer tracebacks stay possible.
"""


class ProviderRequestError(Exception):
    """A request that failed after its retries, or returned an unexpected shape."""


class ProviderBlockedError(ProviderRequestError):
    """The source actively refused us - a bot challenge, a 403, a 429, or an
    empty body where JSON was expected. Terminal, not transient: a collector
    must stop and report rather than retrying its way through a refusal.

    partial_products carries whatever had already been collected before the
    block hit, so real data gathered earlier in a run is still persisted
    instead of being thrown away.
    """

    def __init__(self, message, partial_products=None):
        super().__init__(message)
        self.partial_products = partial_products or []
