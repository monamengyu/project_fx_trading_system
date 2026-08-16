"""Position summary endpoint.

Aggregates confirmed (BOOKED) trades per currency pair and marks the net
position to market using the cached live rate.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import Direction, TradeStatus
from app.models.trade import Trade
from app.schemas.positions import PositionRead
from app.services.market_data.frankfurter_client import get_rate

router = APIRouter(prefix="/positions", tags=["positions"])


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
        if trade.notional_2 is not None:
            leg2 = float(trade.notional_2)
            missing_leg2 = False
        elif rate is None:
            leg2 = 0.0
            missing_leg2 = True
        else:
            leg2 = float(trade.notional_1) * rate
            missing_leg2 = False

        agg = totals.setdefault(
            pair_value,
            {
                "count": 0,
                "total_notional_1": 0.0,
                "net_notional_1": 0.0,
                "total_notional_2": 0.0,
                "net_notional_2": 0.0,
                "missing_leg2": False,
            },
        )
        agg["count"] += 1
        agg["total_notional_1"] += float(trade.notional_1)
        agg["total_notional_2"] += leg2
        agg["missing_leg2"] = agg["missing_leg2"] or missing_leg2
        if trade.direction == Direction.BUY:
            agg["net_notional_1"] += float(trade.notional_1)
            agg["net_notional_2"] += leg2
        else:
            agg["net_notional_1"] -= float(trade.notional_1)
            agg["net_notional_2"] -= leg2

    positions: list[PositionRead] = []
    for pair_value, agg in totals.items():
        rate = rates[pair_value]
        # if any trade's currency_2 leg could not be computed, the totals
        # would be incomplete -> return null rather than a misleading number
        total_notional_2 = net_notional_2 = None
        if not agg["missing_leg2"]:
            total_notional_2 = round(agg["total_notional_2"], 2)
            net_notional_2 = round(agg["net_notional_2"], 2)
        positions.append(
            PositionRead(
                currency_pair=pair_value,
                currency_1=pair_value[:3],
                currency_2=pair_value[3:],
                count=agg["count"],
                total_notional_1=agg["total_notional_1"],
                total_notional_2=total_notional_2,
                net_notional_1=agg["net_notional_1"],
                net_notional_2=net_notional_2,
                mtm_value=None
                if rate is None
                else round(agg["net_notional_1"] * rate, 2),
            )
        )
    positions.sort(key=lambda position: position.currency_pair)
    return positions
