"""Single source of truth for the currency pairs the system supports.

``CurrencyPair`` (the enum) is the canonical member list; this module derives
the ordered set used for display/validation and holds rate-symbol aliases for
currencies the upstream provider does not publish under their own code.
"""

from app.models.enums import CurrencyPair

# Frankfurter (ECB) publishes the onshore CNY rate but not the offshore CNH
# code, so USDCNH is priced via CNY.
RATE_SYMBOL_ALIASES = {"CNH": "CNY"}

# Canonical, ordered list of pair codes as exposed to clients.
SUPPORTED_PAIRS: list[str] = [pair.value for pair in CurrencyPair]


def rate_symbol(currency: str) -> str:
    """Return the currency code the rate provider publishes for ``currency``."""
    return RATE_SYMBOL_ALIASES.get(currency, currency)


def fetch_symbols(pair: str) -> tuple[str, str]:
    """Split a pair code into (base, quote) using provider-published symbols."""
    return pair[:3], rate_symbol(pair[3:])
