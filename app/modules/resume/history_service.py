import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.resume.persistence_service import resume_persistence_service
from app.modules.resume.schemas import ResumeDetailDTO, ResumeListItemDTO

logger = logging.getLogger(__name__)


class ResumeHistoryService:
    async def get_resume_list(self, db: AsyncSession) -> list[ResumeListItemDTO]:
        entities = await resume_persistence_service.find_all(db)
        return [resume_persistence_service.to_list_item_dto(e) for e in entities]

    async def get_resume_detail(self, db: AsyncSession, resume_id: int) -> ResumeDetailDTO:
        entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id)
        return resume_persistence_service.to_detail_dto(entity)


resume_history_service = ResumeHistoryService()
