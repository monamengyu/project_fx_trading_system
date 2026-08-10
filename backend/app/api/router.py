from fastapi import APIRouter

from app.api.routers import market_data, trades

api_router = APIRouter()
api_router.include_router(trades.router)
api_router.include_router(market_data.router)
