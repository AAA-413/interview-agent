"""
执行用户表迁移
"""

import asyncio
import logging

import asyncpg

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_migration():
    """执行迁移"""
    # 连接数据库
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="postgres",
        password="password",
        database="interview_guide",
    )

    try:
        # 读取迁移脚本
        with open("migrations/004_users.sql", "r", encoding="utf-8") as f:
            sql = f.read()

        # 执行迁移
        logger.info("开始执行用户表迁移...")
        await conn.execute(sql)
        logger.info("✅ 用户表迁移成功")

        # 验证表是否创建
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'users'"
        )
        logger.info(f"验证: users 表存在 = {result == 1}")

        # 查询默认管理员
        admin = await conn.fetchrow("SELECT * FROM users WHERE username = 'admin'")
        if admin:
            logger.info(f"✅ 默认管理员账号已创建: {admin['username']} ({admin['email']})")
        else:
            logger.warning("⚠️ 默认管理员账号未创建")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migration())
