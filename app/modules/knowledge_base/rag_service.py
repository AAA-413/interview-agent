import json
import logging
import uuid
from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.models import KnowledgeChunkEntity
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.knowledge_base.rerank_service import get_rerank_service
from app.modules.knowledge_base.schemas import RagAnswerDTO, RagReferenceDTO
from app.modules.knowledge_base.search_channel import (
    MultiChannelRetrievalEngine,
    SearchContext,
    VectorSearchChannel,
)
from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = (
    "你是检索查询改写助手。请将用户问题改写为更适合知识库检索的简洁查询，"
    "保留核心实体、名词和约束，不要扩展无关内容。只输出改写后的查询文本。"
)

ANSWER_SYSTEM_PROMPT = (
    "你是知识库问答助手。请严格基于给定参考片段回答。"
    "如果参考内容不足，请明确说明依据不足，不要编造。"
    "回答使用中文，尽量结构化，必要时引用片段编号如 [1][2]。"
    "在回答末尾，基于内容生成 2-3 个推荐追问问题，以 `---` 分隔，格式为 `**推荐追问：**` 开头。"
)


class KnowledgeBaseRagService:
    def __init__(self):
        # 多路检索引擎将在运行时初始化（需要 db session）
        self.retrieval_engine = None
        # 重排序服务
        self.rerank_service = get_rerank_service()
        logger.info("RAG 服务初始化完成: rerank_enabled=%s", self.rerank_service.enabled)

    async def ask(
        self,
        db: AsyncSession,
        *,
        kb_id: int,
        question: str,
        session_id: str | None = None,
        top_k: int = 4,
    ) -> RagAnswerDTO:
        kb = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id)
        if kb.index_status != AsyncTaskStatus.COMPLETED:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_QUERY_FAILED, "知识库尚未完成索引，暂时无法问答")

        resolved_session_id = session_id or uuid.uuid4().hex

        # 获取对话历史（多轮上下文）
        chat_history = None
        if session_id:
            prev_chats = await knowledge_base_persistence_service.find_session_chats(db, kb_id, session_id)
            if prev_chats:
                chat_history = [{"question": c.question, "answer": c.answer or ""} for c in prev_chats]

        rewritten_query = await self._rewrite_query(question, chat_history)
        chat = await knowledge_base_persistence_service.create_chat(
            db,
            kb_id=kb_id,
            session_id=resolved_session_id,
            question=question,
            rewritten_query=rewritten_query,
        )

        try:
            # 初始化多路检索引擎（如果尚未初始化）
            if self.retrieval_engine is None:
                vector_channel = VectorSearchChannel(self, knowledge_base_vector_service, db)
                from app.modules.knowledge_graph.graph_search_channel import GraphSearchChannel

                graph_channel = GraphSearchChannel(db)
                self.retrieval_engine = MultiChannelRetrievalEngine([vector_channel, graph_channel])
                logger.info("多路检索引擎初始化: channels=2 (Vector + Graph)")

            # 使用多路检索引擎
            query_embedding = knowledge_base_vector_service.embed_text(rewritten_query)
            context = SearchContext(
                question=question,
                kb_id=kb_id,
                top_k=top_k * 2,  # 召回更多候选，用于重排序
                query_embedding=query_embedding,
                rewritten_query=rewritten_query,
            )
            candidates = await self.retrieval_engine.retrieve(context)

            # 重排序（如果启用）
            references = await self.rerank_service.rerank(question, candidates, top_k)

            answer = await self._generate_answer(question, rewritten_query, references)
            reference_payload = [reference.model_dump() for reference in references]
            await knowledge_base_persistence_service.complete_chat(
                db,
                chat_id=chat.id,
                rewritten_query=rewritten_query,
                answer=answer,
                references=reference_payload,
            )
            await db.flush()
            return RagAnswerDTO(
                session_id=resolved_session_id,
                rewritten_query=rewritten_query,
                answer=answer,
                references=references,
            )
        except Exception as e:
            await knowledge_base_persistence_service.fail_chat(db, chat_id=chat.id, error_message=str(e))
            raise

    async def stream_answer(
        self,
        db: AsyncSession,
        *,
        kb_id: int,
        question: str,
        session_id: str | None = None,
        top_k: int = 4,
    ) -> AsyncIterator[str]:
        kb = await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id)
        if kb.index_status != AsyncTaskStatus.COMPLETED:
            raise BusinessException(ErrorCode.KNOWLEDGE_BASE_QUERY_FAILED, "知识库尚未完成索引，暂时无法问答")

        resolved_session_id = session_id or uuid.uuid4().hex

        # 获取对话历史（多轮上下文）
        chat_history = None
        if session_id:
            prev_chats = await knowledge_base_persistence_service.find_session_chats(db, kb_id, session_id)
            if prev_chats:
                chat_history = [{"question": c.question, "answer": c.answer or ""} for c in prev_chats]

        rewritten_query = await self._rewrite_query(question, chat_history)
        chat = await knowledge_base_persistence_service.create_chat(
            db,
            kb_id=kb_id,
            session_id=resolved_session_id,
            question=question,
            rewritten_query=rewritten_query,
        )

        try:
            if self.retrieval_engine is None:
                vector_channel = VectorSearchChannel(self, knowledge_base_vector_service, db)
                from app.modules.knowledge_graph.graph_search_channel import GraphSearchChannel

                graph_channel = GraphSearchChannel(db)
                self.retrieval_engine = MultiChannelRetrievalEngine([vector_channel, graph_channel])

            query_embedding = knowledge_base_vector_service.embed_text(rewritten_query)
            context = SearchContext(
                question=question,
                kb_id=kb_id,
                top_k=top_k * 2,
                query_embedding=query_embedding,
                rewritten_query=rewritten_query,
            )
            candidates = await self.retrieval_engine.retrieve(context)
            references = await self.rerank_service.rerank(question, candidates, top_k)

            yield self._sse_event("meta", {"session_id": resolved_session_id, "rewritten_query": rewritten_query})
            yield self._sse_event("references", {"items": [item.model_dump() for item in references]})

            if not references:
                answer = "未在知识库中检索到足够相关的内容，当前无法给出可靠答案。"
                yield self._sse_event("chunk", {"content": answer})
                yield self._sse_event("done", {"answer": answer})
                await knowledge_base_persistence_service.complete_chat(
                    db,
                    chat_id=chat.id,
                    rewritten_query=rewritten_query,
                    answer=answer,
                    references=[],
                )
                await db.flush()
                return

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
                db,
                chat_id=chat.id,
                rewritten_query=rewritten_query,
                answer=answer,
                references=reference_payload,
            )
            await db.flush()
        except Exception as e:
            await knowledge_base_persistence_service.fail_chat(db, chat_id=chat.id, error_message=str(e))
            raise

    async def list_chats(self, db: AsyncSession, kb_id: int):
        await knowledge_base_persistence_service.find_by_id_or_throw(db, kb_id)
        chats = await knowledge_base_persistence_service.find_recent_chats(db, kb_id)
        return [knowledge_base_persistence_service.to_chat_list_item(item) for item in chats]

    async def _rewrite_query(self, question: str, chat_history: list[dict] | None = None) -> str:
        try:
            messages = [SystemMessage(content=REWRITE_SYSTEM_PROMPT)]

            # 如果有对话历史，添加上下文
            if chat_history:
                history_text = "\n".join(f"用户: {c['question']}\n助手: {c['answer'][:200]}" for c in chat_history)
                messages.append(
                    HumanMessage(
                        content=f"对话历史：\n{history_text}\n\n当前问题：{question}\n\n请结合对话历史改写当前问题，使其能独立检索到相关内容。只输出改写后的查询。"
                    )
                )
            else:
                messages.append(HumanMessage(content=question))

            response = await llm_registry.default.ainvoke(messages)
            text = (response.content or "").strip() if hasattr(response, "content") else ""
            return text or question
        except Exception as e:
            logger.warning("查询改写失败，回退原问题: %s", e)
            return question

    async def _generate_answer(
        self,
        question: str,
        rewritten_query: str,
        references: list[RagReferenceDTO],
    ) -> str:
        if not references:
            return "未在知识库中检索到足够相关的内容，当前无法给出可靠答案。"

        prompt = self._build_answer_prompt(question, rewritten_query, references)
        try:
            response = await llm_registry.default.ainvoke(
                [
                    SystemMessage(content=ANSWER_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            text = (response.content or "").strip() if hasattr(response, "content") else ""
            if text:
                return text
        except Exception as e:
            logger.warning("LLM 生成问答失败，回退为模板答案: %s", e)

        summary_lines = [f"- {item.content or item.content_preview}" for item in references]
        return "根据知识库检索结果，相关内容包括：\n" + "\n".join(summary_lines)

    @staticmethod
    def _build_answer_prompt(
        question: str,
        rewritten_query: str,
        references: list[RagReferenceDTO],
    ) -> str:
        context_parts = []
        for index, item in enumerate(references, start=1):
            content = item.content or item.content_preview
            source = item.source_name or "知识库"
            context_parts.append(
                f"[片段{index}] 来源: {source}\n"
                f"标题: {item.title or '未命名'}\n"
                f"相关度: {item.score:.4f}\n"
                f"内容: {content}"
            )
        return (
            f"用户问题：{question}\n"
            f"检索查询：{rewritten_query}\n\n"
            f"参考片段：\n{chr(10).join(context_parts)}\n\n"
            "请基于这些片段回答。要求：\n"
            "1. 在回答中用 [1][2] 等标注引用来源\n"
            "2. 如有代码，保留代码块格式\n"
            "3. 回答末尾以 `---` 分隔，写 `**推荐追问：**` 后列出 2-3 个有价值的后续问题"
        )

    def _search_chunks(
        self,
        chunks: list[KnowledgeChunkEntity],
        query: str,
        top_k: int,
    ) -> list[RagReferenceDTO]:
        query_embedding = knowledge_base_vector_service.embed_text(query)
        scored: list[tuple[float, KnowledgeChunkEntity]] = []
        for chunk in chunks:
            embedding = self._parse_embedding(chunk.embedding_json)
            score = knowledge_base_vector_service.cosine_similarity(query_embedding, embedding)
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)

        references: list[RagReferenceDTO] = []
        for score, chunk in scored[: max(1, top_k)]:
            metadata = self._parse_metadata(chunk.metadata_json)
            references.append(
                RagReferenceDTO(
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    title=chunk.title,
                    content=chunk.content or "",
                    content_preview=chunk.content_preview or chunk.content[:180],
                    score=round(score, 4),
                    metadata=metadata,
                )
            )
        return references

    @staticmethod
    def _parse_embedding(payload: str | None) -> list[float]:
        if not payload:
            return []
        try:
            data = json.loads(payload)
            return [float(item) for item in data]
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @staticmethod
    def _parse_metadata(payload: str | None) -> dict:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _sse_event(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def _split_answer(answer: str, chunk_size: int = 120) -> list[str]:
        if not answer:
            return []
        return [answer[index : index + chunk_size] for index in range(0, len(answer), chunk_size)]


knowledge_base_rag_service = KnowledgeBaseRagService()
