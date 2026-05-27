import asyncio
import logging
import socket
from collections.abc import AsyncGenerator

from sqlalchemy import text
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


def init_engine():
    """延迟初始化数据库引擎（在应用启动时调用）"""
    global engine, async_session_factory

    import time

    max_retries = 5
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            logger.info("正在创建数据库引擎（尝试 %d/%d）", attempt + 1, max_retries)
            engine = create_async_engine(
                settings.database.dsn,
                echo=settings.debug,
                pool_size=20,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=3600,
                pool_pre_ping=True,
                connect_args={
                    "timeout": 5,
                    "command_timeout": 5,
                    "server_settings": {
                        "timezone": "Asia/Shanghai",
                    },
                },
            )
            logger.info("数据库引擎创建成功，连接池配置: pool_size=20, max_overflow=10, 总连接数=30")

            async_session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            return
        except Exception as e:
            logger.warning(f"数据库引擎创建失败（尝试 {attempt + 1}/{max_retries}）: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.error("数据库引擎创建最终失败")
                raise


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


def get_db_context():
    """返回数据库会话上下文管理器（用于 async with）"""
    if async_session_factory is None:
        raise RuntimeError("数据库不可用，请先启动 PostgreSQL")
    return async_session_factory()


async def init_db() -> None:
    if engine is None:
        logger.warning("数据库引擎未初始化，跳过表创建")
        return

    from app.models.base import Base
    from app.modules.agent_orchestration.models import (  # noqa: F401
        AgentCostLogEntity,
        AgentExecutionEntity,
        AgentExecutionStepEntity,
        AgentPerformanceEntity,
    )
    from app.modules.auth.models import UserEntity  # noqa: F401
    from app.modules.interview.models import InterviewAnswerEntity, InterviewSessionEntity  # noqa: F401
    from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity, RagChatEntity  # noqa: F401
    from app.modules.knowledge_graph.models import KnowledgeGraphEntity, KnowledgeTriple  # noqa: F401
    from app.modules.organization.models import OrganizationEntity, OrganizationMemberEntity  # noqa: F401
    from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity  # noqa: F401

    max_retries = 5
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            await asyncio.wait_for(
                _do_create_tables(Base),
                timeout=10,
            )
            logger.info("数据库表创建成功")
            return
        except asyncio.TimeoutError:
            logger.warning("数据库连接超时（10s），尝试 %d/%d", attempt + 1, max_retries)
        except Exception as e:
            logger.warning("数据库初始化失败（尝试 %d/%d）: %s", attempt + 1, max_retries, e)

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    logger.error("数据库初始化最终失败，已重试 %d 次", max_retries)


async def _do_create_tables(base) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(base.metadata.create_all)


async def close_db() -> None:
    if engine is not None:
        await engine.dispose()
