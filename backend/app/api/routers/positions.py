"""Position summary endpoint.

Aggregates confirmed (BOOKED) trades per currency pair and reports the net
position: notional totals, option greeks and the unrealised P&L (mark to
market) in USD.

MTM semantics
-------------
For each leg the P&L is the current market value minus the executed (booked)
value, normalised to USD:

* spot/forward legs are valued at ``notional_1 * live rate`` versus the
  booked rate, so the P&L in the quote currency is ``signed notional_1 *
  (live rate - booked rate)``.
* option legs are repriced at the live spot with a 10% volatility; the
  current premium (per unit) times the contract notional is compared against
  the premium paid at execution.
"""

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import Direction, TradeStatus
from app.models.trade import Trade
from app.schemas.instrument_details import (
    ForwardDetails,
    OptionDetails,
    SpotDetails,
)
from app.schemas.positions import PositionRead
from app.services.market_data.frankfurter_client import get_rate
from app.services.pricing.option_pricer import price_option_details

router = APIRouter(prefix="/positions", tags=["positions"])


def _to_usd(amount: float, currency_2: str, rate: float) -> float:
    """Convert a P&L amount quoted in currency_2 to USD at the live rate."""
    if currency_2 == "USD":
        return amount
    # Only USD-anchored pairs are supported; the quote currency (JPY for
    # USDJPY) needs dividing by the live rate (JPY per USD).
    return amount / rate


def _premium_to_usd(premium: float, premium_currency: str, currency_2: str, rate: float) -> float:
    """Convert an executed premium (stored total) to USD."""
    if premium_currency == "USD":
        return float(premium)
    if premium_currency == currency_2:
        return _to_usd(float(premium), currency_2, rate)
    raise ValueError(f"cannot convert premium in {premium_currency} to USD")


@router.get("", response_model=list[PositionRead])
async def list_positions(db: AsyncSession = Depends(get_db)) -> list[PositionRead]:
    """Return one position summary row per currency pair for BOOKED trades."""
    result = await db.execute(select(Trade).where(Trade.status == TradeStatus.BOOKED))
    trades = list(result.scalars().all())

    # cached market rate per pair (None if upstream unavailable)
    rates: dict[str, float | None] = {}
    for pair in {t.currency_pair for t in trades}:
        try:
            rate, _ = await get_rate(pair)
        except RuntimeError:
            rate = None
        rates[pair.value] = rate

    totals: dict[str, dict] = {}
    for trade in trades:
        pair_value = trade.currency_pair.value
        rate = rates[pair_value]
        currency_2 = pair_value[3:]
        signed = 1.0 if trade.direction == Direction.BUY else -1.0
        notional_1 = float(trade.notional_1)
        details = trade.instrument_details or {}
        instrument_type = details.get("instrument_type")

        agg = totals.setdefault(
            pair_value,
            {
                "total_notional_1": 0.0,
                "net_notional_1": 0.0,
                "total_notional_2": 0.0,
                "net_notional_2": 0.0,
                "missing_leg2": False,
                "delta": 0.0,
                "gamma": 0.0,
                "vega": 0.0,
                "theta": 0.0,
                "pnl_usd": 0.0,
                "has_option": False,
                "unpriced_option": False,
            },
        )
        agg["total_notional_1"] += notional_1
        agg["net_notional_1"] += signed * notional_1

        if instrument_type == "OPTION":
            agg["has_option"] = True
            # Option legs have no currency_2 notional; they contribute only to
            # the currency_1 total/net and to the greeks/MTM when repriced.
            if rate is None:
                agg["unpriced_option"] = True
                continue
            try:
                option = OptionDetails(**details)
                priced = price_option_details(
                    option, spot=rate, vol=0.10, valuation_date=date.today()
                )
                executed_usd = _premium_to_usd(
                    option.premium, option.premium_currency, currency_2, rate
                )
            except (ValueError, ValidationError):
                agg["unpriced_option"] = True
                continue
            greeks = priced.greeks
            agg["delta"] += signed * notional_1 * greeks.delta
            agg["gamma"] += signed * notional_1 * greeks.gamma
            agg["vega"] += signed * notional_1 * greeks.vega
            agg["theta"] += signed * notional_1 * greeks.theta
            current_usd = _to_usd(priced.premium * notional_1, currency_2, rate)
            agg["pnl_usd"] += signed * (current_usd - executed_usd)
            continue

        # SPOT / FORWARD legs
        if instrument_type == "FORWARD":
            booked_rate = ForwardDetails(**details).rate
        else:
            booked_rate = SpotDetails(**details).rate

        agg["delta"] += signed * notional_1

        if trade.notional_2 is not None:
            leg2 = float(trade.notional_2)
            missing_leg2 = False
        elif rate is None:
            leg2 = 0.0
            missing_leg2 = True
        else:
            leg2 = notional_1 * rate
            missing_leg2 = False

        agg["total_notional_2"] += leg2
        agg["missing_leg2"] = agg["missing_leg2"] or missing_leg2
        agg["net_notional_2"] += signed * leg2

        if rate is not None:
            pnl_ccy2 = signed * notional_1 * (rate - booked_rate)
            agg["pnl_usd"] += _to_usd(pnl_ccy2, currency_2, rate)

    positions: list[PositionRead] = []
    for pair_value, agg in totals.items():
        rate = rates[pair_value]
        # if any spot/forward leg's currency_2 amount could not be computed,
        # the totals would be incomplete -> return null rather than misleading
        total_notional_2 = net_notional_2 = None
        if not agg["missing_leg2"]:
            total_notional_2 = round(agg["total_notional_2"], 2)
            net_notional_2 = round(agg["net_notional_2"], 2)

        # Greeks are only meaningful when every option leg could be priced.
        delta = gamma = vega = theta = None
        if not agg["unpriced_option"]:
            delta = round(agg["delta"], 2)
            if agg["has_option"]:
                gamma = round(agg["gamma"], 2)
                vega = round(agg["vega"], 2)
                theta = round(agg["theta"], 2)
            else:
                gamma = vega = theta = 0.0

        positions.append(
            PositionRead(
                currency_pair=pair_value,
                currency_1=pair_value[:3],
                currency_2=pair_value[3:],
                total_notional_1=round(agg["total_notional_1"], 2),
                total_notional_2=total_notional_2,
                net_notional_1=round(agg["net_notional_1"], 2),
                net_notional_2=net_notional_2,
                delta=delta,
                gamma=gamma,
                vega=vega,
                theta=theta,
                mtm_value=None
                if rate is None or agg["unpriced_option"]
                else round(agg["pnl_usd"], 2),
            )
        )
    positions.sort(key=lambda position: position.currency_pair)
    return positions
