import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.model import AsyncTaskStatus
from app.config import settings
from app.infrastructure.file.document_parse_service import document_parse_service
from app.infrastructure.file.file_hash_service import file_hash_service
from app.infrastructure.file.file_storage_service import file_storage_service
from app.infrastructure.file.file_validation_service import file_validation_service
from app.infrastructure.redis.redis_service import RedisService, get_redis
from app.modules.resume.async_tasks import AnalyzeStreamProducer
from app.modules.resume.models import ResumeEntity
from app.modules.resume.persistence_service import resume_persistence_service

logger = logging.getLogger(__name__)


class ResumeUploadService:
    async def upload(self, db: AsyncSession, file_bytes: bytes, filename: str, content_type: str | None, user_id: int = 0) -> ResumeEntity:
        safe_filename = file_validation_service.validate_file(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            max_size=settings.resume.max_file_size,
            allowed_types=settings.resume.allowed_types,
            file_type_name="简历",
        )

        file_hash = file_hash_service.calculate_hash(file_bytes)

        existing = await resume_persistence_service.find_by_file_hash(db, file_hash)
        if existing:
            existing.increment_access_count()
            await db.flush()
            logger.info("简历已存在(哈希去重): id=%d", existing.id)
            return existing

        storage_key, storage_url = await file_storage_service.upload_resume(file_bytes, safe_filename, content_type)
        resume_text = await document_parse_service.parse_content(file_bytes, filename)

        entity = ResumeEntity(
            user_id=user_id,
            file_hash=file_hash,
            original_filename=safe_filename,
            file_size=len(file_bytes),
            content_type=content_type,
            storage_key=storage_key,
            storage_url=storage_url,
            resume_text=resume_text,
            analyze_status=AsyncTaskStatus.PENDING,
        )

        entity = await resume_persistence_service.save_resume(db, entity)

        if not resume_text:
            await resume_persistence_service.update_analyze_status(db, entity.id, AsyncTaskStatus.FAILED, "简历解析结果为空")

        return entity

    async def reanalyze(self, db: AsyncSession, resume_id: int, user_id: int = 0) -> None:
        entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id, user_id)

        if not entity.resume_text:
            raise BusinessException(ErrorCode.RESUME_PARSE_FAILED, "简历文本为空，无法重新分析")

        await resume_persistence_service.update_analyze_status(db, resume_id, AsyncTaskStatus.PENDING, None)
        await self._enqueue_analysis(resume_id)

    @staticmethod
    async def _enqueue_analysis(resume_id: int) -> None:
        redis = await get_redis()
        producer = AnalyzeStreamProducer(RedisService(redis))
        await producer.send_analyze_task(resume_id)


resume_upload_service = ResumeUploadService()
