import asyncio
from sqlalchemy import select, update
from app.database import async_session_factory
from app.modules.auth.models import UserEntity
from app.modules.auth.security import get_password_hash

async def update_admin_password():
    async with async_session_factory() as session:
        # 生成正确的密码哈希
        new_hash = get_password_hash("admin123")
        print(f"New password hash: {new_hash}")

        # 更新管理员密码
        await session.execute(
            update(UserEntity)
            .where(UserEntity.username == "admin")
            .values(hashed_password=new_hash)
        )
        await session.commit()

        # 验证更新
        result = await session.execute(
            select(UserEntity).where(UserEntity.username == "admin")
        )
        user = result.scalar_one()
        print(f"Updated user: {user.username}, hash: {user.hashed_password[:50]}...")

if __name__ == "__main__":
    asyncio.run(update_admin_password())
