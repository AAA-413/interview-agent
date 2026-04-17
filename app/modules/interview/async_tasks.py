import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService
from app.modules.interview.persistence_service import interview_persistence_service

logger = logging.getLogger(__name__)

EVALUATE_STREAM_KEY = "stream:interview:evaluate"
FIELD_SESSION_ID = "sessionId"


class EvaluateStreamProducer:
    def __init__(self, redis_service: RedisService):
        self._redis = redis_service

    async def send_evaluate_task(self, session_id: str) -> None:
        try:
            fields = {FIELD_SESSION_ID: session_id}
            await self._redis.xadd(EVALUATE_STREAM_KEY, fields, maxlen=10000)
            logger.info("已发送评估任务: sessionId=%s", session_id)
        except Exception as e:
            logger.error("发送评估任务失败: sessionId=%s, error=%s", session_id, e)
            raise


class InterviewEvaluateTaskHandler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def handle(self, fields: dict[str, str]) -> None:
        session_id = fields.get(FIELD_SESSION_ID)
        if not session_id:
            logger.warning("忽略无效评估任务，缺少 sessionId: %s", fields)
            return

        async with self._session_factory() as db:
            try:
                await interview_persistence_service.update_evaluate_status(db, session_id, AsyncTaskStatus.PROCESSING.value, None)
                from app.modules.interview.session_service import interview_session_service

                await interview_session_service.evaluate_session(db, session_id)
                await interview_persistence_service.update_evaluate_status(db, session_id, AsyncTaskStatus.COMPLETED.value, None)
                await db.commit()
                logger.info("面试评估完成: sessionId=%s", session_id)
            except Exception as e:
                await db.rollback()
                logger.error("面试评估失败: sessionId=%s, error=%s", session_id, e)
                async with self._session_factory() as failed_db:
                    await interview_persistence_service.update_evaluate_status(
                        failed_db, session_id, AsyncTaskStatus.FAILED.value, str(e)
                    )
                    await failed_db.commit()
