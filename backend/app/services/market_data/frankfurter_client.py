import time

import httpx

from app.models.enums import CurrencyPair

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CACHE_TTL_SECONDS = 3600

_cache: dict[str, tuple[float, str, float]] = {}


async def get_rate(pair: CurrencyPair) -> tuple[float, str]:
    cached = _cache.get(pair.value)
    now = time.monotonic()
    if cached and now - cached[2] < CACHE_TTL_SECONDS:
        return cached[0], cached[1]

    base, quote = pair.value[:3], pair.value[3:]
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(FRANKFURTER_URL, params={"base": base, "symbols": quote})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch rate for {pair.value}") from exc
    data = response.json()
    rate, as_of = data["rates"][quote], data["date"]
    _cache[pair.value] = (rate, as_of, now)
    return rate, as_of
