from fastapi import APIRouter

from app.api.routers import market_data, nl_parse, positions, trades, ws

api_router = APIRouter()
api_router.include_router(trades.router)
api_router.include_router(market_data.router)
api_router.include_router(positions.router)
api_router.include_router(ws.router)
api_router.include_router(nl_parse.router)
