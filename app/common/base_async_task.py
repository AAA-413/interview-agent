import asyncio
import logging
from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService

logger = logging.getLogger(__name__)

TASK_TIMEOUT_SECONDS = 300  # 5 分钟超时


class StreamTaskProducer:
    """通用 Redis Stream 任务生产者。"""

    def __init__(self, redis_service: RedisService, stream_key: str):
        self._redis = redis_service
        self._stream_key = stream_key

    async def send_task(self, fields: dict[str, str], maxlen: int = 1000) -> None:
        try:
            await self._redis.xadd(self._stream_key, fields, maxlen=maxlen)
            logger.info("已发送任务: stream=%s, fields=%s", self._stream_key, fields)
        except Exception as e:
            logger.error("发送任务失败: stream=%s, error=%s", self._stream_key, e)
            raise


class StreamTaskHandler(ABC):
    """通用 Redis Stream 任务处理器基类。

    子类需要实现:
        field_name: 消息中的主键字段名
        process(): 实际业务处理逻辑
        update_status(): 更新任务状态的方法
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @property
    @abstractmethod
    def field_name(self) -> str:
        """消息中标识任务的字段名，如 'resumeId'、'sessionId'。"""

    @abstractmethod
    async def process(self, db: AsyncSession, key_value: str) -> None:
        """实际业务处理逻辑，在单个事务中执行。"""

    @abstractmethod
    async def update_status(
        self, db: AsyncSession, key_value: str, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        """更新任务状态。"""

    async def handle(self, fields: dict[str, str]) -> None:
        raw = fields.get(self.field_name)
        if not raw:
            logger.warning("忽略无效任务，缺少 %s: %s", self.field_name, fields)
            return

        async with self._session_factory() as db:
            try:
                await self.update_status(db, raw, AsyncTaskStatus.PROCESSING)
                await asyncio.wait_for(self.process(db, raw), timeout=TASK_TIMEOUT_SECONDS)
                await self.update_status(db, raw, AsyncTaskStatus.COMPLETED)
                await db.commit()
                logger.info("任务处理完成: %s=%s", self.field_name, raw)
            except asyncio.TimeoutError:
                await db.rollback()
                error_msg = f"任务处理超时（{TASK_TIMEOUT_SECONDS}秒）"
                logger.error("任务超时: %s=%s", self.field_name, raw)
                async with self._session_factory() as failed_db:
                    await self.update_status(failed_db, raw, AsyncTaskStatus.FAILED, error_msg)
                    await failed_db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("任务处理失败: %s=%s, error=%s", self.field_name, raw, e)
                async with self._session_factory() as failed_db:
                    await self.update_status(failed_db, raw, AsyncTaskStatus.FAILED, str(e))
                    await failed_db.commit()
