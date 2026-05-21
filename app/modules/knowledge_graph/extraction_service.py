import json
import logging
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class KnowledgeGraphExtractionService:
    def __init__(self) -> None:
        self._system_prompt: str | None = None
        self._user_prompt_template: str | None = None

    def _load_prompts(self) -> tuple[str, str]:
        if self._system_prompt is None:
            self._system_prompt = (PROMPT_DIR / "kg-extraction-system.md").read_text(encoding="utf-8")
        if self._user_prompt_template is None:
            self._user_prompt_template = (PROMPT_DIR / "kg-extraction-user.md").read_text(encoding="utf-8")
        return self._system_prompt, self._user_prompt_template

    async def extract_and_save(
        self,
        db: AsyncSession,
        kb_id: int,
        source_text: str,
        chunks: list | None = None,
    ) -> dict:
        start = time.time()

        system_prompt, user_prompt_template = self._load_prompts()

        await knowledge_graph_persistence_service.clear_by_kb_id(db, kb_id)

        # 优先按 chunk 提取（记录 source_chunk_id），否则回退到 _split_text
        if chunks:
            segments_with_id = [(chunk.id, chunk.content or "") for chunk in chunks if (chunk.content or "").strip()]
            logger.info("知识图谱抽取开始: kb_id=%d, chunks=%d (按chunk提取)", kb_id, len(segments_with_id))
        else:
            segments_with_id = [(None, seg) for seg in self._split_text(source_text, max_length=2000)]
            logger.info("知识图谱抽取开始: kb_id=%d, segments=%d (按段落提取)", kb_id, len(segments_with_id))

        all_triples: list[dict] = []
        for i, (chunk_id, segment) in enumerate(segments_with_id):
            try:
                triples = await self._extract_from_segment(segment, system_prompt, user_prompt_template)
                for t in triples:
                    t["_source_chunk_id"] = chunk_id
                all_triples.extend(triples)
                logger.debug("段落 %d/%d 抽取: %d 个三元组", i + 1, len(segments_with_id), len(triples))
            except Exception as e:
                logger.warning("段落 %d/%d 抽取失败: %s", i + 1, len(segments_with_id), e)

        unique = self._deduplicate(all_triples)
        logger.info("去重: %d → %d 个三元组", len(all_triples), len(unique))

        entity_count = 0
        triple_count = 0
        entities_cache: dict[str, int] = {}

        for t in unique:
            subject_key = f"{t['subject']}:{t['subject_type']}"
            object_key = f"{t['object']}:{t['object_type']}"

            if subject_key not in entities_cache:
                subj_entity = await knowledge_graph_persistence_service.find_or_create_entity(
                    db, t["subject"], t["subject_type"]
                )
                entities_cache[subject_key] = subj_entity.id
                entity_count += 1

            if object_key not in entities_cache:
                obj_entity = await knowledge_graph_persistence_service.find_or_create_entity(
                    db, t["object"], t["object_type"]
                )
                entities_cache[object_key] = obj_entity.id
                entity_count += 1

            triple = await knowledge_graph_persistence_service.create_triple(
                db,
                subject_id=entities_cache[subject_key],
                predicate=t["predicate"],
                object_id=entities_cache[object_key],
                source_kb_id=kb_id,
                source_chunk_id=t.get("_source_chunk_id"),
            )
            if triple:
                triple_count += 1

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "知识图谱抽取完成: kb_id=%d, entities=%d, triples=%d, duration=%dms",
            kb_id,
            entity_count,
            triple_count,
            duration_ms,
        )
        return {"kb_id": kb_id, "entity_count": entity_count, "triple_count": triple_count, "duration_ms": duration_ms}

    async def _extract_from_segment(self, text: str, system_prompt: str, user_prompt_template: str) -> list[dict]:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt_template.format(text=text)),
        ]

        response = await llm_registry.default.ainvoke(messages)
        content = (response.content or "").strip() if hasattr(response, "content") else ""

        content = self._clean_json_response(content)

        try:
            triples = json.loads(content)
            if not isinstance(triples, list):
                return []
            valid = []
            for t in triples:
                if all(k in t for k in ("subject", "predicate", "object", "subject_type", "object_type")):
                    valid.append(
                        {
                            "subject": str(t["subject"]).strip(),
                            "predicate": str(t["predicate"]).strip(),
                            "object": str(t["object"]).strip(),
                            "subject_type": str(t["subject_type"]).strip(),
                            "object_type": str(t["object_type"]).strip(),
                        }
                    )
            return valid
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("LLM 输出解析失败: %s, content=%s", e, content[:200])
            return []

    @staticmethod
    def _clean_json_response(content: str) -> str:
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            content = "\n".join(lines)
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            content = content[start : end + 1]
        return content.strip()

    @staticmethod
    def _split_text(text: str, max_length: int = 2000) -> list[str]:
        if not text:
            return []
        if len(text) <= max_length:
            return [text]

        segments = []
        paragraphs = text.split("\n\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > max_length:
                if current:
                    segments.append(current.strip())
                current = para
            else:
                current = current + "\n\n" + para if current else para
        if current:
            segments.append(current.strip())

        return [s for s in segments if s]

    @staticmethod
    def _deduplicate(triples: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for t in triples:
            key = (t["subject"], t["predicate"], t["object"])
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique


knowledge_graph_extraction_service = KnowledgeGraphExtractionService()
