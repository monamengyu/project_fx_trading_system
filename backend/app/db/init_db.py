import asyncio

from app.db.base import Base
from app.db.session import engine
from app.models import trade, trade_state  # noqa: F401 (ensures models are registered)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created:", list(Base.metadata.tables.keys()))


if __name__ == "__main__":
    asyncio.run(init_db())