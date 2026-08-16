import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import api_router
from app.api.routers.ws import stream_rates
from app.core.config import settings
from app.db.session import get_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # background task that pushes live market rates to WebSocket subscribers
    stream_task = asyncio.create_task(stream_rates())
    yield
    stream_task.cancel()


# create the backend application, with the API represented by the object app
app = FastAPI(title=settings.app_name, lifespan=lifespan)

# allow the React frontend (Vite dev server on :3000) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    return {"db_status": "ok", "result": result.scalar()}