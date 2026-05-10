import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.common.ai.llm_provider import llm_registry
from app.modules.knowledge_base.models import KnowledgeChunkEntity
from app.modules.knowledge_base.schemas import RagReferenceDTO
from app.modules.knowledge_base.search_channel import SearchChannel, SearchChannelResult, SearchContext
from app.modules.knowledge_graph.models import KnowledgeGraphEntity, KnowledgeTriple
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service

logger = logging.getLogger(__name__)

ENTITY_EXTRACT_PROMPT = """从以下问题中提取出所有提到的实体名称（技术、框架、工具、概念、理论、方法、人物等）。

问题：{question}

只输出实体名称列表，用逗号分隔，不要其他文字。
示例输出：Redis,MySQL,缓存,认知失调理论,FastAPI

如果没有明确的实体，输出空行。"""


class GraphSearchChannel(SearchChannel):

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    def get_name(self) -> str:
        return "GraphSearch"

    def get_priority(self) -> int:
        return 2

    def is_enabled(self, context: SearchContext) -> bool:
        return True

    async def search(self, context: SearchContext) -> SearchChannelResult:
        start = time.time()

        try:
            entities = await self._extract_query_entities(context.question or context.rewritten_query or "")
            if not entities:
                logger.info("图谱检索: 未从问题中提取到实体")
                return SearchChannelResult(
                    channel_name=self.get_name(),
                    chunks=[],
                    confidence=0.0,
                    latency_ms=int((time.time() - start) * 1000),
                )

            logger.info("图谱检索: 提取到实体 %s", entities)

            all_triples = []
            for entity_name in entities:
                triples = await knowledge_graph_persistence_service.query_two_hop(
                    self.db_session, entity_name, context.kb_id
                )
                all_triples.extend(triples)

            seen = set()
            unique_triples = []
            for t in all_triples:
                if t.id not in seen:
                    seen.add(t.id)
                    unique_triples.append(t)

            # 从三元组关联到实际的知识库文本片段
            chunks = await self._triples_to_chunk_references(
                unique_triples, entities, context.kb_id, context.query_embedding,
            )

            chunks.sort(key=lambda c: c.score, reverse=True)
            chunks = chunks[:context.top_k]

            latency_ms = int((time.time() - start) * 1000)
            confidence = max([c.score for c in chunks]) if chunks else 0.0

            logger.info(
                "图谱检索完成: entities=%d, triples=%d, results=%d, latency=%dms",
                len(entities), len(unique_triples), len(chunks), latency_ms,
            )

            return SearchChannelResult(
                channel_name=self.get_name(),
                chunks=chunks,
                confidence=confidence,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error("图谱检索失败: %s", e, exc_info=True)
            return SearchChannelResult(
                channel_name=self.get_name(),
                chunks=[],
                confidence=0.0,
                latency_ms=int((time.time() - start) * 1000),
            )

    async def _extract_query_entities(self, question: str) -> list[str]:
        if not question:
            return []

        try:
            messages = [
                SystemMessage(content="你是实体提取助手。从问题中提取实体名称（技术、概念、理论、方法、人物等），用逗号分隔输出。只输出名称，不要其他文字。"),
                HumanMessage(content=ENTITY_EXTRACT_PROMPT.format(question=question)),
            ]
            response = await llm_registry.default.ainvoke(messages)
            content = (response.content or "").strip() if hasattr(response, "content") else ""

            if not content:
                return []

            entities = [e.strip() for e in content.split(",") if e.strip()]
            return entities[:5]
        except Exception as e:
            logger.warning("实体提取失败: %s", e)
            return []

    async def _triples_to_chunk_references(
        self,
        triples: list,
        query_entities: list[str],
        kb_id: int | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[RagReferenceDTO]:
        """将图谱三元组映射到实际的知识库文本片段。"""
        if not triples:
            return []

        entity_set = set(query_entities)
        # 收集所有图谱中涉及的实体名
        graph_entity_names: set[str] = set()
        for triple in triples:
            graph_entity_names.add(triple.subject_entity.name)
            graph_entity_names.add(triple.object_entity.name)

        # 从 knowledge_chunks 中查找包含这些实体的片段
        from sqlalchemy import select, or_
        stmt = select(KnowledgeChunkEntity)
        if kb_id is not None:
            stmt = stmt.where(KnowledgeChunkEntity.knowledge_base_id == kb_id)

        # 用 ILIKE 匹配实体名（取前 10 个最长的实体名避免条件过多）
        sorted_names = sorted(graph_entity_names, key=len, reverse=True)[:10]
        conditions = [
            KnowledgeChunkEntity.content.ilike(f"%{name}%")
            for name in sorted_names
        ]
        stmt = stmt.where(or_(*conditions))
        stmt = stmt.limit(30)

        result = await self.db_session.execute(stmt)
        chunks = list(result.scalars().all())

        # 语义过滤：仅跨KB模式启用（kb_id=None），过滤不同KB中的噪声chunk
        if query_embedding is not None and chunks and kb_id is None:
            semantic_threshold = 0.4
            filtered_chunks = []
            for chunk in chunks:
                if chunk.embedding is not None:
                    similarity = 1.0 - self._cosine_distance(query_embedding, chunk.embedding)
                    if similarity >= semantic_threshold:
                        filtered_chunks.append(chunk)
                else:
                    filtered_chunks.append(chunk)
            if len(filtered_chunks) < len(chunks):
                logger.info(
                    "图谱语义过滤: %d → %d chunks (阈值=%.2f)",
                    len(chunks), len(filtered_chunks), semantic_threshold,
                )
            chunks = filtered_chunks

        if not chunks:
            return []

        # 计算每个 chunk 与图谱实体的匹配度
        references = []
        for chunk in chunks:
            content = chunk.content or ""
            # 命中的实体名数量（区分直接实体和间接实体）
            direct_hits = sum(1 for e in entity_set if e in content)
            graph_hits = sum(1 for e in graph_entity_names if e in content)

            score = min(0.95, 0.5 + direct_hits * 0.15 + graph_hits * 0.05)

            kb_name = f"KB#{chunk.knowledge_base_id}"
            references.append(RagReferenceDTO(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                title=chunk.title or "",
                content=content,
                content_preview=(content or "")[:200],
                score=score,
                source_name=kb_name,
                metadata={
                    "type": "knowledge_graph",
                    "matched_entities": [e for e in graph_entity_names if e in content],
                    "direct_entity_hits": direct_hits,
                },
            ))

        references.sort(key=lambda c: c.score, reverse=True)
        return references

    @staticmethod
    def _cosine_distance(vec1: list[float], vec2: list[float]) -> float:
        import math
        dot = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = math.sqrt(sum(a * a for a in vec1))
        mag2 = math.sqrt(sum(b * b for b in vec2))
        if mag1 == 0 or mag2 == 0:
            return 1.0
        return 1.0 - dot / (mag1 * mag2)


knowledge_graph_search_channel = GraphSearchChannel
