import uuid
from datetime import date

import pytest

from app.db.session import AsyncSessionLocal
from app.models.trade import Trade
from app.models.enums import InstrumentType, CurrencyPair, Direction, Currency, TradeStatus


@pytest.mark.asyncio
async def test_insert_and_fetch_trade():
    async with AsyncSessionLocal() as session:
        trade = Trade(
            trade_id=uuid.uuid4(),
            instrument_type=InstrumentType.SPOT,
            currency_pair=CurrencyPair.EURUSD,
            direction=Direction.BUY,
            currency_1=Currency.EUR,
            notional_1=1000000,
            currency_2=Currency.USD,
            notional_2=1085000,
            trade_date=date.today(),
            counterparty="BANK_A",
            status=TradeStatus.BOOKED,
            comment=None,
            instrument_details={"rate": 1.085, "settlement_date": "2026-08-01"},
        )
        session.add(trade)
        await session.commit()

        fetched = await session.get(Trade, trade.trade_id)
        assert fetched is not None
        assert fetched.counterparty == "BANK_A"