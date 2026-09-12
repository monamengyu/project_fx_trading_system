from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.enums import CurrencyPair
from app.services.market_data import frankfurter_client
from app.services.market_data.cache import CachedRate


class FakeCache:
    """Controllable stand-in for the cache singleton used by get_rate."""

    def __init__(self, fresh=None, stale=None):
        self.fresh = fresh
        self.stale = stale
        self.set_calls = []

    async def get(self, pair):
        return self.fresh

    async def peek(self, pair):
        return self.stale

    async def set(self, pair, rate, as_of):
        self.set_calls.append((pair, rate, as_of))


# --- fetch_rate -------------------------------------------------------------


async def test_fetch_rate_success():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {"USD": 1.0862}, "date": "2026-08-01"}

    class FakeClient:
        def __init__(self, response):
            self.response = response
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params):
            self.calls.append((url, params))
            return self.response

    fake_client = FakeClient(FakeResponse())
    with patch.object(
        frankfurter_client.httpx, "AsyncClient", return_value=fake_client
    ):
        rate, as_of = await frankfurter_client.fetch_rate(CurrencyPair.EURUSD)
    assert (rate, as_of) == (1.0862, date(2026, 8, 1))
    assert fake_client.calls == [
        (
            "https://api.frankfurter.dev/v1/latest",
            {"base": "EUR", "symbols": "USD"},
        )
    ]


async def test_fetch_rate_usdcnh_queries_cny_symbol():
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"rates": {"CNY": 7.2}, "date": "2026-08-01"}

    class FakeClient:
        def __init__(self, response):
            self.response = response
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params):
            self.calls.append((url, params))
            return self.response

    fake_client = FakeClient(FakeResponse())
    with patch.object(
        frankfurter_client.httpx, "AsyncClient", return_value=fake_client
    ):
        rate, as_of = await frankfurter_client.fetch_rate(CurrencyPair.USDCNH)
    assert (rate, as_of) == (7.2, date(2026, 8, 1))
    assert fake_client.calls == [
        (
            "https://api.frankfurter.dev/v1/latest",
            {"base": "USD", "symbols": "CNY"},
        )
    ]


async def test_fetch_rate_http_error_raises_runtime_error():
    class FakeResponse:
        status_code = 500

        def raise_for_status(self):
            raise httpx.HTTPStatusError("Server error", request=None, response=self)

        def json(self):
            return {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params):
            return FakeResponse()

    with patch.object(
        frankfurter_client.httpx, "AsyncClient", return_value=FakeClient()
    ), pytest.raises(RuntimeError, match="EURUSD"):
        await frankfurter_client.fetch_rate(CurrencyPair.EURUSD)


async def test_fetch_rate_network_error_raises_runtime_error():
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params):
            raise httpx.ConnectError("upstream down")

    with patch.object(
        frankfurter_client.httpx, "AsyncClient", return_value=FailingClient()
    ), pytest.raises(RuntimeError, match="EURUSD"):
        await frankfurter_client.fetch_rate(CurrencyPair.EURUSD)


# --- get_rate (cache integration) -------------------------------------------


async def test_get_rate_serves_fresh_cache_hit_without_fetching():
    fresh = CachedRate(rate=1.0862, as_of=date(2026, 8, 1), fetched_at=0.0)
    fake = FakeCache(fresh=fresh)
    with patch.object(frankfurter_client, "market_data_cache", fake), patch.object(
        frankfurter_client,
        "fetch_rate",
        new=AsyncMock(side_effect=AssertionError("must not fetch upstream")),
    ):
        rate, as_of = await frankfurter_client.get_rate(CurrencyPair.EURUSD)
    assert (rate, as_of) == (1.0862, date(2026, 8, 1))
    assert fake.set_calls == []


async def test_get_rate_miss_fetches_and_populates_cache():
    fake = FakeCache(fresh=None)
    with patch.object(frankfurter_client, "market_data_cache", fake), patch.object(
        frankfurter_client,
        "fetch_rate",
        new=AsyncMock(return_value=(1.0862, date(2026, 8, 1))),
    ) as mock_fetch:
        rate, as_of = await frankfurter_client.get_rate(CurrencyPair.EURUSD)
    assert (rate, as_of) == (1.0862, date(2026, 8, 1))
    mock_fetch.assert_awaited_once_with(CurrencyPair.EURUSD)
    assert fake.set_calls == [(CurrencyPair.EURUSD, 1.0862, date(2026, 8, 1))]


async def test_get_rate_upstream_failure_serves_stale_rate():
    stale = CachedRate(rate=1.0850, as_of=date(2026, 7, 31), fetched_at=0.0)
    fake = FakeCache(fresh=None, stale=stale)
    with patch.object(frankfurter_client, "market_data_cache", fake), patch.object(
        frankfurter_client,
        "fetch_rate",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        rate, as_of = await frankfurter_client.get_rate(CurrencyPair.EURUSD)
    assert (rate, as_of) == (1.0850, date(2026, 7, 31))


async def test_get_rate_upstream_failure_without_stale_raises():
    fake = FakeCache(fresh=None, stale=None)
    with patch.object(frankfurter_client, "market_data_cache", fake), patch.object(
        frankfurter_client,
        "fetch_rate",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ), pytest.raises(RuntimeError):
        await frankfurter_client.get_rate(CurrencyPair.EURUSD)
