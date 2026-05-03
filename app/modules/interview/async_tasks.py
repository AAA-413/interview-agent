import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.base_async_task import StreamTaskHandler, StreamTaskProducer
from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService
from app.modules.interview.persistence_service import interview_persistence_service

logger = logging.getLogger(__name__)

EVALUATE_STREAM_KEY = "stream:interview:evaluate"
FIELD_SESSION_ID = "sessionId"


class EvaluateStreamProducer(StreamTaskProducer):
    def __init__(self, redis_service: RedisService):
        super().__init__(redis_service, EVALUATE_STREAM_KEY)

    async def send_evaluate_task(self, session_id: str) -> None:
        await self.send_task({FIELD_SESSION_ID: session_id}, maxlen=10000)


class InterviewEvaluateTaskHandler(StreamTaskHandler):
    @property
    def field_name(self) -> str:
        return FIELD_SESSION_ID

    async def update_status(
        self, db: AsyncSession, key_value: str, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        await interview_persistence_service.update_evaluate_status(db, key_value, status.value, error)

    async def process(self, db: AsyncSession, key_value: str) -> None:
        from app.modules.interview.session_service import interview_session_service

        await interview_session_service.evaluate_session(db, key_value)
        logger.info("面试评估完成: sessionId=%s", key_value)
