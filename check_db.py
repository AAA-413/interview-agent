import asyncio

from sqlalchemy import text

from app.database import async_session_factory, init_engine


async def check():
    init_engine()
    async with async_session_factory() as session:
        result = await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        tables = [r[0] for r in result.fetchall()]
        print("Tables:", tables)


asyncio.run(check())
