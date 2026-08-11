"""Frankfurter (ECB daily reference rates) market data provider.

``get_rate`` is cache-first: it serves a cached rate while it is fresh and only
calls the upstream provider on a miss. If the upstream call fails and a
previously cached rate exists (even if expired), the stale rate is served as a
fallback so the API stays available; the ``as_of`` date keeps the staleness
transparent to the client.
"""

from datetime import date

import httpx

from app.models.enums import CurrencyPair
from app.services.market_data.cache import market_data_cache

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"


async def fetch_rate(pair: CurrencyPair) -> tuple[float, date]:
    """Fetch a fresh rate from the upstream Frankfurter API.

    Raises ``RuntimeError`` if the upstream request fails.
    """
    base, quote = pair.value[:3], pair.value[3:]
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                FRANKFURTER_URL, params={"base": base, "symbols": quote}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch rate for {pair.value}") from exc
    data = response.json()
    return data["rates"][quote], date.fromisoformat(data["date"])


async def get_rate(pair: CurrencyPair) -> tuple[float, date]:
    """Return the rate for a currency pair, using the caching layer."""
    cached = await market_data_cache.get(pair)
    if cached is not None:
        return cached.rate, cached.as_of

    try:
        rate, as_of = await fetch_rate(pair)
    except RuntimeError:
        stale = await market_data_cache.peek(pair)
        if stale is not None:
            return stale.rate, stale.as_of
        raise

    await market_data_cache.set(pair, rate, as_of)
    return rate, as_of
