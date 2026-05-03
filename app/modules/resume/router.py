import logging
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.infrastructure.export.pdf_export_service import pdf_export_service
from app.modules.auth.dependencies import get_current_user_id
from app.modules.resume.delete_service import resume_delete_service
from app.modules.resume.history_service import resume_history_service
from app.modules.resume.schemas import ResumeDetailDTO, ResumeListItemDTO
from app.modules.resume.upload_service import resume_upload_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=Result[list[ResumeListItemDTO]])
async def list_resumes(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items = await resume_history_service.get_resume_list(db, user_id)
    return Result.success(items)


@router.get("/{resume_id}", response_model=Result[ResumeDetailDTO])
async def get_resume(
    resume_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await resume_history_service.get_resume_detail(db, resume_id, user_id)
    return Result.success(detail)


@router.post("", response_model=Result[ResumeDetailDTO])
async def upload_resume(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    entity = await resume_upload_service.upload(db, file_bytes, file.filename or "unknown", file.content_type, user_id)
    detail = await resume_history_service.get_resume_detail(db, entity.id, user_id)
    return Result.success(detail)


@router.delete("/{resume_id}", response_model=Result[None])
async def delete_resume(
    resume_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await resume_delete_service.delete_resume(db, resume_id, user_id)
    return Result.success(None)


@router.post("/{resume_id}/reanalyze", response_model=Result[None])
async def reanalyze_resume(
    resume_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await resume_upload_service.reanalyze(db, resume_id, user_id)
    return Result.success(None)


@router.get("/{resume_id}/export-pdf")
async def export_resume_pdf(
    resume_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await resume_history_service.get_resume_detail(db, resume_id, user_id)
    pdf_bytes = await pdf_export_service.export_resume_analysis_pdf(detail)
    filename = f"resume-analysis-{resume_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
