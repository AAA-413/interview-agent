import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.result import Result
from app.database import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_graph.extraction_service import knowledge_graph_extraction_service
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service
from app.modules.knowledge_graph.schemas import (
    CreateTripleRequest,
    EntityDTO,
    EntityDetailDTO,
    ExtractResultDTO,
    GraphDataDTO,
    TripleDTO,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/entities", response_model=Result[dict])
async def list_entities(
    entity_type: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entities, total = await knowledge_graph_persistence_service.list_entities(
        db, entity_type=entity_type, keyword=keyword, page=page, size=size
    )
    items = [knowledge_graph_persistence_service.to_entity_dto(e) for e in entities]
    return Result.success({"items": [i.model_dump() for i in items], "total": total, "page": page, "size": size})


@router.get("/graph", response_model=Result[GraphDataDTO])
async def get_graph(
    kb_id: int | None = Query(default=None),
    entity_types: str | None = Query(default=None, description="逗号分隔的实体类型"),
    limit: int = Query(default=200, ge=1, le=1000),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    types_list = [t.strip() for t in entity_types.split(",") if t.strip()] if entity_types else None
    graph_data = await knowledge_graph_persistence_service.get_graph_data(
        db, kb_id=kb_id, entity_types=types_list, limit=limit
    )
    return Result.success(graph_data)


@router.get("/entity/{name}", response_model=Result[EntityDetailDTO])
async def get_entity_detail(
    name: str,
    depth: int = Query(default=2, ge=1, le=3),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await knowledge_graph_persistence_service.get_entity_detail(db, name, depth=depth)
    if not detail:
        return Result.error(f"实体 '{name}' 不存在", 404)
    return Result.success(detail)


@router.get("/triples", response_model=Result[list[TripleDTO]])
async def list_triples(
    entity: str | None = Query(default=None),
    predicate: str | None = Query(default=None),
    kb_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if entity:
        triples = await knowledge_graph_persistence_service.query_triples_by_entity(db, entity, kb_id)
    else:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.modules.knowledge_graph.models import KnowledgeTriple

        stmt = select(KnowledgeTriple).options(
            selectinload(KnowledgeTriple.subject_entity),
            selectinload(KnowledgeTriple.object_entity),
        )
        if predicate:
            stmt = stmt.where(KnowledgeTriple.predicate == predicate)
        if kb_id:
            stmt = stmt.where(KnowledgeTriple.source_kb_id == kb_id)
        stmt = stmt.offset((page - 1) * size).limit(size)
        result = await db.execute(stmt)
        triples = list(result.scalars().all())

    dtos = []
    for t in triples:
        dtos.append(TripleDTO(
            id=t.id,
            subject=EntityDTO(
                id=t.subject_entity.id,
                name=t.subject_entity.name,
                entity_type=t.subject_entity.entity_type,
                description=t.subject_entity.description,
                properties={},
                mention_count=t.subject_entity.mention_count,
            ),
            predicate=t.predicate,
            object=EntityDTO(
                id=t.object_entity.id,
                name=t.object_entity.name,
                entity_type=t.object_entity.entity_type,
                description=t.object_entity.description,
                properties={},
                mention_count=t.object_entity.mention_count,
            ),
            confidence=t.confidence,
            source_kb_id=t.source_kb_id,
        ))
    return Result.success(dtos)


@router.post("/triples", response_model=Result[TripleDTO])
async def create_triple(
    request: CreateTripleRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    subj = await knowledge_graph_persistence_service.find_or_create_entity(
        db, request.subject, request.subject_type
    )
    obj = await knowledge_graph_persistence_service.find_or_create_entity(
        db, request.object, request.object_type
    )
    triple = await knowledge_graph_persistence_service.create_triple(
        db, subject_id=subj.id, predicate=request.predicate, object_id=obj.id,
        source_kb_id=request.source_kb_id,
    )
    return Result.success(TripleDTO(
        id=triple.id,
        subject=knowledge_graph_persistence_service.to_entity_dto(subj),
        predicate=triple.predicate,
        object=knowledge_graph_persistence_service.to_entity_dto(obj),
        confidence=triple.confidence,
        source_kb_id=triple.source_kb_id,
    ))


@router.delete("/triples/{triple_id}", response_model=Result[None])
async def delete_triple(
    triple_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    deleted = await knowledge_graph_persistence_service.delete_triple(db, triple_id)
    if not deleted:
        return Result.error("三元组不存在", 404)
    return Result.success(None)


@router.post("/reextract/{kb_id}", response_model=Result[ExtractResultDTO])
async def reextract_knowledge_graph(
    kb_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entity = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id, user_id)
    if not entity.source_text:
        return Result.error("知识库文本为空，无法抽取", 400)

    result = await knowledge_graph_extraction_service.extract_and_save(db, kb_id, entity.source_text)
    return Result.success(ExtractResultDTO(**result))
