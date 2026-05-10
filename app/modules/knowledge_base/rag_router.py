from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.rag_service import knowledge_base_rag_service
from app.modules.knowledge_base.schemas import AskKnowledgeBaseRequest, RagAnswerDTO, RagChatDTO, RagChatListItemDTO

router = APIRouter()


@router.post("/{kb_id}/chat", response_model=Result[RagAnswerDTO])
async def ask_knowledge_base(
    kb_id: int,
    request: AskKnowledgeBaseRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    result = await knowledge_base_rag_service.ask(
        db,
        kb_id=kb_id,
        question=request.question,
        session_id=request.session_id,
        top_k=request.top_k,
    )
    return Result.success(result)


@router.post("/{kb_id}/chat/stream")
async def stream_knowledge_base_answer(
    kb_id: int,
    request: AskKnowledgeBaseRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    generator = knowledge_base_rag_service.stream_answer(
        db,
        kb_id=kb_id,
        question=request.question,
        session_id=request.session_id,
        top_k=request.top_k,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/{kb_id}/chats", response_model=Result[list[RagChatListItemDTO]])
async def list_knowledge_base_chats(
    kb_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    items = await knowledge_base_rag_service.list_chats(db, kb_id)
    return Result.success(items)


@router.get("/{kb_id}/chat/history", response_model=Result[list[RagChatDTO]])
async def get_knowledge_base_session_history(
    kb_id: int,
    session_id: str = Query(..., min_length=1),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    items = await knowledge_base_persistence_service.find_kb_session_chat_dtos(db, kb_id, session_id)
    return Result.success(items)


@router.delete("/{kb_id}/chats/{session_id}")
async def delete_knowledge_base_session(
    kb_id: int,
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    count = await knowledge_base_persistence_service.delete_kb_session(db, kb_id, session_id)
    return Result.success({"deleted": count})
