import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_INDEX_STREAM_KEY = "knowledge_base:index:stream"
FIELD_KNOWLEDGE_BASE_ID = "knowledgeBaseId"


class KnowledgeBaseIndexStreamProducer:
    def __init__(self, redis_service: RedisService):
        self._redis = redis_service

    async def send_index_task(self, knowledge_base_id: int) -> None:
        message = {FIELD_KNOWLEDGE_BASE_ID: str(knowledge_base_id)}
        await self._redis.xadd(KNOWLEDGE_BASE_INDEX_STREAM_KEY, message, maxlen=1000)
        logger.info("已发送知识库索引任务: knowledgeBaseId=%d", knowledge_base_id)


class KnowledgeBaseIndexTaskHandler:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def handle(self, fields: dict[str, str]) -> None:
        kb_id_raw = fields.get(FIELD_KNOWLEDGE_BASE_ID)
        if not kb_id_raw:
            logger.warning("忽略无效知识库索引任务，缺少 knowledgeBaseId: %s", fields)
            return

        kb_id = int(kb_id_raw)
        async with self._session_factory() as db:
            try:
                entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id)
                if not entity.source_text:
                    await knowledge_base_persistence_service.update_index_status(
                        db, kb_id, AsyncTaskStatus.FAILED, "知识库文本为空，无法建立索引"
                    )
                    await db.commit()
                    return

                await knowledge_base_persistence_service.update_index_status(db, kb_id, AsyncTaskStatus.PROCESSING, None)
                await knowledge_base_persistence_service.clear_chunks(db, kb_id)
                chunks = knowledge_base_vector_service.split_text(entity.source_text)
                if not chunks:
                    await knowledge_base_persistence_service.update_index_status(
                        db, kb_id, AsyncTaskStatus.FAILED, "未生成任何文本分块"
                    )
                    await db.commit()
                    return

                chunk_entities = knowledge_base_vector_service.to_entities(chunks)
                await knowledge_base_persistence_service.save_chunks(db, kb_id, chunk_entities)
                await knowledge_base_persistence_service.update_index_status(db, kb_id, AsyncTaskStatus.COMPLETED, None)
                await db.commit()
                logger.info("知识库索引完成: knowledgeBaseId=%d, chunks=%d", kb_id, len(chunk_entities))
            except Exception as e:
                await db.rollback()
                logger.exception("知识库索引失败: knowledgeBaseId=%d", kb_id)
                async with self._session_factory() as failed_db:
                    await knowledge_base_persistence_service.update_index_status(
                        failed_db, kb_id, AsyncTaskStatus.FAILED, f"索引失败: {e}"
                    )
                    await failed_db.commit()
