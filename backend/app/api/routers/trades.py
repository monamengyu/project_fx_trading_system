import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Date, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import (
    Currency,
    CurrencyPair,
    Direction,
    InstrumentType,
    TradeState,
    TradeStatus,
)
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.schemas.trade import (
    TradeAmendRequest,
    TradeCancelRequest,
    TradeCreate,
    TradeHistoryRead,
    TradeRead,
)
from app.services import trade_lifecycle
from app.services.business_calendar import (
    effective_trade_date,
    is_business_day,
    spot_value_date,
)

router = APIRouter(prefix="/trades", tags=["trades"])


def _validate_settlement(
    trade_type: InstrumentType, settlement_date: date, trade_date: date
) -> None:
    """Re-apply the booking settlement rules against a trade's own trade_date."""
    spot = spot_value_date(trade_date)
    if not is_business_day(settlement_date):
        raise HTTPException(
            status_code=422,
            detail="settlement_date must be a business day (Mon-Fri)",
        )
    if trade_type == InstrumentType.SPOT:
        if not (trade_date <= settlement_date <= spot):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"SPOT settlement_date must be between {trade_date} and {spot} "
                    f"(trade date + 2 business days); use FORWARD for later dates"
                ),
            )
    else:  # FORWARD
        if settlement_date <= spot:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"FORWARD settlement_date must be after {spot} "
                    f"(trade date + 2 business days)"
                ),
            )


@router.post("", response_model=TradeRead, status_code=201)
async def create_trade(payload: TradeCreate, db: AsyncSession = Depends(get_db)) -> Trade:
    trade = Trade(
        **payload.model_dump(exclude={"instrument_details"}),  # Unpack the payload excluding instrument_details straight into Trade()
        instrument_details=payload.instrument_details.model_dump(mode="json"),
        # roll weekends forward so trade_date is always a business day
        trade_date=effective_trade_date(date.today()),
        status=TradeStatus.PENDING_CONFIRMATION,
    )
    db.add(trade)
    await db.flush()  # assign trade_id before writing the lifecycle log
    # record the initial state in the append-only lifecycle log
    await trade_lifecycle.append_state(
        db, trade.trade_id, TradeState.PENDING_CONFIRMATION
    )
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("", response_model=list[TradeRead])
async def list_trades(
    db: AsyncSession = Depends(get_db),
    instrument_type: InstrumentType | None = None,
    currency_pair: CurrencyPair | None = None,
    status: TradeStatus | None = None,
    trade_date_from: date | None = None,
    trade_date_to: date | None = None,
    settlement_date_from: date | None = None,
    settlement_date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Trade]:
    """List trades with optional filters and simple offset/limit pagination."""
    query = select(Trade)
    if instrument_type is not None:
        query = query.where(Trade.instrument_type == instrument_type)
    if currency_pair is not None:
        query = query.where(Trade.currency_pair == currency_pair)
    if status is not None:
        query = query.where(Trade.status == status)
    if trade_date_from is not None:
        query = query.where(Trade.trade_date >= trade_date_from)
    if trade_date_to is not None:
        query = query.where(Trade.trade_date <= trade_date_to)
    settlement_date = cast(
        Trade.instrument_details["settlement_date"].astext, Date
    )
    if settlement_date_from is not None:
        query = query.where(settlement_date >= settlement_date_from)
    if settlement_date_to is not None:
        query = query.where(settlement_date <= settlement_date_to)
    query = (
        query.order_by(Trade.trade_date.desc(), Trade.trade_id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{trade_id}", response_model=TradeRead)
async def get_trade(trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Trade:
    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.get("/{trade_id}/history", response_model=TradeHistoryRead)
async def get_trade_history(
    trade_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    result = await db.execute(
        select(TradeStateLog)
        .where(TradeStateLog.trade_id == trade_id)
        .order_by(TradeStateLog.state_id)
    )
    return {"trade_id": trade_id, "history": list(result.scalars().all())}


@router.post("/{trade_id}/cancel", response_model=TradeRead)
async def cancel_trade(
    trade_id: uuid.UUID,
    payload: TradeCancelRequest,
    db: AsyncSession = Depends(get_db),
) -> Trade:
    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    try:
        await trade_lifecycle.cancel_trade(db, trade, notes=payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(trade)
    return trade


@router.post("/{trade_id}/amend", response_model=TradeRead)
async def amend_trade(
    trade_id: uuid.UUID,
    payload: TradeAmendRequest,
    db: AsyncSession = Depends(get_db),
) -> Trade:
    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # The instrument type selects the details schema, so it can't change on
    # amend; only the economics within the existing type may be edited.
    if payload.instrument_details is not None and (
        payload.instrument_details.instrument_type != trade.instrument_type.value
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"instrument_details.instrument_type "
                f"({payload.instrument_details.instrument_type}) does not match "
                f"the trade's instrument_type ({trade.instrument_type.value})"
            ),
        )

    # For SPOT/FORWARD, validate the new settlement date against the trade's own
    # trade_date (the trade may have been booked days ago, not today).
    if (
        payload.instrument_details is not None
        and trade.instrument_type in (InstrumentType.SPOT, InstrumentType.FORWARD)
    ):
        _validate_settlement(
            trade.instrument_type,
            payload.instrument_details.settlement_date,
            trade.trade_date,
        )

    try:
        await trade_lifecycle.amend_trade(db, trade, notes=payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if payload.currency_pair is not None:
        trade.currency_pair = payload.currency_pair
        trade.currency_1 = Currency(payload.currency_pair.value[:3])
        trade.currency_2 = Currency(payload.currency_pair.value[3:])
    if payload.direction is not None:
        trade.direction = payload.direction
    if payload.counterparty is not None:
        trade.counterparty = payload.counterparty
    if payload.notional_1 is not None:
        trade.notional_1 = payload.notional_1
    if payload.comment is not None:
        trade.comment = payload.comment

    if payload.instrument_details is not None:
        trade.instrument_details = payload.instrument_details.model_dump(mode="json")

    # For SPOT/FORWARD the counterpart notional (notional_2) is derived as
    # notional_1 × rate, so keep it consistent with the amended values unless
    # the caller supplied it explicitly. OPTION trades don't store a notional_2.
    if payload.notional_2 is not None:
        trade.notional_2 = payload.notional_2
    elif trade.instrument_type in (InstrumentType.SPOT, InstrumentType.FORWARD):
        rate = (
            payload.instrument_details.rate
            if payload.instrument_details is not None
            else trade.instrument_details.get("rate")
        )
        trade.notional_2 = round(float(trade.notional_1) * float(rate), 2)

    await db.commit()
    await db.refresh(trade)
    return trade


@router.post("/{trade_id}/confirm", response_model=TradeRead)
async def confirm_trade(
    trade_id: uuid.UUID,
    payload: TradeCancelRequest,
    db: AsyncSession = Depends(get_db),
) -> Trade:
    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    try:
        await trade_lifecycle.confirm_trade(db, trade, notes=payload.comment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(trade)
    return trade
