import json
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.knowledge_graph.models import KnowledgeGraphEntity, KnowledgeTriple
from app.modules.knowledge_graph.schemas import (
    EntityDetailDTO,
    EntityDTO,
    GraphDataDTO,
    GraphEdgeDTO,
    GraphNodeDTO,
    GraphStatsDTO,
    TripleDTO,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphPersistenceService:
    async def find_or_create_entity(
        self, db: AsyncSession, name: str, entity_type: str, description: str | None = None
    ) -> KnowledgeGraphEntity:
        stmt = select(KnowledgeGraphEntity).where(
            KnowledgeGraphEntity.name == name,
            KnowledgeGraphEntity.entity_type == entity_type,
        )
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()
        if entity:
            entity.mention_count += 1
            if description and not entity.description:
                entity.description = description
            await db.flush()
            return entity

        entity = KnowledgeGraphEntity(
            name=name,
            entity_type=entity_type,
            description=description,
            mention_count=1,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_triple(
        self,
        db: AsyncSession,
        subject_id: int,
        predicate: str,
        object_id: int,
        source_kb_id: int | None = None,
        source_chunk_id: int | None = None,
        confidence: float = 1.0,
    ) -> KnowledgeTriple | None:
        check_stmt = select(KnowledgeTriple).where(
            KnowledgeTriple.subject_id == subject_id,
            KnowledgeTriple.predicate == predicate,
            KnowledgeTriple.object_id == object_id,
        )
        result = await db.execute(check_stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        triple = KnowledgeTriple(
            subject_id=subject_id,
            predicate=predicate,
            object_id=object_id,
            source_kb_id=source_kb_id,
            source_chunk_id=source_chunk_id,
            confidence=confidence,
        )
        db.add(triple)
        await db.flush()
        return triple

    async def query_triples_by_entity(
        self, db: AsyncSession, entity_name: str, kb_id: int | None = None
    ) -> list[KnowledgeTriple]:
        stmt = (
            select(KnowledgeTriple)
            .options(
                selectinload(KnowledgeTriple.subject_entity),
                selectinload(KnowledgeTriple.object_entity),
            )
            .join(KnowledgeGraphEntity, KnowledgeTriple.subject_id == KnowledgeGraphEntity.id)
            .where(
                (KnowledgeGraphEntity.name == entity_name)
                | (
                    KnowledgeTriple.object_id.in_(
                        select(KnowledgeGraphEntity.id).where(KnowledgeGraphEntity.name == entity_name)
                    )
                )
            )
        )
        if kb_id is not None:
            stmt = stmt.where(KnowledgeTriple.source_kb_id == kb_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def query_two_hop(
        self, db: AsyncSession, entity_name: str, kb_id: int | None = None
    ) -> list[KnowledgeTriple]:
        first_hop = await self.query_triples_by_entity(db, entity_name, kb_id)
        neighbor_ids = set()
        for t in first_hop:
            if t.subject_entity.name == entity_name:
                neighbor_ids.add(t.object_id)
            else:
                neighbor_ids.add(t.subject_id)

        if not neighbor_ids:
            return first_hop

        stmt = (
            select(KnowledgeTriple)
            .options(
                selectinload(KnowledgeTriple.subject_entity),
                selectinload(KnowledgeTriple.object_entity),
            )
            .where(KnowledgeTriple.subject_id.in_(neighbor_ids) | KnowledgeTriple.object_id.in_(neighbor_ids))
        )
        if kb_id is not None:
            stmt = stmt.where(KnowledgeTriple.source_kb_id == kb_id)
        result = await db.execute(stmt)
        second_hop = list(result.scalars().all())

        seen = set()
        merged = []
        for t in first_hop + second_hop:
            if t.id not in seen:
                seen.add(t.id)
                merged.append(t)
        return merged

    async def get_graph_data(
        self,
        db: AsyncSession,
        kb_id: int | None = None,
        entity_types: list[str] | None = None,
        limit: int = 200,
    ) -> GraphDataDTO:
        triple_stmt = (
            select(KnowledgeTriple)
            .options(
                selectinload(KnowledgeTriple.subject_entity),
                selectinload(KnowledgeTriple.object_entity),
            )
            .join(KnowledgeGraphEntity, KnowledgeTriple.subject_id == KnowledgeGraphEntity.id)
        )
        if kb_id is not None:
            triple_stmt = triple_stmt.where(KnowledgeTriple.source_kb_id == kb_id)
        triple_stmt = triple_stmt.order_by(
            (KnowledgeGraphEntity.mention_count + KnowledgeTriple.confidence * 10).desc()
        ).limit(limit)

        result = await db.execute(triple_stmt)
        triples = list(result.scalars().all())

        nodes_map: dict[str, dict] = {}
        edges = []
        type_counts: dict[str, int] = {}

        for t in triples:
            subj = t.subject_entity
            obj = t.object_entity

            if entity_types:
                if subj.entity_type not in entity_types and obj.entity_type not in entity_types:
                    continue

            if subj.name not in nodes_map:
                nodes_map[subj.name] = {
                    "id": subj.name,
                    "label": subj.name,
                    "type": subj.entity_type,
                    "size": subj.mention_count,
                    "properties": json.loads(subj.properties_json) if subj.properties_json else {},
                }
                type_counts[subj.entity_type] = type_counts.get(subj.entity_type, 0) + 1

            if obj.name not in nodes_map:
                nodes_map[obj.name] = {
                    "id": obj.name,
                    "label": obj.name,
                    "type": obj.entity_type,
                    "size": obj.mention_count,
                    "properties": json.loads(obj.properties_json) if obj.properties_json else {},
                }
                type_counts[obj.entity_type] = type_counts.get(obj.entity_type, 0) + 1

            edges.append(
                {
                    "source": subj.name,
                    "target": obj.name,
                    "relation": t.predicate,
                    "confidence": t.confidence,
                }
            )

        return GraphDataDTO(
            nodes=[GraphNodeDTO(**n) for n in nodes_map.values()],
            edges=[GraphEdgeDTO(**e) for e in edges],
            stats=GraphStatsDTO(
                entity_count=len(nodes_map),
                triple_count=len(edges),
                type_distribution=type_counts,
            ),
        )

    async def get_entity_detail(self, db: AsyncSession, entity_name: str, depth: int = 2) -> EntityDetailDTO | None:
        stmt = select(KnowledgeGraphEntity).where(KnowledgeGraphEntity.name == entity_name)
        result = await db.execute(stmt)
        entity = result.scalar_one_or_none()
        if not entity:
            return None

        if depth <= 1:
            triples = await self.query_triples_by_entity(db, entity_name)
        else:
            triples = await self.query_two_hop(db, entity_name)

        triple_dtos = []
        for t in triples:
            triple_dtos.append(
                TripleDTO(
                    id=t.id,
                    subject=EntityDTO(
                        id=t.subject_entity.id,
                        name=t.subject_entity.name,
                        entity_type=t.subject_entity.entity_type,
                        description=t.subject_entity.description,
                        properties=json.loads(t.subject_entity.properties_json)
                        if t.subject_entity.properties_json
                        else {},
                        mention_count=t.subject_entity.mention_count,
                    ),
                    predicate=t.predicate,
                    object=EntityDTO(
                        id=t.object_entity.id,
                        name=t.object_entity.name,
                        entity_type=t.object_entity.entity_type,
                        description=t.object_entity.description,
                        properties=json.loads(t.object_entity.properties_json)
                        if t.object_entity.properties_json
                        else {},
                        mention_count=t.object_entity.mention_count,
                    ),
                    confidence=t.confidence,
                    source_kb_id=t.source_kb_id,
                )
            )

        return EntityDetailDTO(
            entity=EntityDTO(
                id=entity.id,
                name=entity.name,
                entity_type=entity.entity_type,
                description=entity.description,
                properties=json.loads(entity.properties_json) if entity.properties_json else {},
                mention_count=entity.mention_count,
            ),
            related_triples=triple_dtos,
        )

    async def list_entities(
        self,
        db: AsyncSession,
        entity_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[KnowledgeGraphEntity], int]:
        stmt = select(KnowledgeGraphEntity)
        count_stmt = select(func.count(KnowledgeGraphEntity.id))

        if entity_type:
            stmt = stmt.where(KnowledgeGraphEntity.entity_type == entity_type)
            count_stmt = count_stmt.where(KnowledgeGraphEntity.entity_type == entity_type)
        if keyword:
            stmt = stmt.where(KnowledgeGraphEntity.name.ilike(f"%{keyword}%"))
            count_stmt = count_stmt.where(KnowledgeGraphEntity.name.ilike(f"%{keyword}%"))

        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(KnowledgeGraphEntity.mention_count.desc())
        stmt = stmt.offset((page - 1) * size).limit(size)
        result = await db.execute(stmt)
        entities = list(result.scalars().all())

        return entities, total

    async def clear_by_kb_id(self, db: AsyncSession, kb_id: int) -> None:
        await db.execute(delete(KnowledgeTriple).where(KnowledgeTriple.source_kb_id == kb_id))
        await self._cleanup_orphan_entities(db)
        await db.flush()

    async def _cleanup_orphan_entities(self, db: AsyncSession) -> None:
        orphan_ids = select(KnowledgeGraphEntity.id).where(
            ~KnowledgeGraphEntity.id.in_(select(KnowledgeTriple.subject_id)),
            ~KnowledgeGraphEntity.id.in_(select(KnowledgeTriple.object_id)),
        )
        await db.execute(delete(KnowledgeGraphEntity).where(KnowledgeGraphEntity.id.in_(orphan_ids)))

    async def delete_triple(self, db: AsyncSession, triple_id: int) -> bool:
        stmt = select(KnowledgeTriple).where(KnowledgeTriple.id == triple_id)
        result = await db.execute(stmt)
        triple = result.scalar_one_or_none()
        if not triple:
            return False
        await db.delete(triple)
        await self._cleanup_orphan_entities(db)
        await db.flush()
        return True

    def to_entity_dto(self, entity: KnowledgeGraphEntity) -> EntityDTO:
        return EntityDTO(
            id=entity.id,
            name=entity.name,
            entity_type=entity.entity_type,
            description=entity.description,
            properties=json.loads(entity.properties_json) if entity.properties_json else {},
            mention_count=entity.mention_count,
        )


knowledge_graph_persistence_service = KnowledgeGraphPersistenceService()
