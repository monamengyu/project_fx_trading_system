from fastapi import APIRouter

from app.api.routers import trades

api_router = APIRouter()
api_router.include_router(trades.router)
