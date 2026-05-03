import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.file.file_storage_service import file_storage_service
from app.modules.resume.persistence_service import resume_persistence_service

logger = logging.getLogger(__name__)


class ResumeDeleteService:
    async def delete_resume(self, db: AsyncSession, resume_id: int, user_id: int = 0) -> None:
        logger.info("收到删除简历请求: id=%d", resume_id)

        entity = await resume_persistence_service.find_by_id_or_throw(db, resume_id, user_id)

        if entity.storage_key:
            try:
                await file_storage_service.delete_file(entity.storage_key)
            except Exception as e:
                logger.warning("删除存储文件失败，继续删除数据库记录: %s", str(e))

        await resume_persistence_service.delete_resume(db, resume_id)
        logger.info("简历删除完成: id=%d", resume_id)


resume_delete_service = ResumeDeleteService()
