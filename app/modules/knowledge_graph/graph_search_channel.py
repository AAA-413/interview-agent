import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.modules.knowledge_base.schemas import RagReferenceDTO
from app.modules.knowledge_base.search_channel import SearchChannel, SearchChannelResult, SearchContext
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service

logger = logging.getLogger(__name__)

ENTITY_EXTRACT_PROMPT = """从以下问题中提取出所有提到的实体名称（技术、框架、工具、概念等）。

问题：{question}

只输出实体名称列表，用逗号分隔，不要其他文字。
示例输出：Redis,MySQL,缓存

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

            chunks = self._triples_to_references(unique_triples, entities)

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
                SystemMessage(content="你是实体提取助手。从问题中提取技术实体名称，用逗号分隔输出。只输出名称，不要其他文字。"),
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

    @staticmethod
    def _triples_to_references(
        triples: list, query_entities: list[str]
    ) -> list[RagReferenceDTO]:
        references = []
        entity_set = set(query_entities)

        for triple in triples:
            subj_name = triple.subject_entity.name
            obj_name = triple.object_entity.name

            is_direct = subj_name in entity_set or obj_name in entity_set
            score = 0.85 if is_direct else 0.65

            content = f"{subj_name} —[{triple.predicate}]→ {obj_name}"
            if triple.subject_entity.description:
                content += f"\n{subj_name}：{triple.subject_entity.description}"
            if triple.object_entity.description:
                content += f"\n{obj_name}：{triple.object_entity.description}"

            title = f"{subj_name} {triple.predicate} {obj_name}"

            references.append(RagReferenceDTO(
                chunk_id=triple.id,
                chunk_index=0,
                title=title,
                content=content,
                content_preview=content[:200],
                score=score,
                source_name="知识图谱",
                metadata={
                    "type": "knowledge_graph",
                    "subject": subj_name,
                    "predicate": triple.predicate,
                    "object": obj_name,
                },
            ))

        return references


knowledge_graph_search_channel = GraphSearchChannel
