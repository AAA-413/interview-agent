import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.rag_service import ANSWER_SYSTEM_PROMPT, REWRITE_SYSTEM_PROMPT
from app.modules.knowledge_base.rerank_service import get_rerank_service
from app.modules.knowledge_base.schemas import RagAnswerDTO, RagReferenceDTO, RagChatListItemDTO
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service
from app.modules.knowledge_graph.graph_search_channel import GraphSearchChannel
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service

logger = logging.getLogger(__name__)


class CrossKBRagService:
    """跨知识库 RAG 问答服务"""

    def __init__(self):
        self.rerank_service = get_rerank_service()
        self._entity_cache: dict[str, list[str]] = {}

    async def ask(
        self, db: AsyncSession, *, user_id: int, question: str, top_k: int = 4
    ) -> RagAnswerDTO:
        session_id = uuid.uuid4().hex

        rewritten_query = await self._rewrite_query(question, None)

        query_embedding = knowledge_base_vector_service.embed_text(rewritten_query)

        candidates = await self._vector_search(db, user_id, rewritten_query, top_k * 2)
        graph_results = await self._graph_search(db, question, top_k, weight=0.5, query_embedding=query_embedding)
        candidates.extend(graph_results)
        candidates = self._deduplicate(candidates)

        references = await self.rerank_service.rerank(question, candidates, top_k)

        answer = await self._generate_answer(question, rewritten_query, references)

        return RagAnswerDTO(
            session_id=session_id,
            rewritten_query=rewritten_query,
            answer=answer,
            references=references,
        )

    async def stream_answer(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        question: str,
        session_id: str | None = None,
        top_k: int = 4,
    ) -> AsyncIterator[str]:
        resolved_session_id = session_id or uuid.uuid4().hex

        # 加载历史 + 滑动压缩
        chat_history = None
        if session_id:
            prev_chats = await knowledge_base_persistence_service.find_cross_kb_session_chats(db, user_id, session_id)
            if prev_chats:
                chat_history = await self._compress_history(prev_chats)

        rewritten_query = await self._rewrite_query(question, chat_history)

        # 创建 PENDING 记录
        chat = await knowledge_base_persistence_service.create_cross_kb_chat(
            db, user_id=user_id, session_id=resolved_session_id,
            question=question, rewritten_query=rewritten_query,
        )

        try:
            # 检索
            query_embedding = knowledge_base_vector_service.embed_text(rewritten_query)
            candidates = await self._vector_search(
                db, user_id, rewritten_query, top_k * 2, query_embedding=query_embedding,
            )
            graph_results = await self._graph_search(
                db, question, top_k, weight=0.5, query_embedding=query_embedding,
            )
            candidates.extend(graph_results)
            candidates = self._deduplicate(candidates)
            references = await self.rerank_service.rerank(question, candidates, top_k)

            # SSE: meta + references
            yield self._sse_event("meta", {"session_id": resolved_session_id, "rewritten_query": rewritten_query})
            yield self._sse_event("references", {"items": [r.model_dump() for r in references]})

            if not references:
                answer = "未在知识库中检索到足够相关的内容，当前无法给出可靠答案。"
                yield self._sse_event("chunk", {"content": answer})
                yield self._sse_event("done", {"answer": answer})
                await knowledge_base_persistence_service.complete_chat(
                    db, chat_id=chat.id, rewritten_query=rewritten_query, answer=answer, references=[],
                )
                await db.flush()
                return

            # 流式生成回答
            prompt = self._build_answer_prompt(question, rewritten_query, references)
            answer_parts: list[str] = []
            async for token in llm_registry.default.astream(
                [SystemMessage(content=ANSWER_SYSTEM_PROMPT), HumanMessage(content=prompt)]
            ):
                chunk_text = token.content if hasattr(token, "content") and token.content else ""
                if chunk_text:
                    answer_parts.append(chunk_text)
                    yield self._sse_event("chunk", {"content": chunk_text})

            answer = "".join(answer_parts).strip() or "未能生成回答。"
            yield self._sse_event("done", {"answer": answer})

            reference_payload = [ref.model_dump() for ref in references]
            await knowledge_base_persistence_service.complete_chat(
                db, chat_id=chat.id, rewritten_query=rewritten_query, answer=answer, references=reference_payload,
            )
            await db.flush()
        except Exception as e:
            await knowledge_base_persistence_service.fail_chat(db, chat_id=chat.id, error_message=str(e))
            raise

    async def list_chats(self, db: AsyncSession, user_id: int) -> list[RagChatListItemDTO]:
        chats = await knowledge_base_persistence_service.find_user_cross_kb_chats(db, user_id)
        return [knowledge_base_persistence_service.to_chat_list_item(c) for c in chats]

    async def _compress_history(self, chats: list) -> list[dict]:
        """最近3轮完整保留，更早的压缩为摘要"""
        RECENT_COUNT = 3

        recent = chats[-RECENT_COUNT:]
        older = chats[:-RECENT_COUNT] if len(chats) > RECENT_COUNT else []

        result = []

        if older:
            summary = await self._summarize_older_chats(older)
            result.append({"question": "[对话摘要]", "answer": summary})

        for c in recent:
            result.append({"question": c.question, "answer": (c.answer or "")[:200]})

        return result

    async def _summarize_older_chats(self, chats: list) -> str:
        try:
            history_text = "\n".join(
                f"用户: {c.question}\n助手: {(c.answer or '')[:150]}"
                for c in chats
            )
            prompt = f"请将以下对话历史压缩为一段简洁摘要（不超过100字），保留关键信息和讨论主题：\n\n{history_text}"
            response = await llm_registry.default.ainvoke([
                SystemMessage(content="你是对话摘要助手。将对话历史压缩为简洁摘要，保留关键实体和主题。"),
                HumanMessage(content=prompt),
            ])
            return (response.content or "").strip()[:200]
        except Exception as e:
            logger.warning("对话摘要生成失败: %s", e)
            return f"（早期对话共{len(chats)}轮，摘要生成失败）"

    @staticmethod
    def _build_answer_prompt(
        question: str, rewritten_query: str, references: list[RagReferenceDTO],
    ) -> str:
        context_parts = []
        for index, item in enumerate(references, start=1):
            content = item.content or item.content_preview
            context_parts.append(
                f"[片段{index}] 来源: {item.source_name}\n"
                f"标题: {item.title or '未命名'}\n"
                f"相关度: {item.score:.4f}\n"
                f"内容: {content}"
            )
        ref_map = "\n".join(
            f"[{i}] → {item.source_name} / {item.title or '未命名'}"
            for i, item in enumerate(references, start=1)
        )
        return (
            f"用户问题：{question}\n"
            f"检索查询：{rewritten_query}\n\n"
            f"参考片段（来自多个知识库）：\n{chr(10).join(context_parts)}\n\n"
            "请基于这些片段回答。要求：\n"
            "1. 在回答中用 [1][2] 等标注引用来源\n"
            "2. 如有代码，保留代码块格式\n"
            "3. 回答末尾以 `---` 分隔，写 `**推荐追问：**` 后列出 2-3 个有价值的后续问题\n\n"
            f"引用来源映射（供参考，不要在回答中重复列出）：\n{ref_map}"
        )

    @staticmethod
    def _sse_event(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def retrieve_with_config(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        question: str,
        top_k: int = 4,
        use_vector: bool = True,
        use_graph: bool = True,
        use_rerank: bool = True,
        graph_weight: float = 0.5,
        scope_kb_id: int | None = None,
    ) -> tuple[list[RagReferenceDTO], int]:
        """可配置检索策略，供评估脚本调用。

        Args:
            scope_kb_id: None=跨KB搜索所有，指定值=只搜该KB
        Returns:
            (检索结果, 延迟毫秒)
        """
        start = time.time()

        # 无条件计算 embedding，供图谱语义过滤使用
        query_embedding = knowledge_base_vector_service.embed_text(question)

        vector_results: list[RagReferenceDTO] = []
        graph_results: list[RagReferenceDTO] = []

        if use_vector:
            vector_results = await self._vector_search(
                db, user_id, question, top_k * 2,
                kb_id=scope_kb_id, query_embedding=query_embedding,
            )

        if use_graph:
            graph_results = await self._graph_search(
                db, question, top_k, weight=graph_weight, kb_id=scope_kb_id,
                query_embedding=query_embedding,
            )

        # 分离管道：仅向量结果重排，图谱结果保留自身分数
        if use_rerank and self.rerank_service.enabled and vector_results:
            vector_results = await self.rerank_service.rerank(question, vector_results, top_k)

        # 合并 + dedup（取较高分）
        all_results = self._deduplicate(vector_results + graph_results)
        references = sorted(all_results, key=lambda c: c.score, reverse=True)[:top_k]

        latency_ms = int((time.time() - start) * 1000)
        return references, latency_ms

    async def _vector_search(
        self,
        db: AsyncSession,
        user_id: int,
        question: str,
        top_k: int,
        kb_id: int | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[RagReferenceDTO]:
        if query_embedding is None:
            query_embedding = knowledge_base_vector_service.embed_text(question)

        if kb_id is not None:
            stmt = (
                select(KnowledgeChunkEntity)
                .where(KnowledgeChunkEntity.knowledge_base_id == kb_id)
                .where(KnowledgeChunkEntity.embedding.isnot(None))
                .order_by(KnowledgeChunkEntity.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )
        else:
            stmt = (
                select(KnowledgeChunkEntity)
                .join(KnowledgeBaseEntity, KnowledgeChunkEntity.knowledge_base_id == KnowledgeBaseEntity.id)
                .where(KnowledgeBaseEntity.user_id == user_id)
                .where(KnowledgeBaseEntity.index_status == AsyncTaskStatus.COMPLETED)
                .where(KnowledgeChunkEntity.embedding.isnot(None))
                .order_by(KnowledgeChunkEntity.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )

        result = await db.execute(stmt)
        chunks = list(result.scalars().all())

        kb_names: dict[int, str] = {}
        references = []
        for chunk in chunks:
            kid = chunk.knowledge_base_id
            if kid not in kb_names:
                kb = await db.get(KnowledgeBaseEntity, kid)
                kb_names[kid] = kb.name if kb else f"KB#{kid}"

            if chunk.embedding is not None:
                distance = self._cosine_distance(query_embedding, chunk.embedding)
                score = 1.0 - distance
            else:
                score = 0.5

            references.append(RagReferenceDTO(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                title=chunk.title or "",
                content=chunk.content or "",
                content_preview=chunk.content_preview or (chunk.content or "")[:200],
                score=score,
                source_name=kb_names[kid],
            ))

        return references

    async def _graph_search(
        self,
        db: AsyncSession,
        question: str,
        top_k: int,
        weight: float = 0.5,
        kb_id: int | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[RagReferenceDTO]:
        try:
            entities = await self._extract_entities(question)
            if not entities:
                return []

            all_triples = []
            for entity_name in entities:
                triples = await knowledge_graph_persistence_service.query_two_hop(
                    db, entity_name, kb_id=kb_id
                )
                all_triples.extend(triples)

            seen = set()
            unique_triples = []
            for t in all_triples:
                if t.id not in seen:
                    seen.add(t.id)
                    unique_triples.append(t)

            if not unique_triples:
                return []

            # 从三元组关联到实际的知识库文本片段
            entity_set = set(entities)
            graph_entity_names: set[str] = set()
            for triple in unique_triples:
                graph_entity_names.add(triple.subject_entity.name)
                graph_entity_names.add(triple.object_entity.name)

            from sqlalchemy import or_, select
            from app.modules.knowledge_base.models import KnowledgeChunkEntity

            stmt = select(KnowledgeChunkEntity)
            if kb_id is not None:
                stmt = stmt.where(KnowledgeChunkEntity.knowledge_base_id == kb_id)

            sorted_names = sorted(graph_entity_names, key=len, reverse=True)[:10]
            conditions = [
                KnowledgeChunkEntity.content.ilike(f"%{name}%")
                for name in sorted_names
            ]
            stmt = stmt.where(or_(*conditions))
            stmt = stmt.limit(30)

            result = await db.execute(stmt)
            chunks = list(result.scalars().all())

            # 语义过滤：仅跨KB模式启用（kb_id=None），过滤不同KB中的噪声chunk
            # 单KB模式下所有chunk来自同一KB，不需要语义过滤
            if query_embedding is not None and chunks and kb_id is None:
                semantic_threshold = 0.4
                filtered_chunks = []
                for chunk in chunks:
                    if chunk.embedding is not None:
                        similarity = 1.0 - self._cosine_distance(query_embedding, chunk.embedding)
                        if similarity >= semantic_threshold:
                            filtered_chunks.append(chunk)
                    else:
                        filtered_chunks.append(chunk)  # 无 embedding 保留
                if len(filtered_chunks) < len(chunks):
                    logger.info(
                        "图谱语义过滤: %d → %d chunks (阈值=%.2f)",
                        len(chunks), len(filtered_chunks), semantic_threshold,
                    )
                chunks = filtered_chunks

            references = []
            for chunk in chunks:
                content = chunk.content or ""
                direct_hits = sum(1 for e in entity_set if e in content)
                graph_hits = sum(1 for e in graph_entity_names if e in content)
                raw_score = min(0.95, 0.5 + direct_hits * 0.15 + graph_hits * 0.05)
                score = raw_score * weight

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
                    },
                ))

            references.sort(key=lambda c: c.score, reverse=True)
            return references[:top_k]
        except Exception as e:
            logger.warning("图谱检索失败: %s", e)
            return []

    async def _extract_entities(self, question: str) -> list[str]:
        # 缓存：同一问题在不同策略/场景下实体相同
        if question in self._entity_cache:
            return self._entity_cache[question]
        try:
            prompt = (
                "从以下问题中提取出所有提到的实体名称（技术、框架、工具、概念、理论、方法、人物等）。\n\n"
                f"问题：{question}\n\n"
                "只输出实体名称列表，用逗号分隔，不要其他文字。\n"
                "示例输出：Redis,MySQL,缓存,认知失调理论,FastAPI\n\n"
                "如果没有明确的实体，输出空行。"
            )
            messages = [
                SystemMessage(content="你是实体提取助手。从问题中提取实体名称（技术、概念、理论、方法、人物等），用逗号分隔输出。只输出名称，不要其他文字。"),
                HumanMessage(content=prompt),
            ]
            response = await llm_registry.default.ainvoke(messages)
            content = (response.content or "").strip() if hasattr(response, "content") else ""
            if not content:
                self._entity_cache[question] = []
                return []
            result = [e.strip() for e in content.split(",") if e.strip()][:5]
            self._entity_cache[question] = result
            return result
        except Exception as e:
            logger.warning("实体提取失败: %s", e)
            return []

    async def _rewrite_query(
        self, question: str, chat_history: list[dict] | None = None
    ) -> str:
        try:
            messages = [SystemMessage(content=REWRITE_SYSTEM_PROMPT)]
            if chat_history:
                history_text = "\n".join(
                    f"用户: {c['question']}\n助手: {c['answer'][:200]}"
                    for c in chat_history
                )
                messages.append(HumanMessage(
                    content=f"对话历史：\n{history_text}\n\n当前问题：{question}\n\n请结合对话历史改写当前问题，使其能独立检索到相关内容。只输出改写后的查询。"
                ))
            else:
                messages.append(HumanMessage(content=question))
            response = await llm_registry.default.ainvoke(messages)
            text = (response.content or "").strip() if hasattr(response, "content") else ""
            return text or question
        except Exception as e:
            logger.warning("查询改写失败，回退原问题: %s", e)
            return question

    async def _generate_answer(
        self, question: str, rewritten_query: str, references: list[RagReferenceDTO]
    ) -> str:
        if not references:
            return "未在知识库中检索到足够相关的内容，当前无法给出可靠答案。"

        prompt = self._build_answer_prompt(question, rewritten_query, references)
        try:
            response = await llm_registry.default.ainvoke(
                [SystemMessage(content=ANSWER_SYSTEM_PROMPT), HumanMessage(content=prompt)]
            )
            text = (response.content or "").strip() if hasattr(response, "content") else ""
            if text:
                return text
        except Exception as e:
            logger.warning("LLM 生成问答失败: %s", e)

        summary_lines = [f"- [{i.source_name}] {i.content or i.content_preview}" for i in references]
        return "根据知识库检索结果，相关内容包括：\n" + "\n".join(summary_lines)

    @staticmethod
    def _deduplicate(chunks: list[RagReferenceDTO]) -> list[RagReferenceDTO]:
        seen: dict[int, RagReferenceDTO] = {}
        for chunk in chunks:
            if chunk.chunk_id not in seen or chunk.score > seen[chunk.chunk_id].score:
                seen[chunk.chunk_id] = chunk
        return list(seen.values())

    @staticmethod
    def _cosine_distance(vec1: list[float], vec2: list[float]) -> float:
        import math
        dot = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = math.sqrt(sum(a * a for a in vec1))
        mag2 = math.sqrt(sum(b * b for b in vec2))
        if mag1 == 0 or mag2 == 0:
            return 1.0
        return 1.0 - dot / (mag1 * mag2)


cross_kb_rag_service = CrossKBRagService()
