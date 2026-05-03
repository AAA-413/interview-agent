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
from app.modules.knowledge_base.async_tasks import KnowledgeBaseIndexStreamProducer
from app.modules.knowledge_base.models import KnowledgeBaseEntity
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service

logger = logging.getLogger(__name__)


class KnowledgeBaseUploadService:
    async def upload(
        self,
        db: AsyncSession,
        *,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        name: str | None,
        description: str | None,
        user_id: int = 0,
    ) -> KnowledgeBaseEntity:
        safe_filename = file_validation_service.validate_file(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            max_size=settings.resume.max_file_size,
            allowed_types=settings.resume.allowed_types,
            file_type_name="知识库文档",
        )

        file_hash = file_hash_service.calculate_hash(file_bytes)
        existing = await knowledge_base_persistence_service.find_by_file_hash(db, file_hash)
        if existing:
            logger.info("知识库文档已存在(哈希去重): id=%d", existing.id)
            return existing

        storage_key, storage_url = await file_storage_service.upload_knowledge_base(file_bytes, safe_filename, content_type)
        source_text = await document_parse_service.parse_content(file_bytes, filename)

        entity = KnowledgeBaseEntity(
            user_id=user_id,
            name=(name or safe_filename).strip() or safe_filename,
            description=description,
            file_hash=file_hash,
            original_filename=safe_filename,
            file_size=len(file_bytes),
            content_type=content_type,
            storage_key=storage_key,
            storage_url=storage_url,
            source_text=source_text,
            index_status=AsyncTaskStatus.PENDING,
        )
        entity = await knowledge_base_persistence_service.save(db, entity)

        if source_text:
            await self._enqueue_index(entity.id)
        else:
            await knowledge_base_persistence_service.update_index_status(
                db, entity.id, AsyncTaskStatus.FAILED, "文档解析结果为空"
            )
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED, "文档解析结果为空")

        return entity

    async def reindex(self, db: AsyncSession, kb_id: int, user_id: int = 0) -> KnowledgeBaseEntity:
        entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
        if not entity.source_text:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_UPLOAD_FAILED, "知识库文本为空，无法重新索引")
        await knowledge_base_persistence_service.update_index_status(db, kb_id, AsyncTaskStatus.PENDING, None)
        await knowledge_base_persistence_service.clear_chunks(db, kb_id)
        entity.chunk_count = 0
        await db.flush()
        await self._enqueue_index(kb_id)
        return entity

    @staticmethod
    async def _enqueue_index(kb_id: int) -> None:
        redis = await get_redis()
        producer = KnowledgeBaseIndexStreamProducer(RedisService(redis))
        await producer.send_index_task(kb_id)


knowledge_base_upload_service = KnowledgeBaseUploadService()
