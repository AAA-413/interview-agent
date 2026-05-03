import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.file.file_storage_service import file_storage_service
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.schemas import KnowledgeBaseDetailDTO, KnowledgeBaseListItemDTO

logger = logging.getLogger(__name__)


class KnowledgeBaseHistoryService:
    async def get_list(self, db: AsyncSession, user_id: int) -> list[KnowledgeBaseListItemDTO]:
        entities = await knowledge_base_persistence_service.find_all(db, user_id=user_id)
        return [knowledge_base_persistence_service.to_list_item_dto(entity) for entity in entities]

    async def get_detail(self, db: AsyncSession, kb_id: int, user_id: int) -> KnowledgeBaseDetailDTO:
        entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
        return knowledge_base_persistence_service.to_detail_dto(entity)


class KnowledgeBaseDeleteService:
    async def delete(self, db: AsyncSession, kb_id: int, user_id: int = 0) -> None:
        entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
        storage_key = entity.storage_key
        await knowledge_base_persistence_service.delete(db, kb_id, user_id)
        if storage_key:
            await file_storage_service.delete_file(storage_key)


knowledge_base_history_service = KnowledgeBaseHistoryService()
knowledge_base_delete_service = KnowledgeBaseDeleteService()
