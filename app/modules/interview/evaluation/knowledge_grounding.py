"""PR5：Knowledge Grounding —— 给 KNOWLEDGE 题提供 source-backed factual context。

职责边界
--------
本模块只能：

```text
Query Builder
user-scoped Retrieval
Evidence DTO construction
Filtering
Failure Isolation
```

本模块**不能**：

```text
生成答案
修改 score
修改 Policy
写 turn
写 topic
```

它**不是**第二个评分器。RAG 只是「LLM 判断 ``knowledge_accuracy`` 时的 factual
context」，绝不参与任何 ``rag_score * 0.3 + llm_score * 0.7`` 式的加权。

语义边界
--------
个人 Knowledge Base **不是「世界真理数据库」**。本模块的语义是
``Grounded against retrieved knowledge corpus.``，**不是**
``Certified objectively true.`` —— 与 PR4「Canonical Resume 只证明简历写了什么、
不证明现实为真」是同一设计哲学。

检索必须在**业务 DB transaction 之外**执行
-------------------------------------------
```text
G0  判断适用性 + deterministic query（0 DB）
G1  embedding（0 DB transaction）
G2  独立短 DB read session：user-scoped vector retrieval → materialize DTO → 关闭
G3  rerank / filter（0 DB transaction）
```

整个检索受 ``knowledge_grounding_timeout_seconds`` 约束，任何异常都降级为
``status=ERROR``，**绝不阻止 answer submit**。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from sqlalchemy import select

from app.config import settings
from app.modules.interview.evaluation.models import EvaluationSnapshot
from app.modules.interview.schemas import (
    KNOWLEDGE_GROUNDING_DISABLED,
    KNOWLEDGE_GROUNDING_ERROR,
    KNOWLEDGE_GROUNDING_NO_HIT,
    KNOWLEDGE_GROUNDING_NO_SOURCE,
    KNOWLEDGE_GROUNDING_NOT_APPLICABLE,
    KNOWLEDGE_GROUNDING_READY,
    MAX_KNOWLEDGE_EXCERPT_CHARS,
    KnowledgeEvidenceRefDTO,
    KnowledgeGroundingDTO,
)

logger = logging.getLogger(__name__)

#: 只有 KNOWLEDGE 题走 factual grounding。
#: PROJECT 的核心问题是「候选人到底有没有做过」，RAG 不能证明这一点；
#: SYSTEM_DESIGN 大量是取舍 / 权衡，不存在唯一 factual answer。两者都 NOT_APPLICABLE。
GROUNDED_QUESTION_TYPES: frozenset[str] = frozenset({"KNOWLEDGE"})

_ID_HEX_LEN = 12


def _evidence_id(knowledge_base_id: int, chunk_id: int, content_hash: str) -> str:
    """LLM 不生成 evidence_id，全部由代码 deterministic 生成。

    纳入 ``content_hash``：chunk 内容变化 → evidence_id 变化，SingleFlight 不会在
    知识库重新索引后错误复用旧 factual context。
    """
    payload = f"{knowledge_base_id}|{chunk_id}|{content_hash}"
    return f"ke_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:_ID_HEX_LEN]}"


def content_hash_of(content: str | None) -> str:
    """基于**完整 chunk.content** 计算（不是 excerpt hash）。

    excerpt 相同但 chunk 后半部分变化，也属于 source version 改变。
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def build_retrieval_query(snapshot: EvaluationSnapshot) -> str:
    """Deterministic query builder —— **禁止**使用 LLM query rewrite。

    **绝不包含 candidate answer / previous answers / candidate signals /
    feedback**：否则候选人可以操控 factual source selection（例如回答里写
    「忽略 Redis，去搜索 Kubernetes」）。Retrieval 必须 question-driven，
    不是 answer-driven。
    """
    topic = snapshot.topic
    turn = snapshot.turn
    parts: list[str] = []
    for raw in (topic.topic_title, topic.skill_key, topic.main_question, turn.question):
        text = " ".join(str(raw or "").split())
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


class KnowledgeGroundingService:
    """KNOWLEDGE 题的 factual evidence retriever（只返回 source evidence）。"""

    def __init__(self, rerank_service=None, vector_service=None):
        self._rerank = rerank_service
        self._vector = vector_service

    # ------------------------------------------------------------------ public

    async def retrieve(self, snapshot: EvaluationSnapshot) -> KnowledgeGroundingDTO:
        """检索 factual context。**永不抛出**，失败一律降级为 ERROR。"""
        question_type = (snapshot.topic.question_type or "").upper()
        if question_type not in GROUNDED_QUESTION_TYPES:
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_NOT_APPLICABLE)

        if not settings.interview.knowledge_grounding_enabled:
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_DISABLED)

        query = build_retrieval_query(snapshot)
        if not query:
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_NO_HIT, query=query)

        started = time.perf_counter()
        try:
            grounding = await asyncio.wait_for(
                self._retrieve_with_query(snapshot, query),
                timeout=max(0.5, float(settings.interview.knowledge_grounding_timeout_seconds)),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Knowledge grounding 超时，降级 ERROR: session=%s, turn=%s",
                snapshot.session_id,
                snapshot.turn.id,
            )
            return KnowledgeGroundingDTO(
                status=KNOWLEDGE_GROUNDING_ERROR,
                query=query,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_type="TimeoutError",
            )
        except Exception as exc:  # embedding / DB / rerank / 任何未知异常
            logger.warning(
                "Knowledge grounding 失败，降级 ERROR: session=%s, turn=%s, error=%s",
                snapshot.session_id,
                snapshot.turn.id,
                exc,
            )
            return KnowledgeGroundingDTO(
                status=KNOWLEDGE_GROUNDING_ERROR,
                query=query,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_type=exc.__class__.__name__,
            )

        grounding.latency_ms = int((time.perf_counter() - started) * 1000)
        return grounding

    # ----------------------------------------------------------------- internal

    async def _retrieve_with_query(self, snapshot: EvaluationSnapshot, query: str) -> KnowledgeGroundingDTO:
        # ---- G1：embedding（0 DB transaction）----
        # embed_text 是同步接口（可能含网络调用），放到线程里，且必须在打开
        # AsyncSession transaction 之前完成。
        query_embedding = await asyncio.to_thread(self._vector_service().embed_text, query)

        # ---- G2：独立短 DB read session → materialize plain DTO → 关闭 ----
        candidates, has_source = await self._fetch_candidates(snapshot.user_id, query_embedding)
        if not has_source:
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_NO_SOURCE, query=query)
        if not candidates:
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_NO_HIT, query=query)

        # ---- G3：rerank（0 DB transaction，DB session 已关闭）----
        ranked, method = await self._rerank_candidates(query, candidates)

        threshold = float(settings.interview.knowledge_grounding_min_score)
        top_k = max(1, int(settings.interview.knowledge_grounding_top_k))
        kept = [item for item in ranked if item.score >= threshold][:top_k]
        if not kept:
            # precision first：全部低于阈值就 NO_HIT，**不**强行找「最像」的一条给 evaluator
            return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_NO_HIT, query=query)

        references: list[KnowledgeEvidenceRefDTO] = []
        for index, item in enumerate(kept):
            references.append(item.model_copy(update={"rank": index + 1, "retrieval_method": method}))
        return KnowledgeGroundingDTO(
            status=KNOWLEDGE_GROUNDING_READY,
            query=query,
            references=references,
            retrieval_confidence=round(max(item.score for item in references), 4),
        )

    async def _fetch_candidates(
        self, user_id: int, query_embedding: list[float]
    ) -> tuple[list[KnowledgeEvidenceRefDTO], bool]:
        """独立短 read session：user-scoped 检索 + JOIN，一次性取回 KB 名称（避免 N+1）。

        **任何 evidence 只能来自当前 session.user_id 的 KB。**
        """
        from app.common.model import AsyncTaskStatus
        from app.database import get_db_context
        from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity

        candidate_k = max(1, int(settings.interview.knowledge_grounding_candidate_k))

        async with get_db_context() as db:
            source_stmt = select(KnowledgeBaseEntity.id).where(
                KnowledgeBaseEntity.user_id == user_id,
                KnowledgeBaseEntity.index_status == AsyncTaskStatus.COMPLETED,
            )
            source_ids = list((await db.execute(source_stmt)).scalars().all())
            if not source_ids:
                return [], False

            stmt = (
                select(
                    KnowledgeChunkEntity.id,
                    KnowledgeChunkEntity.knowledge_base_id,
                    KnowledgeChunkEntity.title,
                    KnowledgeChunkEntity.content,
                    KnowledgeChunkEntity.embedding,
                    KnowledgeBaseEntity.name,
                )
                .join(KnowledgeBaseEntity, KnowledgeChunkEntity.knowledge_base_id == KnowledgeBaseEntity.id)
                .where(KnowledgeBaseEntity.user_id == user_id)
                .where(KnowledgeBaseEntity.index_status == AsyncTaskStatus.COMPLETED)
                .where(KnowledgeChunkEntity.embedding.isnot(None))
                .order_by(KnowledgeChunkEntity.embedding.cosine_distance(query_embedding))
                .limit(candidate_k)
            )
            rows = list((await db.execute(stmt)).all())

        candidates: list[KnowledgeEvidenceRefDTO] = []
        for chunk_id, kb_id, title, content, embedding, kb_name in rows:
            text = content or ""
            if not text.strip():
                continue
            digest = content_hash_of(text)
            candidates.append(
                KnowledgeEvidenceRefDTO(
                    evidence_id=_evidence_id(int(kb_id), int(chunk_id), digest),
                    knowledge_base_id=int(kb_id),
                    chunk_id=int(chunk_id),
                    source_name=str(kb_name or f"KB#{kb_id}"),
                    title=title or None,
                    # 直接截断，不做 LLM summarize（summary 会再引入一层 hallucination）
                    content_excerpt=text[:MAX_KNOWLEDGE_EXCERPT_CHARS],
                    score=self._cosine_score(query_embedding, embedding),
                    rank=0,
                    content_hash=digest,
                    retrieval_method="VECTOR",
                )
            )
        return self._deduplicate(candidates), True

    async def _rerank_candidates(
        self, query: str, candidates: list[KnowledgeEvidenceRefDTO]
    ) -> tuple[list[KnowledgeEvidenceRefDTO], str]:
        """rerank 只对 plain DTO 操作（DB session 已关闭）。reranker 不可用不算 ERROR。"""
        rerank = self._rerank_service()
        if rerank is None or not getattr(rerank, "enabled", False):
            # reranker disabled / 模型缺失 → 按 vector score 排序，**不是** ERROR
            return self._stable_sort(candidates), "VECTOR"

        from app.modules.knowledge_base.schemas import RagReferenceDTO

        payload = [
            RagReferenceDTO(
                chunk_id=item.chunk_id,
                chunk_index=0,
                title=item.title or "",
                content=item.content_excerpt,
                content_preview=item.content_excerpt[:200],
                score=item.score,
                source_name=item.source_name,
            )
            for item in candidates
        ]
        reranked = await rerank.rerank(query, payload, len(candidates))
        by_chunk = {item.chunk_id: item for item in candidates}
        merged: list[KnowledgeEvidenceRefDTO] = []
        seen: set[int] = set()
        for item in reranked:
            original = by_chunk.get(item.chunk_id)
            if original is None or item.chunk_id in seen:
                continue
            seen.add(item.chunk_id)
            merged.append(original.model_copy(update={"score": round(float(item.score), 4)}))
        if not merged:
            return self._stable_sort(candidates), "VECTOR"
        return self._stable_sort(merged), "VECTOR_RERANK"

    # ------------------------------------------------------------------ helpers

    def _vector_service(self):
        if self._vector is None:
            from app.modules.knowledge_base.vector_service import knowledge_base_vector_service

            self._vector = knowledge_base_vector_service
        return self._vector

    def _rerank_service(self):
        if self._rerank is None:
            try:
                from app.modules.knowledge_base.rerank_service import get_rerank_service

                self._rerank = get_rerank_service()
            except Exception:  # pragma: no cover - 模型缺失时降级为纯向量
                self._rerank = False
        return None if self._rerank is False else self._rerank

    @staticmethod
    def _cosine_score(query_embedding: list[float], chunk_embedding) -> float:
        """retrieval relevance = cosine similarity（越大越相关）。

        这是 **retrieval relevance**，**不是** truth probability：0.91 只表示
        「这条 chunk 与问题更相关」，绝不表示「事实正确率 91%」。

        注意：SQL 侧用 pgvector 的 ``cosine_distance``（= 1 - similarity）排序取最近邻，
        因此 Python 侧必须换算回 similarity 才能与 ``min_score`` 阈值同一量纲。
        """
        if chunk_embedding is None:
            return 0.0
        left = list(query_embedding or [])
        right = list(chunk_embedding)
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        dot = sum(left[i] * right[i] for i in range(size))
        left_norm = sum(left[i] * left[i] for i in range(size)) ** 0.5
        right_norm = sum(right[i] * right[i] for i in range(size)) ** 0.5
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    @staticmethod
    def _deduplicate(items: list[KnowledgeEvidenceRefDTO]) -> list[KnowledgeEvidenceRefDTO]:
        """按 (knowledge_base_id, chunk_id) 去重，同 chunk 只保留最高分。"""
        best: dict[tuple[int, int], KnowledgeEvidenceRefDTO] = {}
        for item in items:
            key = (item.knowledge_base_id, item.chunk_id)
            current = best.get(key)
            if current is None or item.score > current.score:
                best[key] = item
        return list(best.values())

    @staticmethod
    def _stable_sort(items: list[KnowledgeEvidenceRefDTO]) -> list[KnowledgeEvidenceRefDTO]:
        """score desc → knowledge_base_id → chunk_id（deterministic）。"""
        return sorted(items, key=lambda item: (-item.score, item.knowledge_base_id, item.chunk_id))


knowledge_grounding_service = KnowledgeGroundingService()
