"""WebSocket endpoints for live market data and MTM position updates.

`/ws/market-data` pushes rate updates to subscribed clients. `/ws/positions`
pushes live per-trade mark-to-market (MTM) values and greeks. Each is driven by
a background task (started by the app lifespan) that polls the underlying data
and broadcasts to all connected clients.
"""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.enums import CurrencyPair, TradeStatus
from app.models.trade import Trade
from app.services.market_data.frankfurter_client import get_rate
from app.services.mtm import compute_trade_valuation_usd

router = APIRouter(tags=["websocket"])

# how often rates are fetched and pushed to subscribers
RATE_STREAM_INTERVAL_SECONDS = 5
# how often per-trade MTM values are computed and pushed to subscribers
MTM_STREAM_INTERVAL_SECONDS = 5


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001 - a dead client must not break the loop
                self.disconnect(connection)


manager = ConnectionManager()
positions_manager = ConnectionManager()


def _utc_now_iso() -> str:
    """Current UTC time formatted as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def stream_rates() -> None:
    """Background task: fetch rates and broadcast them to subscribers."""
    while True:
        for pair in CurrencyPair:
            try:
                rate, as_of = await get_rate(pair)
            except RuntimeError:
                continue  # upstream unavailable; try again next cycle
            await manager.broadcast(
                {"pair": pair.value, "rate": rate, "as_of": as_of.isoformat()}
            )
        await asyncio.sleep(RATE_STREAM_INTERVAL_SECONDS)


async def load_booked_trades() -> list[Trade]:
    """Return all trades currently BOOKED, for live MTM reporting."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Trade).where(Trade.status == TradeStatus.BOOKED)
        )
        return list(result.scalars().all())


async def stream_positions_mtm() -> None:
    """Background task: broadcast per-trade MTM values and greeks to subscribers."""
    while True:
        if positions_manager.active_connections:
            try:
                trades = await load_booked_trades()
            except Exception:  # noqa: BLE001 - a DB outage must not kill the task
                trades = []
            for trade in trades:
                try:
                    rate, _ = await get_rate(trade.currency_pair)
                except RuntimeError:
                    continue  # no live rate for this pair; skip this cycle
                valuation = compute_trade_valuation_usd(trade, rate)
                if valuation is None:
                    continue
                await positions_manager.broadcast(
                    {
                        "trade_id": str(trade.trade_id),
                        "currency_pair": trade.currency_pair.value,
                        "mtm_value": round(valuation.mtm_value, 2),
                        "greeks": {
                            "delta": round(valuation.delta, 2),
                            "gamma": round(valuation.gamma, 2),
                            "vega": round(valuation.vega, 2),
                            "theta": round(valuation.theta, 2),
                        },
                        "as_of": _utc_now_iso(),
                    }
                )
        await asyncio.sleep(MTM_STREAM_INTERVAL_SECONDS)


@router.websocket("/ws/market-data")
async def market_data_ws(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # keep the connection open; receive() also surfaces client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/ws/positions")
async def positions_ws(websocket: WebSocket) -> None:
    await positions_manager.connect(websocket)
    try:
        # keep the connection open; receive() also surfaces client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        positions_manager.disconnect(websocket)
