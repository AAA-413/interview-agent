import asyncio
from sqlalchemy import select
from app.database import async_session_factory
from app.modules.auth.models import UserEntity

async def check_users():
    async with async_session_factory() as session:
        result = await session.execute(select(UserEntity))
        users = result.scalars().all()

        print(f"Total users: {len(users)}")
        for user in users:
            print(f"ID: {user.id}, Username: {user.username}, Email: {user.email}, Superuser: {user.is_superuser}")
            print(f"Password hash: {user.hashed_password[:50]}...")

if __name__ == "__main__":
    asyncio.run(check_users())
