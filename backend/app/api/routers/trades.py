import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.enums import TradeState, TradeStatus
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.schemas.trade import TradeCreate, TradeHistoryRead, TradeRead
from app.services.trade_lifecycle import append_state

router = APIRouter(prefix="/trades", tags=["trades"])


@router.post("", response_model=TradeRead, status_code=201)
async def create_trade(payload: TradeCreate, db: AsyncSession = Depends(get_db)) -> Trade:
    trade = Trade(
        **payload.model_dump(exclude={"instrument_details"}),  # Unpack the payload excluding instrument_details straight into Trade()
        instrument_details=payload.instrument_details.model_dump(mode="json"),
        trade_date=date.today(),
        status=TradeStatus.PENDING_CONFIRMATION,
    )
    db.add(trade)
    await db.flush()  # assign trade_id before writing the lifecycle log
    # record the initial state in the append-only lifecycle log
    await append_state(db, trade.trade_id, TradeState.PENDING_CONFIRMATION)
    await db.commit()
    await db.refresh(trade)
    return trade


@router.get("", response_model=list[TradeRead])
async def list_trades(db: AsyncSession = Depends(get_db)) -> list[Trade]:
    result = await db.execute(select(Trade))
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
