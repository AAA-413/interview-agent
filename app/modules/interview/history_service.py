import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.interview.persistence_service import interview_persistence_service
from app.modules.interview.schemas import InterviewDetailDTO

logger = logging.getLogger(__name__)


class InterviewHistoryService:
    async def get_interview_detail(self, db: AsyncSession, session_id: str, user_id: int = 0) -> InterviewDetailDTO:
        entity = await interview_persistence_service.find_by_session_id_or_throw(db, session_id, user_id)
        return interview_persistence_service.to_detail_dto(entity)

    async def export_interview_pdf(self, db: AsyncSession, session_id: str, user_id: int = 0) -> bytes:
        detail = await self.get_interview_detail(db, session_id, user_id)
        from app.infrastructure.export.pdf_export_service import pdf_export_service

        return await pdf_export_service.export_interview_pdf(detail)


interview_history_service = InterviewHistoryService()
