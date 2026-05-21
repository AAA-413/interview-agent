import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_async_task import StreamTaskHandler, StreamTaskProducer
from app.common.model import AsyncTaskStatus
from app.infrastructure.redis.redis_service import RedisService
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_INDEX_STREAM_KEY = "knowledge_base:index:stream"
FIELD_KNOWLEDGE_BASE_ID = "knowledgeBaseId"


class KnowledgeBaseIndexStreamProducer(StreamTaskProducer):
    def __init__(self, redis_service: RedisService):
        super().__init__(redis_service, KNOWLEDGE_BASE_INDEX_STREAM_KEY)

    async def send_index_task(self, knowledge_base_id: int) -> None:
        await self.send_task({FIELD_KNOWLEDGE_BASE_ID: str(knowledge_base_id)})


class KnowledgeBaseIndexTaskHandler(StreamTaskHandler):
    @property
    def field_name(self) -> str:
        return FIELD_KNOWLEDGE_BASE_ID

    async def update_status(
        self, db: AsyncSession, key_value: str, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        await knowledge_base_persistence_service.update_index_status(db, int(key_value), status, error)

    async def process(self, db: AsyncSession, key_value: str) -> None:
        kb_id = int(key_value)
        entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id)
        if not entity.source_text:
            await knowledge_base_persistence_service.update_index_status(
                db, kb_id, AsyncTaskStatus.FAILED, "知识库文本为空，无法建立索引"
            )
            return

        await knowledge_base_persistence_service.clear_chunks(db, kb_id)
        chunks = knowledge_base_vector_service.split_text(entity.source_text)
        if not chunks:
            await knowledge_base_persistence_service.update_index_status(
                db, kb_id, AsyncTaskStatus.FAILED, "未生成任何文本分块"
            )
            return

        chunk_entities = knowledge_base_vector_service.to_entities(chunks)
        await knowledge_base_persistence_service.save_chunks(db, kb_id, chunk_entities)
        logger.info("知识库索引完成: knowledgeBaseId=%d, chunks=%d", kb_id, len(chunk_entities))

        # 知识图谱抽取（失败不影响主流程）
        try:
            from app.modules.knowledge_graph.extraction_service import knowledge_graph_extraction_service

            await knowledge_graph_extraction_service.extract_and_save(
                db, kb_id, entity.source_text, chunks=chunk_entities
            )
            logger.info("知识图谱抽取完成: knowledgeBaseId=%d", kb_id)
        except Exception as e:
            logger.warning("知识图谱抽取失败（不影响主索引）: knowledgeBaseId=%d, error=%s", kb_id, e)
