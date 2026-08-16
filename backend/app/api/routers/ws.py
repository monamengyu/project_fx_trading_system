"""WebSocket endpoints for live market data.

`/ws/market-data` pushes rate updates to subscribed clients. A background task
(``stream_rates``, started by the app lifespan) periodically fetches the cached
rates for every supported pair and broadcasts them to all connected clients.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.enums import CurrencyPair
from app.services.market_data.frankfurter_client import get_rate

router = APIRouter(tags=["websocket"])

# how often rates are fetched and pushed to subscribers
RATE_STREAM_INTERVAL_SECONDS = 5


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


@router.websocket("/ws/market-data")
async def market_data_ws(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # keep the connection open; receive() also surfaces client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
