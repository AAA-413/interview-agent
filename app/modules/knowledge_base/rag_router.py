from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.knowledge_base.rag_service import knowledge_base_rag_service
from app.modules.knowledge_base.schemas import AskKnowledgeBaseRequest, RagAnswerDTO, RagChatListItemDTO

router = APIRouter()


@router.post("/{kb_id}/chat", response_model=Result[RagAnswerDTO])
async def ask_knowledge_base(kb_id: int, request: AskKnowledgeBaseRequest, db: AsyncSession = Depends(get_db)):
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
    db: AsyncSession = Depends(get_db),
):
    generator = knowledge_base_rag_service.stream_answer(
        db,
        kb_id=kb_id,
        question=request.question,
        session_id=request.session_id,
        top_k=request.top_k,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/{kb_id}/chats", response_model=Result[list[RagChatListItemDTO]])
async def list_knowledge_base_chats(kb_id: int, db: AsyncSession = Depends(get_db)):
    items = await knowledge_base_rag_service.list_chats(db, kb_id)
    return Result.success(items)
