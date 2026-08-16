from datetime import date
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.routers import ws
from app.api.routers.ws import ConnectionManager
from app.main import app


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.sent = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent.append(message)


async def test_connection_manager_connect_broadcast_disconnect():
    manager = ConnectionManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()

    await manager.connect(ws1)
    await manager.connect(ws2)
    assert manager.active_connections == [ws1, ws2]

    await manager.broadcast({"pair": "EURUSD", "rate": 1.15})
    assert ws1.sent == [{"pair": "EURUSD", "rate": 1.15}]
    assert ws2.sent == [{"pair": "EURUSD", "rate": 1.15}]

    manager.disconnect(ws1)
    assert ws1 not in manager.active_connections
    assert ws2 in manager.active_connections


def test_market_data_ws_receives_rate_message():
    # TestClient runs the app lifespan, which starts the streaming task.
    with (
        patch.object(ws, "RATE_STREAM_INTERVAL_SECONDS", 0.05),
        patch.object(
            ws, "get_rate", new=AsyncMock(return_value=(1.1567, date(2026, 8, 14)))
        ),
        TestClient(app) as client,
        client.websocket_connect("/ws/market-data") as websocket,
    ):
        message = websocket.receive_json()

    assert message["pair"] in ("EURUSD", "GBPUSD", "USDJPY")
    assert message["rate"] == 1.1567
    assert message["as_of"] == "2026-08-14"
