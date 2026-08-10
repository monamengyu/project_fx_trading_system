from fastapi import APIRouter, HTTPException

from app.models.enums import CurrencyPair
from app.schemas.market_data import RateResponse
from app.services.market_data.frankfurter_client import get_rate

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/rates", response_model=RateResponse)
async def get_market_rate(pair: CurrencyPair) -> RateResponse:
    try:
        rate, as_of = await get_rate(pair)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RateResponse(pair=pair.value, rate=rate, as_of=as_of)
