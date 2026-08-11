from datetime import date
from unittest.mock import patch

import pytest

from app.models.enums import CurrencyPair
from app.services.market_data.cache import MarketDataCache


@pytest.fixture
def cache():
    return MarketDataCache(ttl_seconds=60)


async def test_get_miss_returns_none(cache):
    assert await cache.get(CurrencyPair.EURUSD) is None
    assert cache.stats == {"hits": 0, "misses": 1}


async def test_set_then_get_is_a_hit(cache):
    await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
    entry = await cache.get(CurrencyPair.EURUSD)
    assert entry is not None
    assert entry.rate == 1.0862
    assert entry.as_of == date(2026, 8, 1)
    assert cache.stats == {"hits": 1, "misses": 0}


async def test_get_returns_entry_within_ttl(cache):
    with patch(
        "app.services.market_data.cache.time.monotonic", side_effect=[1000.0, 1059.0]
    ):
        await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
        assert await cache.get(CurrencyPair.EURUSD) is not None


async def test_get_returns_none_after_ttl_expiry(cache):
    with patch(
        "app.services.market_data.cache.time.monotonic", side_effect=[1000.0, 1061.0]
    ):
        await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
        assert await cache.get(CurrencyPair.EURUSD) is None
    assert cache.stats == {"hits": 0, "misses": 1}


async def test_peek_returns_expired_entry_without_counting_hit(cache):
    with patch("app.services.market_data.cache.time.monotonic", side_effect=[1000.0]):
        await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
    assert await cache.peek(CurrencyPair.EURUSD) is not None
    assert cache.stats == {"hits": 0, "misses": 0}


async def test_peek_returns_none_for_missing_pair(cache):
    assert await cache.peek(CurrencyPair.EURUSD) is None


async def test_entries_are_keyed_by_pair(cache):
    await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
    await cache.set(CurrencyPair.GBPUSD, 1.2730, date(2026, 8, 1))
    eurusd = await cache.get(CurrencyPair.EURUSD)
    gbpusd = await cache.get(CurrencyPair.GBPUSD)
    assert eurusd is not None and gbpusd is not None
    assert eurusd.rate == 1.0862
    assert gbpusd.rate == 1.2730


async def test_clear_resets_store_and_stats(cache):
    await cache.set(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))
    await cache.clear()
    assert await cache.get(CurrencyPair.EURUSD) is None
    assert cache.stats == {"hits": 0, "misses": 1}
