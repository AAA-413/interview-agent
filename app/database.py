import asyncio
import logging
import socket
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)


def _check_port_open(host: str, port: int, timeout: float = 2) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


engine = None
async_session_factory = None

_db_available = _check_port_open(settings.database.host, settings.database.port)

if _db_available:
    engine = create_async_engine(
        settings.database.dsn,
        echo=settings.debug,
        pool_size=20,              # 常驻连接数（从 10 增加到 20）
        max_overflow=10,           # 最大溢出连接数（从 20 减少到 10，总连接数 30）
        pool_timeout=30,           # 获取连接超时（秒）
        pool_recycle=3600,         # 连接回收时间（秒）
        pool_pre_ping=True,        # 连接前检测是否有效
        connect_args={
            "timeout": 5,
            "command_timeout": 5,
        },
    )
    logger.info("数据库连接池配置: pool_size=20, max_overflow=10, 总连接数=30")
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
else:
    logger.warning("PostgreSQL (%s:%s) 不可用，数据库功能将被禁用", settings.database.host, settings.database.port)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if async_session_factory is None:
        logger.error("数据库不可用，async_session_factory 为 None")
        raise RuntimeError("数据库不可用，请先启动 PostgreSQL")
    try:
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("获取数据库会话失败: %s", e)
        raise


async def init_db() -> None:
    if not _db_available or engine is None:
        logger.warning("数据库不可用，跳过表创建")
        return

    from app.models.base import Base
    from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity  # noqa: F401
    from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity  # noqa: F401
    from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity, RagChatEntity  # noqa: F401

    try:
        await asyncio.wait_for(
            _do_create_tables(Base),
            timeout=10,
        )
        logger.info("数据库表创建成功")
    except asyncio.TimeoutError:
        logger.warning("数据库连接超时（10s），跳过表创建")
    except Exception as e:
        logger.warning("数据库初始化失败: %s", e)


async def _do_create_tables(base) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)


async def close_db() -> None:
    if engine is not None:
        await engine.dispose()
