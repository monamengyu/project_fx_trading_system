"""In-memory TTL cache for market data rates.

The cache layer sits between the REST API and the upstream provider (e.g.
Frankfurter). It stores the most recently fetched rate per currency pair and
serves it within a configurable TTL window so repeated requests do not hit the
upstream provider on every call.

All methods are async so a Redis-backed implementation can be swapped in later
without changing callers.
"""

import time
from dataclasses import dataclass
from datetime import date

from app.core.config import settings
from app.models.enums import CurrencyPair


@dataclass(frozen=True)
class CachedRate:
    rate: float
    as_of: date
    fetched_at: float  # time.monotonic() at the moment the entry was stored


class MarketDataCache:
    """TTL cache keyed by currency pair.

    ``get`` only returns entries that are still within the TTL window and
    counts a hit; everything else is a miss. ``peek`` returns any stored entry
    (even expired) without affecting the hit/miss counters, which lets callers
    implement stale-on-error fallbacks.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, CachedRate] = {}
        self._hits = 0
        self._misses = 0

    async def get(self, pair: CurrencyPair) -> CachedRate | None:
        """Return the cached rate if fresh, otherwise ``None`` (a miss)."""
        entry = self._store.get(pair.value)
        if entry is None or time.monotonic() - entry.fetched_at >= self._ttl_seconds:
            self._misses += 1
            return None
        self._hits += 1
        return entry

    async def peek(self, pair: CurrencyPair) -> CachedRate | None:
        """Return any stored entry (even expired) without counting a hit/miss."""
        return self._store.get(pair.value)

    async def set(self, pair: CurrencyPair, rate: float, as_of: date) -> None:
        self._store[pair.value] = CachedRate(
            rate=rate, as_of=as_of, fetched_at=time.monotonic()
        )

    async def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        """Hit/miss counters for observability."""
        return {"hits": self._hits, "misses": self._misses}


# Process-wide singleton used by the Frankfurter client.
market_data_cache = MarketDataCache(ttl_seconds=settings.market_data_cache_ttl_seconds)
