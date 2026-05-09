import json
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.modules.knowledge_graph.persistence_service import knowledge_graph_persistence_service

logger = logging.getLogger(__name__)

EXTRACT_SYSTEM_PROMPT = """你是知识图谱抽取助手。从文本中提取实体和关系三元组。

实体类型枚举：
- 技术：编程语言、数据库、中间件、协议等（如 Redis、MySQL、Java、HTTP）
- 概念：抽象概念、设计理念、架构模式（如 缓存、微服务、事务、CAP理论）
- 工具：开发工具、运维工具（如 Docker、Git、Maven）
- 框架：应用框架、库（如 Spring Boot、MyBatis、React）
- 公司：企业、组织（如 阿里巴巴、字节跳动）
- 人：技术人物（如 Linus Torvalds、Martin Fowler）
- 面试题：具体的面试问题类型（如 系统设计题、算法题）

关系类型枚举：
- 属于：A 是 B 的一种（Redis 属于 缓存技术）
- 使用：A 使用 B（Spring Boot 使用 Tomcat）
- 前置知识：学 A 之前要先学 B（Spring Boot 前置知识 Spring Core）
- 常配合：A 和 B 经常一起使用（Redis 常配合 MySQL）
- 包含：A 包含 B（Spring Cloud 包含 Gateway）
- 解决：A 解决 B 问题（Redis 解决 缓存穿透）
- 对比：A 和 B 是对比关系（Redis 对比 Memcached）
- 优缺点：A 的某个优缺点（Redis 优缺点 持久化支持）
- 适用场景：A 适用于 B（Redis 适用场景 高并发读写）

规则：
1. 只提取文本中明确陈述的关系，不要推断或编造
2. 实体名称用最常用的简称（如 "Redis" 而非 "Remote Dictionary Server"）
3. 同义实体统一为一个名称
4. 每个三元组必须包含 subject、predicate、object、subject_type、object_type
5. 输出纯 JSON 数组，不要任何其他文字、解释或 markdown 标记"""

EXTRACT_USER_PROMPT = """从以下文本中提取知识图谱三元组：

{text}

直接输出 JSON 数组，格式：
[{{"subject": "...", "predicate": "...", "object": "...", "subject_type": "...", "object_type": "..."}}]

如果没有可提取的三元组，输出空数组：[]"""


class KnowledgeGraphExtractionService:

    async def extract_and_save(self, db: AsyncSession, kb_id: int, source_text: str) -> dict:
        start = time.time()

        await knowledge_graph_persistence_service.clear_by_kb_id(db, kb_id)

        segments = self._split_text(source_text, max_length=2000)
        logger.info("知识图谱抽取开始: kb_id=%d, segments=%d", kb_id, len(segments))

        all_triples: list[dict] = []
        for i, segment in enumerate(segments):
            try:
                triples = await self._extract_from_segment(segment)
                all_triples.extend(triples)
                logger.debug("段落 %d/%d 抽取: %d 个三元组", i + 1, len(segments), len(triples))
            except Exception as e:
                logger.warning("段落 %d/%d 抽取失败: %s", i + 1, len(segments), e)

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
            )
            if triple:
                triple_count += 1

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "知识图谱抽取完成: kb_id=%d, entities=%d, triples=%d, duration=%dms",
            kb_id, entity_count, triple_count, duration_ms,
        )
        return {"kb_id": kb_id, "entity_count": entity_count, "triple_count": triple_count, "duration_ms": duration_ms}

    async def _extract_from_segment(self, text: str) -> list[dict]:
        messages = [
            SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
            HumanMessage(content=EXTRACT_USER_PROMPT.format(text=text)),
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
                    valid.append({
                        "subject": str(t["subject"]).strip(),
                        "predicate": str(t["predicate"]).strip(),
                        "object": str(t["object"]).strip(),
                        "subject_type": str(t["subject_type"]).strip(),
                        "object_type": str(t["object_type"]).strip(),
                    })
            return valid
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("LLM 输出解析失败: %s, content=%s", e, content[:200])
            return []

    @staticmethod
    def _clean_json_response(content: str) -> str:
        if content.startswith("```"):
            lines = content.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1:
            content = content[start:end + 1]
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
