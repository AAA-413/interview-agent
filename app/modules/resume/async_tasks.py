import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.model import AsyncTaskStatus
from app.common.ai.llm_provider import llm_registry
from app.infrastructure.redis.redis_service import RedisService
from app.modules.resume.grading_service import resume_grading_service
from app.modules.resume.persistence_service import resume_persistence_service

logger = logging.getLogger(__name__)

RESUME_ANALYZE_STREAM_KEY = "resume:analyze:stream"
FIELD_RESUME_ID = "resumeId"


class AnalyzeStreamProducer:
    def __init__(self, redis_service: RedisService):
        self._redis = redis_service

    async def send_analyze_task(self, resume_id: int) -> None:
        try:
            message = {FIELD_RESUME_ID: str(resume_id)}
            await self._redis.xadd(RESUME_ANALYZE_STREAM_KEY, message, maxlen=1000)
            logger.info("已发送分析任务: resumeId=%d", resume_id)
        except Exception as e:
            logger.error("发送分析任务失败: resumeId=%d, error=%s", resume_id, str(e))
            raise


class ResumeAnalyzeTaskHandler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def handle(self, fields: dict[str, str]) -> None:
        resume_id_raw = fields.get(FIELD_RESUME_ID)
        if not resume_id_raw:
            logger.warning("忽略无效简历分析任务，缺少 resumeId: %s", fields)
            return

        resume_id = int(resume_id_raw)
        async with self._session_factory() as db:
            try:
                entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id)
                if not entity.resume_text:
                    await resume_persistence_service.update_analyze_status(
                        db, resume_id, AsyncTaskStatus.FAILED, "简历文本为空，无法分析"
                    )
                    await db.commit()
                    return

                await resume_persistence_service.clear_analyses(db, resume_id)
                await resume_persistence_service.update_analyze_status(db, resume_id, AsyncTaskStatus.PROCESSING)
                chat_model = llm_registry.default
                result = await resume_grading_service.analyze_resume(chat_model, entity.resume_text)
                await resume_persistence_service.save_analysis(db, resume_id, result)
                await resume_persistence_service.update_analyze_status(db, resume_id, AsyncTaskStatus.COMPLETED)
                await db.commit()
                logger.info("简历分析完成: resumeId=%d, 总分=%d", resume_id, result.overall_score)
            except Exception as e:
                await db.rollback()
                logger.error("简历分析失败: resumeId=%d, error=%s", resume_id, str(e))
                async with self._session_factory() as failed_db:
                    await resume_persistence_service.update_analyze_status(
                        failed_db, resume_id, AsyncTaskStatus.FAILED, f"分析失败: {e}"
                    )
                    await failed_db.commit()
