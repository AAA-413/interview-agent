from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.interview.schemas import StructuredJD
from app.modules.interview.topic_registry import topic_registry_service


@dataclass(frozen=True)
class _SkillRule:
    skill: str
    topic_hint: str
    aliases: tuple[str, ...]


SKILL_RULES: tuple[_SkillRule, ...] = (
    _SkillRule(
        "Python", "FastAPI Python asyncio SQLAlchemy", ("python", "fastapi", "django", "flask", "sqlalchemy", "asyncio")
    ),
    _SkillRule("Java", "Java Spring JVM MyBatis", ("java", "spring", "spring boot", "mybatis", "jvm")),
    _SkillRule("React", "React 状态管理 Hooks Redux Zustand", ("react", "hooks", "redux", "zustand")),
    _SkillRule("Vue", "Vue 状态管理 Pinia Vuex", ("vue", "pinia", "vuex")),
    _SkillRule("TypeScript", "TypeScript 类型设计", ("typescript", "ts ", "类型设计")),
    _SkillRule("Redis", "Redis 缓存一致性 Streams 分布式锁", ("redis", "缓存", "hotkey", "streams", "分布式锁")),
    _SkillRule("MySQL", "MySQL 索引优化 事务隔离 SQL 查询优化", ("mysql", "索引", "事务", "sql")),
    _SkillRule("消息队列", "消息队列可靠性 MQ", ("消息队列", "mq", "kafka", "rabbitmq", "rocketmq")),
    _SkillRule(
        "RAG", "RAG 多通道检索 BM25 向量检索 Cross-Encoder", ("rag", "检索增强", "多通道检索", "多路召回", "bm25")
    ),
    _SkillRule("Embedding", "Embedding 向量检索 pgvector", ("embedding", "向量", "vector", "pgvector")),
    _SkillRule("MCP", "MCP 工具集成", ("mcp", "model context protocol")),
    _SkillRule(
        "Agent", "Agent 规划 执行 多 Agent 工具选择", ("agent", "智能体", "multi-agent", "多 agent", "规划执行")
    ),
    _SkillRule("Prompt", "Prompt 工程 结构化输出", ("prompt", "提示词", "结构化输出")),
    _SkillRule("LLM", "LLM 应用 上下文 成本 评估", ("llm", "大模型", "模型应用", "function calling", "tool calling")),
    _SkillRule("微调", "LoRA QLoRA SFT DPO RLHF", ("微调", "lora", "qlora", "sft", "dpo", "rlhf")),
    _SkillRule("系统设计", "高并发 可扩展 高可用 系统设计", ("系统设计", "高并发", "高可用", "可扩展", "容量")),
)

SENIORITY_KEYWORDS = {
    "intern": ("实习", "intern", "校招", "应届", "学生"),
    "junior": ("初级", "1年", "1-2年", "junior", "助理"),
    "mid": ("中级", "2年", "3年", "3-5年", "mid"),
    "senior": ("高级", "资深", "5年", "专家", "架构师", "senior", "lead"),
}


class JDParseService:
    def parse(self, jd_text: str | None, target_role: str | None = None, skill_id: str | None = None) -> StructuredJD:
        raw_jd = (jd_text or "").strip()
        role = (target_role or "").strip()
        combined = f"{role}\n{raw_jd}".strip()
        normalized = combined.lower()

        required_skills, preferred_skills = self._extract_skills(normalized)
        responsibilities = self._extract_responsibilities(raw_jd)
        role_domain = self._detect_role_domain(normalized, skill_id)
        seniority = self._detect_seniority(normalized)
        quality_score, quality_level, missing_parts = self._quality_score(
            raw_jd=raw_jd,
            target_role=role,
            required_skills=required_skills,
            responsibilities=responsibilities,
            role_domain=role_domain,
            seniority=seniority,
        )
        topic_weights = self._topic_weights(
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            responsibilities=responsibilities,
            role_domain=role_domain,
            quality_score=quality_score,
            target_role=role,
            skill_id=skill_id,
        )

        return StructuredJD(
            raw_jd=raw_jd,
            quality_score=quality_score,
            quality_level=quality_level,
            missing_parts=missing_parts,
            user_suggestion=self._user_suggestion(missing_parts),
            role_title=role or self._infer_role_title(raw_jd, role_domain),
            role_domain=role_domain,
            seniority=seniority,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            responsibilities=responsibilities,
            domain_keywords=self._domain_keywords(role_domain, required_skills),
            topic_weights=topic_weights,
            question_type_mix=self._question_type_mix(role_domain, seniority),
        )

    @staticmethod
    def _extract_skills(normalized_text: str) -> tuple[list[str], list[str]]:
        required: list[str] = []
        preferred: list[str] = []
        for rule in SKILL_RULES:
            if any(alias.lower() in normalized_text for alias in rule.aliases):
                target = preferred if JDParseService._is_preferred_context(normalized_text, rule.aliases) else required
                if rule.skill not in target:
                    target.append(rule.skill)
        return required, preferred

    @staticmethod
    def _is_preferred_context(normalized_text: str, aliases: tuple[str, ...]) -> bool:
        for alias in aliases:
            idx = normalized_text.find(alias.lower())
            if idx < 0:
                continue
            window = normalized_text[max(0, idx - 16) : idx + len(alias) + 16]
            if any(token in window for token in ["优先", "加分", "preferred", "bonus", "plus"]):
                return True
        return False

    @staticmethod
    def _extract_responsibilities(raw_jd: str) -> list[str]:
        if not raw_jd:
            return []
        parts = re.split(r"[。；;\n]", raw_jd)
        responsibilities = []
        markers = ("负责", "参与", "建设", "设计", "开发", "优化", "维护", "落地", "推进", "构建")
        for part in parts:
            item = part.strip(" -\t\r")
            if len(item) < 6:
                continue
            if any(marker in item for marker in markers):
                responsibilities.append(item[:120])
        return responsibilities[:8]

    @staticmethod
    def _detect_role_domain(normalized_text: str, skill_id: str | None) -> str:
        text = f"{skill_id or ''} {normalized_text}".lower()
        if any(k in text for k in ["微调", "finetune", "lora", "qlora", "sft", "dpo", "rlhf"]):
            return "llm_finetuning_rl"
        if any(k in text for k in ["agent", "智能体", "mcp", "multi-agent", "工具调用"]):
            return "ai_agent"
        if any(k in text for k in ["llm", "rag", "大模型", "prompt", "embedding", "向量"]):
            return "llm_application"
        if any(k in text for k in ["前端", "frontend", "react", "vue", "typescript"]):
            return "frontend"
        if any(k in text for k in ["java", "spring", "jvm", "mybatis"]):
            return "java_backend"
        if any(k in text for k in ["python", "fastapi", "django", "flask"]):
            return "python_backend"
        if any(k in text for k in ["后端", "backend", "服务端", "数据库", "redis", "mysql"]):
            return "backend_common"
        return "common_engineering"

    @staticmethod
    def _detect_seniority(normalized_text: str) -> str:
        for level, keywords in SENIORITY_KEYWORDS.items():
            if any(keyword in normalized_text for keyword in keywords):
                return level
        return "unknown"

    @staticmethod
    def _quality_score(
        raw_jd: str,
        target_role: str,
        required_skills: list[str],
        responsibilities: list[str],
        role_domain: str,
        seniority: str,
    ) -> tuple[int, str, list[str]]:
        missing: list[str] = []
        score = 0

        if target_role or re.search(r"(岗位|工程师|开发|实习生|架构师|专家)", raw_jd):
            score += 20
        else:
            missing.append("缺少明确岗位名")

        if len(required_skills) >= 4:
            score += 30
        elif len(required_skills) >= 2:
            score += 22
        elif required_skills:
            score += 12
        else:
            missing.append("缺少具体技术栈")

        if len(responsibilities) >= 3:
            score += 24
        elif responsibilities:
            score += 14
        else:
            missing.append("缺少岗位职责")

        if seniority != "unknown":
            score += 12
        else:
            missing.append("无法判断等级")

        if role_domain != "common_engineering":
            score += 14
        else:
            missing.append("岗位方向信号不足")

        if len(raw_jd) < 30:
            score = min(score, 42)
            if "JD 内容过短" not in missing:
                missing.append("JD 内容过短")
        elif len(raw_jd) < 80:
            score = min(score + 4, 65)

        score = max(0, min(score, 100))
        if score >= 75:
            level = "HIGH"
        elif score >= 50:
            level = "MEDIUM"
        else:
            level = "LOW"
        return score, level, missing[:5]

    def _topic_weights(
        self,
        required_skills: list[str],
        preferred_skills: list[str],
        responsibilities: list[str],
        role_domain: str,
        quality_score: int,
        target_role: str,
        skill_id: str | None,
    ) -> dict[str, float]:
        weights: dict[str, float] = {}
        quality_multiplier = 1.0 if quality_score >= 75 else 0.78 if quality_score >= 50 else 0.55
        skill_to_hint = {rule.skill: rule.topic_hint for rule in SKILL_RULES}
        skill_to_topics = {
            "RAG": ("rag_multi_channel_retrieval",),
            "MCP": ("mcp_tool_integration",),
            "Redis": ("redis_cache_penetration_hotkey", "redis_cache_consistency"),
            "MySQL": ("mysql_index_optimization",),
            "React": ("react_state_management",),
            "TypeScript": ("typescript_type_design",),
            "微调": ("lora_qlora_finetuning", "dpo_preference_optimization"),
        }

        for skill in required_skills:
            for topic_key in skill_to_topics.get(skill, ()):
                self._merge_weight(weights, topic_key, 0.88)
            hint = skill_to_hint.get(skill, skill)
            result = topic_registry_service.normalize(
                raw_topic=hint,
                evidence_snippet=" ".join(responsibilities),
                question_type="KNOWLEDGE",
                target_role=target_role,
                skill_id=skill_id,
                role_domain=role_domain,
            )
            self._merge_weight(weights, result.topic_key, 0.9 * quality_multiplier)

        for skill in preferred_skills:
            hint = skill_to_hint.get(skill, skill)
            result = topic_registry_service.normalize(
                raw_topic=hint,
                evidence_snippet=" ".join(responsibilities),
                question_type="KNOWLEDGE",
                target_role=target_role,
                skill_id=skill_id,
                role_domain=role_domain,
            )
            self._merge_weight(weights, result.topic_key, 0.72 * quality_multiplier)

        for responsibility in responsibilities:
            lowered_responsibility = responsibility.lower()
            if "性能优化" in responsibility and role_domain == "frontend":
                self._merge_weight(weights, "frontend_performance_optimization", 0.86)
            if "任务队列" in responsibility or "异步任务" in responsibility:
                self._merge_weight(weights, "async_task_pipeline", 0.86)
            if "幂等" in responsibility:
                self._merge_weight(weights, "idempotency_design", 0.86)
            if "redis streams" in lowered_responsibility:
                self._merge_weight(weights, "async_task_pipeline", 0.88)
            result = topic_registry_service.normalize(
                raw_topic=responsibility,
                evidence_snippet=responsibility,
                question_type="PROJECT",
                target_role=target_role,
                skill_id=skill_id,
                role_domain=role_domain,
            )
            if result.fallback_reason is None:
                self._merge_weight(weights, result.topic_key, 0.68 * quality_multiplier)

        if not weights and role_domain != "common_engineering":
            fallback_pack = {
                "ai_agent": "agent_planning_execution",
                "llm_application": "rag_multi_channel_retrieval",
                "llm_finetuning_rl": "sft_data_preparation",
                "java_backend": "spring_ioc_aop",
                "python_backend": "fastapi_request_lifecycle",
                "frontend": "react_state_management",
                "backend_common": "api_design_contract",
            }
            self._merge_weight(weights, fallback_pack.get(role_domain, "technical_tradeoff_analysis"), 0.5)

        return dict(sorted(weights.items(), key=lambda item: item[1], reverse=True)[:12])

    @staticmethod
    def _merge_weight(weights: dict[str, float], topic_key: str, value: float) -> None:
        weights[topic_key] = round(max(weights.get(topic_key, 0.0), min(value, 0.98)), 2)

    @staticmethod
    def _question_type_mix(role_domain: str, seniority: str) -> dict[str, float]:
        mixes = {
            "ai_agent": {"project": 0.5, "knowledge": 0.25, "system_design": 0.25},
            "llm_application": {"project": 0.5, "knowledge": 0.25, "system_design": 0.25},
            "llm_finetuning_rl": {"project": 0.4, "knowledge": 0.4, "system_design": 0.2},
            "java_backend": {"project": 0.45, "knowledge": 0.35, "system_design": 0.2},
            "python_backend": {"project": 0.45, "knowledge": 0.3, "system_design": 0.25},
            "frontend": {"project": 0.5, "knowledge": 0.3, "system_design": 0.2},
        }
        mix = dict(mixes.get(role_domain, {"project": 0.45, "knowledge": 0.3, "system_design": 0.25}))
        if seniority in {"intern", "junior"}:
            mix["knowledge"] = round(mix["knowledge"] + 0.08, 2)
            mix["system_design"] = round(max(0.15, mix["system_design"] - 0.08), 2)
        elif seniority == "senior":
            mix["system_design"] = round(mix["system_design"] + 0.1, 2)
            mix["knowledge"] = round(max(0.2, mix["knowledge"] - 0.1), 2)
        total = sum(mix.values())
        return {key: round(value / total, 2) for key, value in mix.items()}

    @staticmethod
    def _infer_role_title(raw_jd: str, role_domain: str) -> str:
        for line in raw_jd.splitlines():
            line = line.strip(" -：:")
            if 2 <= len(line) <= 40 and any(
                token in line for token in ["开发", "工程师", "实习", "架构", "Agent", "LLM"]
            ):
                return line
        labels = {
            "ai_agent": "AI Agent 开发",
            "llm_application": "LLM 应用开发",
            "llm_finetuning_rl": "LLM 微调工程",
            "java_backend": "Java 后端开发",
            "python_backend": "Python 后端开发",
            "frontend": "前端开发",
            "backend_common": "后端开发",
        }
        return labels.get(role_domain, "技术开发")

    @staticmethod
    def _domain_keywords(role_domain: str, required_skills: list[str]) -> list[str]:
        defaults = {
            "ai_agent": ["Agent", "MCP", "工具调用", "任务规划"],
            "llm_application": ["LLM", "RAG", "Embedding", "Prompt"],
            "llm_finetuning_rl": ["SFT", "LoRA", "DPO", "RLHF"],
            "java_backend": ["Java", "Spring", "MySQL", "Redis"],
            "python_backend": ["Python", "FastAPI", "SQLAlchemy", "异步"],
            "frontend": ["React", "Vue", "TypeScript", "状态管理"],
            "backend_common": ["API", "数据库", "缓存", "可靠性"],
        }
        merged = list(dict.fromkeys(required_skills + defaults.get(role_domain, [])))
        return merged[:8]

    @staticmethod
    def _user_suggestion(missing_parts: list[str]) -> str | None:
        if not missing_parts:
            return None
        return "建议补充：" + "、".join(missing_parts) + "，这样面试策略会更贴近目标岗位。"


jd_parse_service = JDParseService()
