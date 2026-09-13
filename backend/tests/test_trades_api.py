from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.trade import Trade
from app.models.trade_state import TradeStateLog
from app.services.business_calendar import (
    add_business_days,
    effective_trade_date,
    override_trade_date,
    spot_value_date,
)


@pytest.fixture
async def client():
    created_ids = []
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.created_trade_ids = created_ids
        yield ac
    if created_ids:
        async with AsyncSessionLocal() as session:
            # delete lifecycle rows first: the FK has no ON DELETE CASCADE
            await session.execute(
                delete(TradeStateLog).where(TradeStateLog.trade_id.in_(created_ids))
            )
            await session.execute(delete(Trade).where(Trade.trade_id.in_(created_ids)))
            await session.commit()


SPOT_PAYLOAD = {
    "instrument_type": "SPOT",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "currency_1": "EUR",
    "notional_1": 1000000,
    "currency_2": "USD",
    "counterparty": "BANK_A",
    "instrument_details": {
        "instrument_type": "SPOT",
        "rate": 1.085,
        "settlement_date": spot_value_date(date.today()).isoformat(),
    },
}


async def _post_trade(client, payload=SPOT_PAYLOAD):
    response = await client.post("/trades", json=payload)
    if response.status_code == 201:
        client.created_trade_ids.append(response.json()["trade_id"])
    return response


async def test_create_trade_success(client):
    response = await _post_trade(client)
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING_CONFIRMATION"
    assert body["instrument_details"]["rate"] == 1.085


async def test_create_trade_mismatched_instrument_type_fails(client):
    bad_payload = {**SPOT_PAYLOAD, "instrument_type": "FORWARD"}
    response = await _post_trade(client, bad_payload)
    assert response.status_code == 422


async def test_list_trades(client):
    await _post_trade(client)
    response = await client.get("/trades")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 1


async def test_get_trade_by_id(client):
    created = await _post_trade(client)
    trade_id = created.json()["trade_id"]
    response = await client.get(f"/trades/{trade_id}")
    assert response.status_code == 200
    assert response.json()["trade_id"] == trade_id


async def test_get_trade_not_found(client):
    response = await client.get("/trades/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


GBPUSD_PAYLOAD = {
    "instrument_type": "SPOT",
    "currency_pair": "GBPUSD",
    "direction": "BUY",
    "currency_1": "GBP",
    "notional_1": 500000,
    "currency_2": "USD",
    "counterparty": "BANK_B",
    "instrument_details": {
        "instrument_type": "SPOT",
        "rate": 1.27,
        "settlement_date": spot_value_date(date.today()).isoformat(),
    },
}


async def test_list_trades_filters_by_currency_pair(client):
    eurusd = await _post_trade(client, SPOT_PAYLOAD)
    gbpusd = await _post_trade(client, GBPUSD_PAYLOAD)
    assert eurusd.status_code == gbpusd.status_code == 201

    response = await client.get("/trades", params={"currency_pair": "GBPUSD"})
    assert response.status_code == 200
    body = response.json()
    assert all(t["currency_pair"] == "GBPUSD" for t in body)
    returned_ids = {t["trade_id"] for t in body}
    assert gbpusd.json()["trade_id"] in returned_ids


async def test_list_trades_paginates(client):
    await _post_trade(client)
    await _post_trade(client)
    await _post_trade(client)

    response = await client.get("/trades", params={"limit": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_trade_date_rolls_forward_on_weekend(client):
    # next Saturday from the real today; pinned so the booking and the
    # settlement-window validator agree on which day it is
    d = date.today()
    saturday = d + timedelta(days=(5 - d.weekday()) % 7)
    monday = saturday + timedelta(days=2)

    effective = effective_trade_date(saturday)
    payload = {
        **SPOT_PAYLOAD,
        "instrument_details": {
            **SPOT_PAYLOAD["instrument_details"],
            "settlement_date": spot_value_date(effective).isoformat(),
        },
    }
    with override_trade_date(saturday):
        response = await client.post("/trades", json=payload)

    assert response.status_code == 201
    assert response.json()["trade_date"] == monday.isoformat()
    client.created_trade_ids.append(response.json()["trade_id"])


async def test_list_trades_filters_by_status(client):
    created = await _post_trade(client)
    trade_id = created.json()["trade_id"]
    await client.post(f"/trades/{trade_id}/cancel", json={})

    response = await client.get("/trades", params={"status": "PENDING_CONFIRMATION"})
    assert response.status_code == 200
    body = response.json()
    assert all(t["status"] == "PENDING_CONFIRMATION" for t in body)
    assert trade_id not in [t["trade_id"] for t in body]


FORWARD_FILTER_PAYLOAD = {
    "instrument_type": "FORWARD",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "currency_1": "EUR",
    "notional_1": 1000000,
    "currency_2": "USD",
    "counterparty": "BANK_A",
    "instrument_details": {
        "instrument_type": "FORWARD",
        "rate": 1.09,
        "settlement_date": add_business_days(date.today(), 15).isoformat(),
    },
}


async def test_list_trades_filters_by_settlement_date(client):
    early = await _post_trade(client)  # SPOT: settles at the spot value date
    late = await _post_trade(client, FORWARD_FILTER_PAYLOAD)  # FORWARD: settles ~T+15bd
    assert early.status_code == late.status_code == 201
    early_id = early.json()["trade_id"]
    late_id = late.json()["trade_id"]

    response = await client.get(
        "/trades",
        params={
            "settlement_date_from": add_business_days(date.today(), 3).isoformat(),
            "settlement_date_to": add_business_days(date.today(), 30).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {t["trade_id"] for t in body}
    assert late_id in returned_ids
    assert early_id not in returned_ids
