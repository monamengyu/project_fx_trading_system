"""Pricing and analytics REST endpoints.

Provides live option quotes against the current (Frankfurter) spot rate. The
quote uses the same conventions as the position MTM: a fixed 10% volatility
and valuation at today's date, so a premium auto-filled into the trade entry
form matches the premium used when the option is later revalued.
"""

from datetime import date

from fastapi import APIRouter, HTTPException

from app.schemas.pricing import OptionQuoteRequest, OptionQuoteResponse
from app.services.market_data.frankfurter_client import get_rate
from app.services.pricing.option_pricer import price_option_quote

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.post("/options", response_model=OptionQuoteResponse)
async def quote_option(request: OptionQuoteRequest) -> OptionQuoteResponse:
    """Price an FX option at the live spot rate.

    The response premium is per unit of the base currency, expressed in the
    pair's quote currency (e.g. USD for EURUSD). ``total_premium`` is the full
    premium for ``notional_1`` in that same currency.
    """
    currency_2 = request.currency_pair.value[3:]
    try:
        spot, _ = await get_rate(request.currency_pair)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        priced = price_option_quote(
            request.option_type,
            spot=spot,
            strike_rate=request.strike_rate,
            expiry_date=request.expiry_date,
            vol=request.vol,
            valuation_date=date.today(),
            premium_currency=currency_2,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return OptionQuoteResponse(
        currency_pair=request.currency_pair.value,
        option_type=priced.option_type,
        premium=priced.premium,
        premium_currency=currency_2,
        total_premium=round(request.notional_1 * priced.premium, 2),
        spot=priced.spot,
        strike_rate=priced.strike_rate,
        expiry_date=priced.expiry_date,
        valuation_date=priced.valuation_date,
        tenor_years=priced.tenor_years,
        vol=priced.vol,
        greeks=priced.greeks,
    )
