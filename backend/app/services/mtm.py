"""Per-trade mark-to-market (MTM) and greeks helpers.

Each BOOKED leg is valued as current market value minus the executed (booked)
value, normalised to USD:

* spot/forward legs: ``signed notional_1 * (live rate - booked rate)`` in the
  quote currency, converted to USD at the live rate.
* option legs: repriced at the live spot with a 10% volatility; the current
  per-unit premium times the contract notional is compared against the
  premium paid at execution (both converted to USD).

These conventions intentionally mirror the aggregation in
``app.api.routers.positions`` so the live WebSocket stream and the REST
position summary agree.
"""

from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from app.models.enums import Direction
from app.models.trade import Trade
from app.schemas.instrument_details import ForwardDetails, OptionDetails, SpotDetails
from app.services.pricing.option_pricer import price_option_details


def to_usd(amount: float, currency_2: str, rate: float) -> float:
    """Convert a P&L amount quoted in ``currency_2`` to USD at the live rate."""
    if currency_2 == "USD":
        return amount
    # Only USD-anchored pairs are supported; a non-USD quote (JPY for USDJPY)
    # needs dividing by the live rate (JPY per USD).
    return amount / rate


def premium_to_usd(
    premium: float, premium_currency: str, currency_2: str, rate: float
) -> float:
    """Convert an executed premium (stored total) to USD."""
    if premium_currency == "USD":
        return float(premium)
    if premium_currency == currency_2:
        return to_usd(float(premium), currency_2, rate)
    raise ValueError(f"cannot convert premium in {premium_currency} to USD")


@dataclass
class TradeValuation:
    """Live per-trade valuation: unrealised P&L in USD plus greeks."""

    mtm_value: float
    delta: float
    gamma: float
    vega: float
    theta: float


def compute_trade_valuation_usd(trade: Trade, rate: float | None) -> TradeValuation | None:
    """Return the live MTM (USD) and greeks for a single BOOKED trade.

    ``rate`` is the current live rate for the trade's pair, or ``None`` when
    the upstream rate provider is unavailable. Returns ``None`` when the value
    cannot be computed (missing live rate or a leg that fails to reprice).

    Greek scaling mirrors ``app.api.routers.positions`` so a pair's streamed
    per-trade values sum to the REST summary:

    * spot/forward: delta = ``signed * notional_1``; gamma/vega/theta = 0.
    * options: the model returns per-one-unit, per-1%-vol and per-year
      quantities, so delta = ``signed * notional_1 * greeks.delta``,
      gamma/vega are divided by 100 and theta by 365.
    """
    if rate is None:
        return None

    details = trade.instrument_details or {}
    instrument_type = details.get("instrument_type")
    if instrument_type is None:
        return None

    currency_2 = trade.currency_pair.value[3:]
    signed = 1.0 if trade.direction == Direction.BUY else -1.0
    notional_1 = float(trade.notional_1)

    if instrument_type == "OPTION":
        try:
            option = OptionDetails(**details)
            priced = price_option_details(
                option, spot=rate, vol=0.10, valuation_date=date.today()
            )
            executed_usd = premium_to_usd(
                option.premium, option.premium_currency, currency_2, rate
            )
        except (ValueError, ValidationError):
            return None
        current_usd = to_usd(priced.premium * notional_1, currency_2, rate)
        greeks = priced.greeks
        return TradeValuation(
            mtm_value=signed * (current_usd - executed_usd),
            delta=signed * notional_1 * greeks.delta,
            gamma=signed * notional_1 * greeks.gamma / 100.0,
            vega=signed * notional_1 * greeks.vega / 100.0,
            theta=signed * notional_1 * greeks.theta / 365.0,
        )

    # SPOT / FORWARD legs
    try:
        if instrument_type == "FORWARD":
            booked_rate = ForwardDetails(**details).rate
        else:
            booked_rate = SpotDetails(**details).rate
    except ValidationError:
        return None

    pnl_ccy2 = signed * notional_1 * (rate - booked_rate)
    return TradeValuation(
        mtm_value=to_usd(pnl_ccy2, currency_2, rate),
        delta=signed * notional_1,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
    )


def compute_trade_mtm_usd(trade: Trade, rate: float | None) -> float | None:
    """Return the MTM (unrealised P&L in USD) for a single trade.

    ``rate`` is the current live rate for the trade's pair, or ``None`` when
    the upstream rate provider is unavailable. Returns ``None`` when the value
    cannot be computed (missing live rate or a leg that fails to reprice).
    """
    valuation = compute_trade_valuation_usd(trade, rate)
    return None if valuation is None else valuation.mtm_value
