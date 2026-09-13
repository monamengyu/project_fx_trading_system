"""Frozen market data for reproducible NL-parse evaluation runs.

The parser reads the live market whenever a draft omits a rate, which makes an
evaluation impossible to replay: identical input can resolve to a different
trade tomorrow. This module swaps the live provider for a snapshot recorded
once, so rate movement cannot leak into the measurements.

Refresh the snapshot with::

    python -c "import asyncio; from evaluation.frozen_rates import record_snapshot; asyncio.run(record_snapshot())"
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.models.enums import CurrencyPair

DEFAULT_SNAPSHOT_PATH = Path(__file__).with_name("frozen_rates.json")


class MissingFrozenRate(Exception):
    """A frozen run asked for a pair the snapshot does not contain.

    Deliberately not a ``RuntimeError`` or ``ValueError`` subclass: the resolver
    converts those into ``ParseError``, which the retry loop would then report as
    a model that could not parse its input. A missing snapshot entry is a broken
    harness rather than a parser failure, so it must stop the run loudly instead
    of being folded into the error-rate measurements.
    """


class FrozenRateProvider:
    """A ``RateProvider`` backed by a snapshot file instead of the live market.

    Never falls back to the network: a silent live lookup would reintroduce
    exactly the non-determinism the snapshot exists to remove.
    """

    def __init__(self, rates: dict[str, tuple[float, date]]) -> None:
        self._rates = dict(rates)

    @classmethod
    def from_file(cls, path: Path | str | None = None) -> FrozenRateProvider:
        payload = json.loads(
            Path(path or DEFAULT_SNAPSHOT_PATH).read_text(encoding="utf-8")
        )
        return cls(
            {
                code: (entry["rate"], date.fromisoformat(entry["as_of"]))
                for code, entry in payload["rates"].items()
            }
        )

    async def __call__(self, pair: CurrencyPair) -> tuple[float, date]:
        try:
            return self._rates[pair.value]
        except KeyError:
            raise MissingFrozenRate(
                f"no frozen rate for {pair.value}; re-record the snapshot"
            ) from None

    @property
    def pairs(self) -> set[str]:
        """The pair codes this snapshot can price."""
        return set(self._rates)


async def record_snapshot(path: Path | str | None = None) -> Path:
    """Fetch live rates for every supported pair and write a new snapshot."""
    from app.services.market_data.frankfurter_client import get_rate
    from app.services.market_data.pairs import SUPPORTED_PAIRS

    target = Path(path or DEFAULT_SNAPSHOT_PATH)
    rates = {}
    for code in SUPPORTED_PAIRS:
        rate, as_of = await get_rate(CurrencyPair[code])
        rates[code] = {"rate": rate, "as_of": as_of.isoformat()}
    payload = {"frozen_at": date.today().isoformat(), "rates": rates}
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target
