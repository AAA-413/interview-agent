import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.knowledge_base.history_service import knowledge_base_delete_service, knowledge_base_history_service
from app.modules.knowledge_base.schemas import (
    FetchDocumentRequest,
    KnowledgeBaseDetailDTO,
    KnowledgeBaseListItemDTO,
    KnowledgeBaseReindexResponse,
)
from app.modules.knowledge_base.upload_service import knowledge_base_upload_service
from app.modules.knowledge_base.fetch_service import knowledge_base_fetch_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=Result[list[KnowledgeBaseListItemDTO]])
async def list_knowledge_bases(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items = await knowledge_base_history_service.get_list(db, user_id)
    return Result.success(items)


@router.get("/{kb_id}", response_model=Result[KnowledgeBaseDetailDTO])
async def get_knowledge_base(
    kb_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await knowledge_base_history_service.get_detail(db, kb_id, user_id)
    return Result.success(detail)


@router.post("", response_model=Result[KnowledgeBaseDetailDTO])
async def create_knowledge_base(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    entity = await knowledge_base_upload_service.upload(
        db,
        file_bytes=file_bytes,
        filename=file.filename or "unknown",
        content_type=file.content_type,
        name=name,
        description=description,
        user_id=user_id,
    )
    detail = await knowledge_base_history_service.get_detail(db, entity.id, user_id)
    return Result.success(detail)


@router.post("/fetch", response_model=Result[KnowledgeBaseDetailDTO])
async def fetch_document(
    request: FetchDocumentRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """从 URL 抓取文档并创建知识库"""
    logger.info(f"收到文档抓取请求: url={request.url}")
    entity = await knowledge_base_fetch_service.fetch_and_create(
        db,
        url=str(request.url),
        name=request.name,
        description=request.description,
        max_length=request.max_length,
        user_id=user_id,
    )
    detail = await knowledge_base_history_service.get_detail(db, entity.id, user_id)
    return Result.success(detail)


@router.post("/{kb_id}/reindex", response_model=Result[KnowledgeBaseReindexResponse])
async def reindex_knowledge_base(
    kb_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entity = await knowledge_base_upload_service.reindex(db, kb_id, user_id)
    return Result.success(KnowledgeBaseReindexResponse(id=entity.id, index_status=entity.index_status, index_error=entity.index_error))


@router.delete("/{kb_id}", response_model=Result[None])
async def delete_knowledge_base(
    kb_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_delete_service.delete(db, kb_id, user_id)
    return Result.success(None)
