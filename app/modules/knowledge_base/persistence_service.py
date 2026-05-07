import json
import logging
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import BasePersistenceService, safe_json_loads
from app.common.error_code import ErrorCode
from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity, RagChatEntity, RagChatStatus
from app.modules.knowledge_base.schemas import (
    KnowledgeBaseDetailDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBaseReindexResponse,
    KnowledgeChunkDTO,
    RagChatDTO,
    RagChatListItemDTO,
    RagReferenceDTO,
)

logger = logging.getLogger(__name__)


class KnowledgeBasePersistenceService(BasePersistenceService[KnowledgeBaseEntity]):
    model = KnowledgeBaseEntity
    not_found_error = ErrorCode.KNOWLEDGE_BASE_NOT_FOUND

    async def find_by_file_hash(self, db: AsyncSession, file_hash: str) -> KnowledgeBaseEntity | None:
        result = await db.execute(select(KnowledgeBaseEntity).where(KnowledgeBaseEntity.file_hash == file_hash))
        return result.scalar_one_or_none()

    async def find_all(self, db: AsyncSession, user_id: int | None = None) -> list[KnowledgeBaseEntity]:
        query = select(KnowledgeBaseEntity).order_by(KnowledgeBaseEntity.created_at.desc())
        if user_id is not None:
            query = query.where(KnowledgeBaseEntity.user_id == user_id)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def delete(self, db: AsyncSession, kb_id: int, user_id: int | None = None) -> KnowledgeBaseEntity:
        entity = await self.find_by_id_or_throw(db, kb_id, user_id)
        await db.delete(entity)
        await db.flush()
        return entity

    async def clear_chunks(self, db: AsyncSession, kb_id: int) -> None:
        await db.execute(delete(KnowledgeChunkEntity).where(KnowledgeChunkEntity.knowledge_base_id == kb_id))
        await db.flush()

    async def clear_chats(self, db: AsyncSession, kb_id: int) -> None:
        await db.execute(delete(RagChatEntity).where(RagChatEntity.knowledge_base_id == kb_id))
        await db.flush()

    async def update_index_status(
        self, db: AsyncSession, kb_id: int, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        entity = await self.find_by_id(db, kb_id)
        if entity is None:
            return
        entity.index_status = status
        entity.index_error = error[:500] if error else None
        if status == AsyncTaskStatus.COMPLETED:
            entity.last_indexed_at = datetime.now()
        await db.flush()

    async def save_chunks(self, db: AsyncSession, kb_id: int, chunks: list[KnowledgeChunkEntity]) -> None:
        for chunk in chunks:
            chunk.knowledge_base_id = kb_id
            db.add(chunk)
        entity = await self.find_by_id_or_throw(db, kb_id)
        entity.chunk_count = len(chunks)
        entity.document_count = 1
        entity.last_indexed_at = datetime.now()
        await db.flush()

    async def create_chat(
        self,
        db: AsyncSession,
        *,
        kb_id: int,
        session_id: str,
        question: str,
        rewritten_query: str | None = None,
    ) -> RagChatEntity:
        entity = RagChatEntity(
            knowledge_base_id=kb_id,
            session_id=session_id,
            question=question,
            rewritten_query=rewritten_query,
            status=RagChatStatus.PENDING,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def complete_chat(
        self,
        db: AsyncSession,
        *,
        chat_id: int,
        rewritten_query: str,
        answer: str,
        references: list[dict],
    ) -> None:
        result = await db.execute(select(RagChatEntity).where(RagChatEntity.id == chat_id))
        entity = result.scalar_one_or_none()
        if entity is None:
            return
        entity.rewritten_query = rewritten_query
        entity.answer = answer
        entity.references_json = json.dumps(references, ensure_ascii=False)
        entity.status = RagChatStatus.COMPLETED
        entity.error_message = None
        await db.flush()

    async def fail_chat(self, db: AsyncSession, *, chat_id: int, error_message: str) -> None:
        result = await db.execute(select(RagChatEntity).where(RagChatEntity.id == chat_id))
        entity = result.scalar_one_or_none()
        if entity is None:
            return
        entity.status = RagChatStatus.FAILED
        entity.error_message = error_message[:500] if error_message else None
        await db.flush()

    async def find_recent_chats(self, db: AsyncSession, kb_id: int, limit: int = 10) -> list[RagChatEntity]:
        result = await db.execute(
            select(RagChatEntity)
            .where(RagChatEntity.knowledge_base_id == kb_id)
            .order_by(RagChatEntity.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_session_chats(self, db: AsyncSession, kb_id: int, session_id: str, limit: int = 5) -> list[RagChatEntity]:
        result = await db.execute(
            select(RagChatEntity)
            .where(RagChatEntity.knowledge_base_id == kb_id)
            .where(RagChatEntity.session_id == session_id)
            .where(RagChatEntity.status == RagChatStatus.COMPLETED)
            .order_by(RagChatEntity.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    def to_list_item_dto(self, entity: KnowledgeBaseEntity) -> KnowledgeBaseListItemDTO:
        return KnowledgeBaseListItemDTO(
            id=entity.id,
            name=entity.name,
            description=entity.description,
            filename=entity.original_filename,
            file_size=entity.file_size,
            chunk_count=entity.chunk_count,
            document_count=entity.document_count,
            index_status=entity.index_status,
            index_error=entity.index_error,
            last_indexed_at=entity.last_indexed_at,
            created_at=entity.created_at,
        )

    def to_detail_dto(self, entity: KnowledgeBaseEntity) -> KnowledgeBaseDetailDTO:
        chunks = [self._to_chunk_dto(chunk) for chunk in sorted(entity.chunks, key=lambda item: item.chunk_index)]
        chats = [self._to_chat_dto(chat) for chat in sorted(entity.chats, key=lambda item: item.created_at, reverse=True)[:10]]
        return KnowledgeBaseDetailDTO(
            id=entity.id,
            name=entity.name,
            description=entity.description,
            filename=entity.original_filename,
            file_size=entity.file_size,
            content_type=entity.content_type,
            storage_url=entity.storage_url,
            source_text=entity.source_text,
            chunk_count=entity.chunk_count,
            document_count=entity.document_count,
            index_status=entity.index_status,
            index_error=entity.index_error,
            last_indexed_at=entity.last_indexed_at,
            created_at=entity.created_at,
            chunks=chunks,
            recent_chats=chats,
        )

    def to_reindex_response(self, entity: KnowledgeBaseEntity) -> KnowledgeBaseReindexResponse:
        return KnowledgeBaseReindexResponse(
            id=entity.id,
            index_status=entity.index_status,
            index_error=entity.index_error,
        )

    def to_chat_list_item(self, entity: RagChatEntity) -> RagChatListItemDTO:
        return RagChatListItemDTO(
            id=entity.id,
            session_id=entity.session_id,
            question=entity.question,
            status=entity.status,
            created_at=entity.created_at,
        )

    @staticmethod
    def _to_chunk_dto(entity: KnowledgeChunkEntity) -> KnowledgeChunkDTO:
        metadata = safe_json_loads(entity.metadata_json, {})
        return KnowledgeChunkDTO(
            id=entity.id,
            chunk_index=entity.chunk_index,
            title=entity.title,
            content=entity.content,
            content_preview=entity.content_preview,
            metadata=metadata,
        )

    @staticmethod
    def _to_chat_dto(entity: RagChatEntity) -> RagChatDTO:
        raw_refs = safe_json_loads(entity.references_json, [])
        references = [RagReferenceDTO(**item) for item in raw_refs] if raw_refs else []
        return RagChatDTO(
            id=entity.id,
            session_id=entity.session_id,
            question=entity.question,
            rewritten_query=entity.rewritten_query,
            answer=entity.answer,
            references=references,
            status=entity.status,
            error_message=entity.error_message,
            created_at=entity.created_at,
        )


knowledge_base_persistence_service = KnowledgeBasePersistenceService()
