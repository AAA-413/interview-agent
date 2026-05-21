import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.common.base_async_task import StreamTaskHandler, StreamTaskProducer
from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService
from app.modules.resume.grading_service import resume_grading_service
from app.modules.resume.persistence_service import resume_persistence_service

logger = logging.getLogger(__name__)

RESUME_ANALYZE_STREAM_KEY = "resume:analyze:stream"
FIELD_RESUME_ID = "resumeId"


class AnalyzeStreamProducer(StreamTaskProducer):
    def __init__(self, redis_service: RedisService):
        super().__init__(redis_service, RESUME_ANALYZE_STREAM_KEY)

    async def send_analyze_task(self, resume_id: int) -> None:
        await self.send_task({FIELD_RESUME_ID: str(resume_id)})


class ResumeAnalyzeTaskHandler(StreamTaskHandler):
    @property
    def field_name(self) -> str:
        return FIELD_RESUME_ID

    async def update_status(
        self, db: AsyncSession, key_value: str, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        await resume_persistence_service.update_analyze_status(db, int(key_value), status, error)

    async def process(self, db: AsyncSession, key_value: str) -> None:
        resume_id = int(key_value)
        entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id)
        if not entity.resume_text:
            await resume_persistence_service.update_analyze_status(
                db, resume_id, AsyncTaskStatus.FAILED, "简历文本为空，无法分析"
            )
            return

        await resume_persistence_service.clear_analyses(db, resume_id)
        chat_model = llm_registry.default
        result = await resume_grading_service.analyze_resume(chat_model, entity.resume_text)
        await resume_persistence_service.save_analysis(db, resume_id, result)
        logger.info("简历分析完成: resumeId=%d, 总分=%d", resume_id, result.overall_score)
