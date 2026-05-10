from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.knowledge_base.cross_kb_rag_service import cross_kb_rag_service
from app.modules.knowledge_base.schemas import AskKnowledgeBaseRequest, RagAnswerDTO, RagChatDTO, RagChatListItemDTO

router = APIRouter()


@router.post("/cross/chat", response_model=Result[RagAnswerDTO])
async def cross_kb_chat(
    request: AskKnowledgeBaseRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await cross_kb_rag_service.ask(
        db, user_id=user_id, question=request.question, top_k=request.top_k,
    )
    return Result.success(result)


@router.post("/cross/chat/stream")
async def cross_kb_chat_stream(
    request: AskKnowledgeBaseRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    generator = cross_kb_rag_service.stream_answer(
        db,
        user_id=user_id,
        question=request.question,
        session_id=request.session_id,
        top_k=request.top_k,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@router.get("/cross/chats", response_model=Result[list[RagChatListItemDTO]])
async def list_cross_kb_chats(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    items = await cross_kb_rag_service.list_chats(db, user_id)
    return Result.success(items)


@router.get("/cross/chat/history", response_model=Result[list[RagChatDTO]])
async def get_cross_kb_session_history(
    session_id: str = Query(..., min_length=1),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
    items = await knowledge_base_persistence_service.find_cross_kb_session_chat_dtos(db, user_id, session_id)
    return Result.success(items)


@router.delete("/cross/chats/{session_id}")
async def delete_cross_kb_session(
    session_id: str,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
    count = await knowledge_base_persistence_service.delete_cross_kb_session(db, user_id, session_id)
    return Result.success({"deleted": count})


@router.get("/cross/chat/retrieve")
async def cross_kb_retrieve(
    question: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(default=4, ge=1, le=20),
    use_vector: bool = Query(default=True),
    use_graph: bool = Query(default=True),
    use_rerank: bool = Query(default=True),
    graph_weight: float = Query(default=0.5, ge=0.0, le=1.0),
    scope_kb_id: int | None = Query(default=None),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """纯检索接口，供评估脚本使用。返回检索结果，不生成回答。"""
    references, latency_ms = await cross_kb_rag_service.retrieve_with_config(
        db,
        user_id=user_id,
        question=question,
        top_k=top_k,
        use_vector=use_vector,
        use_graph=use_graph,
        use_rerank=use_rerank,
        graph_weight=graph_weight,
        scope_kb_id=scope_kb_id,
    )
    return Result.success({
        "references": [r.model_dump() for r in references],
        "latency_ms": latency_ms,
    })
