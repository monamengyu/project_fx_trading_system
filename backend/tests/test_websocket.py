import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.api.routers import ws
from app.api.routers.ws import ConnectionManager
from app.main import app
from app.models.enums import Currency, CurrencyPair, Direction, InstrumentType, TradeStatus
from app.models.trade import Trade
from app.services.market_data.pairs import SUPPORTED_PAIRS


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

    assert message["pair"] in SUPPORTED_PAIRS
    assert message["rate"] == 1.1567
    assert message["as_of"] == "2026-08-14"


def _booked_spot_trade():
    """A BOOKED EURUSD BUY SPOT 1,000,000 @ 1.085 (no DB session needed)."""
    return Trade(
        trade_id=uuid.uuid4(),
        instrument_type=InstrumentType.SPOT,
        currency_pair=CurrencyPair.EURUSD,
        direction=Direction.BUY,
        currency_1=Currency.EUR,
        notional_1=1000000,
        currency_2=Currency.USD,
        notional_2=1085000,
        trade_date=date(2026, 8, 14),
        counterparty="BANK_A",
        status=TradeStatus.BOOKED,
        comment=None,
        instrument_details={
            "instrument_type": "SPOT",
            "rate": 1.085,
            "settlement_date": "2026-08-19",
        },
    )


def test_positions_ws_receives_mtm_message():
    trade = _booked_spot_trade()
    # TestClient runs the app lifespan, which starts the streaming tasks.
    with (
        patch.object(ws, "MTM_STREAM_INTERVAL_SECONDS", 0.05),
        patch.object(ws, "load_booked_trades", new=AsyncMock(return_value=[trade])),
        patch.object(
            ws, "get_rate", new=AsyncMock(return_value=(1.15, date(2026, 8, 14)))
        ),
        TestClient(app) as client,
        client.websocket_connect("/ws/positions") as websocket,
    ):
        message = websocket.receive_json()

    # 1,000,000 * (1.15 - 1.085) = 65,000 USD
    assert message["trade_id"] == str(trade.trade_id)
    assert message["currency_pair"] == "EURUSD"
    assert message["mtm_value"] == 65000.0
    # spot BUY 1,000,000: delta = +1,000,000, gamma/vega/theta are zero
    assert message["greeks"] == {
        "delta": 1000000.0,
        "gamma": 0.0,
        "vega": 0.0,
        "theta": 0.0,
    }
    assert message["as_of"].endswith("Z")
