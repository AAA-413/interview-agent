from __future__ import annotations

import hashlib
import inspect
import logging
import re
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_persistence_service import safe_json_loads
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.model import AsyncTaskStatus
from app.config import settings
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service
from app.modules.interview.jd_parse_service import jd_parse_service
from app.modules.interview.models import (
    DecisionAction,
    InterviewMode,
    InterviewSessionEntity,
    InterviewTopicEntity,
    InterviewTurnEntity,
    SessionStatus,
    TopicStatus,
    TurnType,
)
from app.modules.interview.schemas import (
    DynamicDecisionDTO,
    DynamicInterviewCreateRequest,
    DynamicInterviewCreateResponse,
    DynamicRagCitationDTO,
    DynamicReportDTO,
    DynamicSessionDetailDTO,
    DynamicTopicDTO,
    DynamicTopicRagInsightDTO,
    DynamicTopicSummaryDTO,
    DynamicTurnAnswerResponse,
    DynamicTurnDTO,
    DynamicTurnEvaluationDTO,
    SubmitDynamicTurnAnswerRequest,
    TomorrowTaskDTO,
)
from app.modules.interview.topic_registry import TopicDef, topic_registry_service
from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity
from app.modules.knowledge_base.persistence_service import knowledge_base_persistence_service
from app.modules.resume.history_service import resume_history_service
from app.modules.resume.schemas import ProjectInfo, ResumeDetailDTO, ResumeProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TopicCandidate:
    topic: TopicDef
    question_type: str
    evidence: str | None
    source_type: str
    weight: float


class InterviewPlanService:
    def build_plan(
        self,
        request: DynamicInterviewCreateRequest,
        structured_jd,
        resume_detail: ResumeDetailDTO | None,
        mode: str = InterviewMode.COACH.value,
        recent_topic_keys: list[dict] | None = None,
        user_topic_profile: dict | None = None,
        variation_seed: str | None = None,
    ) -> tuple[list[DynamicTopicDTO], dict]:
        target_role = request.target_role or structured_jd.role_title or "目标技术岗位"
        seed = variation_seed or target_role
        profile = self._latest_profile(resume_detail)
        recent_keys = {item["topic_key"] for item in (recent_topic_keys or [])}
        low_score_keys = set(user_topic_profile.get("low_score_topics", []) if user_topic_profile else [])

        project_candidates = self._project_candidates(profile, structured_jd, target_role, request.skill_id)
        knowledge_candidate = self._knowledge_candidate(
            structured_jd, target_role, request.skill_id, project_candidates
        )
        system_candidate = self._system_design_candidate(structured_jd.role_domain, target_role)

        self._apply_dedup(project_candidates, recent_keys, low_score_keys)
        self._apply_dedup([knowledge_candidate], recent_keys, low_score_keys)

        selected = self._select_project_candidates(project_candidates, limit=2, variation_seed=seed) + [
            knowledge_candidate,
            system_candidate,
        ]
        selected = self._ensure_four_topics(selected, target_role)
        topics = [
            self._candidate_to_topic(
                candidate=candidate,
                order=index + 1,
                target_role=target_role,
                active=index == 0,
                variation_seed=seed,
            )
            for index, candidate in enumerate(selected[:4])
        ]
        plan_summary = {
            "topic_count": len(topics),
            "mode": mode,
            "target_role": target_role,
            "role_domain": structured_jd.role_domain,
            "jd_quality_score": structured_jd.quality_score,
            "topic_weights": structured_jd.topic_weights,
            "question_type_mix": {"PROJECT": 2, "KNOWLEDGE": 1, "SYSTEM_DESIGN": 1},
            "dedup_applied": bool(recent_keys),
            "recent_topic_keys": sorted(recent_keys),
            "low_score_retry_topics": sorted(low_score_keys),
            "variation_seed": seed,
            "topics": [
                {
                    "topic_key": topic.topic_key,
                    "topic_title": topic.topic_title,
                    "question_type": topic.question_type,
                    "source_type": topic.source_type,
                }
                for topic in topics
            ],
        }
        return topics, plan_summary

    @staticmethod
    def _latest_profile(resume_detail: ResumeDetailDTO | None) -> ResumeProfile | None:
        if not resume_detail or not resume_detail.analyses:
            return None
        latest = max(resume_detail.analyses, key=lambda item: item.analyzed_at)
        return latest.profile

    def _project_candidates(
        self,
        profile: ResumeProfile | None,
        structured_jd,
        target_role: str,
        skill_id: str | None,
    ) -> list[_TopicCandidate]:
        projects = profile.projects if profile and profile.projects else []
        candidates: list[_TopicCandidate] = []

        for project in projects[:4]:
            evidence = self._project_evidence(project)
            normalized = topic_registry_service.normalize(
                raw_topic=" ".join(project.tech_stack) or project.description,
                evidence_snippet=evidence,
                question_type="PROJECT",
                target_role=target_role,
                skill_id=skill_id,
                role_domain=structured_jd.role_domain,
            )
            topic = topic_registry_service.get_topic(normalized.topic_key)
            if topic is None or normalized.fallback_reason:
                topic = topic_registry_service.get_topic("project_role_ownership")
            elif topic.topic_key == "multi_agent_collaboration" and not self._has_multi_agent_evidence(evidence):
                topic = None
            if topic:
                candidates.append(
                    _TopicCandidate(
                        topic=topic,
                        question_type="PROJECT",
                        evidence=evidence,
                        source_type="resume",
                        weight=structured_jd.topic_weights.get(topic.topic_key, 0.52) + 0.12,
                    )
                )

            evidence_lower = evidence.lower()
            for topic_key, weight in structured_jd.topic_weights.items():
                weighted_topic = topic_registry_service.get_topic(topic_key)
                if weighted_topic is None or "PROJECT" not in weighted_topic.supported_question_types:
                    continue
                if weighted_topic.skill_key in {"typescript", "fastapi"}:
                    continue
                aliases = (
                    weighted_topic.topic_key,
                    weighted_topic.label,
                    weighted_topic.skill_key,
                    *weighted_topic.aliases,
                )
                if not any(alias and alias.lower() in evidence_lower for alias in aliases):
                    continue
                candidates.append(
                    _TopicCandidate(
                        topic=weighted_topic,
                        question_type="PROJECT",
                        evidence=evidence,
                        source_type="resume",
                        weight=min(weight + 0.18, 1.0),
                    )
                )

            evidence_priority_topics = (
                "frontend_performance_optimization",
                "async_task_pipeline",
                "idempotency_design",
                "redis_cache_penetration_hotkey",
                "mysql_index_optimization",
                "mcp_tool_integration",
            )
            for topic_key in evidence_priority_topics:
                priority_topic = topic_registry_service.get_topic(topic_key)
                if priority_topic is None:
                    continue
                aliases = (priority_topic.topic_key, priority_topic.label, *priority_topic.aliases)
                if not any(alias and alias.lower() in evidence_lower for alias in aliases):
                    continue
                candidates.append(
                    _TopicCandidate(
                        topic=priority_topic,
                        question_type="PROJECT",
                        evidence=evidence,
                        source_type="resume",
                        weight=0.96,
                    )
                )

            metric_topic = topic_registry_service.get_topic("project_metric_validation")
            if metric_topic:
                candidates.append(
                    _TopicCandidate(
                        topic=metric_topic,
                        question_type="PROJECT",
                        evidence=evidence,
                        source_type="resume",
                        weight=structured_jd.topic_weights.get(metric_topic.topic_key, 0.5),
                    )
                )

        if not candidates:
            fallback_topic = topic_registry_service.get_topic("custom_project_topic")
            if fallback_topic:
                candidates.append(
                    _TopicCandidate(
                        topic=fallback_topic,
                        question_type="PROJECT",
                        evidence="简历中未识别到明确项目证据，请先用一个最能证明岗位匹配度的核心项目作答。",
                        source_type="resume",
                        weight=0.4,
                    )
                )
            ownership_topic = topic_registry_service.get_topic("project_role_ownership")
            if ownership_topic:
                candidates.append(
                    _TopicCandidate(
                        topic=ownership_topic,
                        question_type="PROJECT",
                        evidence="简历项目证据不足，本题用于补齐个人贡献和项目真实性表达。",
                        source_type="resume",
                        weight=0.38,
                    )
                )

        candidates.sort(
            key=lambda item: (item.weight, self._project_topic_priority(item.topic.topic_key)),
            reverse=True,
        )
        return self._dedupe_candidates(candidates, "PROJECT")

    @staticmethod
    def _select_project_candidates(
        candidates: list[_TopicCandidate],
        limit: int,
        variation_seed: str,
    ) -> list[_TopicCandidate]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.weight + InterviewPlanService._stable_jitter(variation_seed, item.topic.topic_key) * 0.08,
                InterviewPlanService._project_topic_priority(item.topic.topic_key),
            ),
            reverse=True,
        )
        selected: list[_TopicCandidate] = []
        used_skills: set[str] = set()
        for candidate in ranked:
            if len(selected) >= limit:
                break
            if candidate.topic.skill_key in used_skills:
                continue
            selected.append(candidate)
            used_skills.add(candidate.topic.skill_key)
        for candidate in ranked:
            if len(selected) >= limit:
                break
            if candidate.topic.topic_key in {item.topic.topic_key for item in selected}:
                continue
            selected.append(candidate)
        return selected[:limit]

    @staticmethod
    def _project_topic_priority(topic_key: str) -> int:
        priority = {
            "rag_multi_channel_retrieval": 100,
            "mcp_tool_integration": 98,
            "redis_cache_penetration_hotkey": 96,
            "mysql_index_optimization": 94,
            "react_state_management": 92,
            "frontend_performance_optimization": 90,
            "async_task_pipeline": 88,
            "idempotency_design": 86,
            "lora_qlora_finetuning": 84,
            "dpo_preference_optimization": 82,
            "redis_cache_consistency": 60,
            "multi_agent_collaboration": 20,
        }
        return priority.get(topic_key, 50)

    @staticmethod
    def _stable_index(seed: str, modulo: int) -> int:
        if modulo <= 0:
            return 0
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % modulo

    @staticmethod
    def _stable_jitter(seed: str, topic_key: str) -> float:
        digest = hashlib.sha256(f"{seed}:{topic_key}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    @staticmethod
    def _has_multi_agent_evidence(evidence: str) -> bool:
        lowered = evidence.lower()
        return "多 agent" in lowered or "multi-agent" in lowered or "agent 协作" in lowered

    def _knowledge_candidate(
        self,
        structured_jd,
        target_role: str,
        skill_id: str | None,
        existing: list[_TopicCandidate],
    ) -> _TopicCandidate:
        used = {candidate.topic.topic_key for candidate in existing}
        weighted_topics = sorted(structured_jd.topic_weights.items(), key=lambda item: item[1], reverse=True)
        for topic_key, weight in weighted_topics:
            topic = topic_registry_service.get_topic(topic_key)
            if topic and topic_key not in used and "KNOWLEDGE" in topic.supported_question_types:
                return _TopicCandidate(
                    topic=topic,
                    question_type="KNOWLEDGE",
                    evidence=self._jd_evidence(structured_jd),
                    source_type="jd",
                    weight=weight,
                )

        normalized = topic_registry_service.normalize(
            raw_topic=" ".join(structured_jd.required_skills or structured_jd.domain_keywords or [target_role]),
            evidence_snippet=self._jd_evidence(structured_jd),
            question_type="KNOWLEDGE",
            target_role=target_role,
            skill_id=skill_id,
            role_domain=structured_jd.role_domain,
        )
        topic = topic_registry_service.get_topic(normalized.topic_key) or topic_registry_service.get_topic(
            "other_knowledge"
        )
        return _TopicCandidate(
            topic=topic,
            question_type="KNOWLEDGE",
            evidence=self._jd_evidence(structured_jd),
            source_type="jd",
            weight=0.45,
        )

    @staticmethod
    def _system_design_candidate(role_domain: str, target_role: str) -> _TopicCandidate:
        topic_key_by_domain = {
            "ai_agent": "workflow_orchestration_design",
            "llm_application": "cost_latency_tradeoff",
            "llm_finetuning_rl": "system_capacity_estimation",
            "java_backend": "high_concurrency_design",
            "python_backend": "availability_fault_tolerance",
            "frontend": "scalability_design",
            "backend_common": "data_consistency_design",
        }
        topic = topic_registry_service.get_topic(topic_key_by_domain.get(role_domain, "scalability_design"))
        if topic is None:
            topic = topic_registry_service.get_topic("other_system_design")
        return _TopicCandidate(
            topic=topic,
            question_type="SYSTEM_DESIGN",
            evidence=f"目标岗位：{target_role}",
            source_type="jd",
            weight=0.5,
        )

    def _ensure_four_topics(self, candidates: list[_TopicCandidate], target_role: str) -> list[_TopicCandidate]:
        selected = list(candidates)
        fallbacks = [
            ("technical_tradeoff_analysis", "PROJECT", "围绕核心项目补充技术取舍证据。"),
            ("other_knowledge", "KNOWLEDGE", f"围绕{target_role}补充基础知识。"),
            ("other_system_design", "SYSTEM_DESIGN", f"围绕{target_role}补充系统设计表达。"),
        ]
        while len(selected) < 4:
            topic_key, q_type, evidence = fallbacks[(len(selected) - len(candidates)) % len(fallbacks)]
            topic = topic_registry_service.get_topic(topic_key)
            if topic:
                selected.append(_TopicCandidate(topic, q_type, evidence, "fallback", 0.2))
        return selected[:4]

    @staticmethod
    def _apply_dedup(
        candidates: list[_TopicCandidate],
        recent_keys: set[str],
        low_score_keys: set[str],
    ) -> None:
        """Adjust candidate weights: penalize recent repeats, boost low-score retry topics."""
        for i, candidate in enumerate(candidates):
            if candidate.topic.topic_key in recent_keys:
                candidates[i] = _TopicCandidate(
                    topic=candidate.topic,
                    question_type=candidate.question_type,
                    evidence=candidate.evidence,
                    source_type=candidate.source_type,
                    weight=candidate.weight * 0.4,
                )
            elif candidate.topic.topic_key in low_score_keys:
                candidates[i] = _TopicCandidate(
                    topic=candidate.topic,
                    question_type=candidate.question_type,
                    evidence=candidate.evidence,
                    source_type="retry",
                    weight=min(candidate.weight + 0.2, 1.0),
                )

    @staticmethod
    def _dedupe_candidates(candidates: list[_TopicCandidate], question_type: str) -> list[_TopicCandidate]:
        result: list[_TopicCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.topic.topic_key
            if key in seen:
                continue
            if question_type not in candidate.topic.supported_question_types:
                continue
            seen.add(key)
            result.append(candidate)
        return result

    def _candidate_to_topic(
        self,
        candidate: _TopicCandidate,
        order: int,
        target_role: str,
        active: bool,
        variation_seed: str,
    ) -> DynamicTopicDTO:
        return DynamicTopicDTO(
            topic_key=candidate.topic.topic_key,
            topic_title=candidate.topic.label,
            skill_key=candidate.topic.skill_key,
            question_type=candidate.question_type,
            source_type=candidate.source_type,
            evidence_snippet=candidate.evidence,
            main_question=self._main_question(candidate, target_role, variation_seed),
            topic_order=order,
            status=TopicStatus.ACTIVE.value if active else TopicStatus.PENDING.value,
            max_turns=3,
            followup_goals=self._followup_goals(candidate),
            exit_criteria=self._exit_criteria(candidate),
            rubric=self._rubric(candidate.question_type),
        )

    @staticmethod
    def _project_evidence(project: ProjectInfo) -> str:
        parts = [
            project.name,
            project.role,
            project.description,
            "、".join(project.tech_stack),
            "、".join(project.highlights),
        ]
        text = "；".join(part for part in parts if part)
        return text[:500] if text else "简历项目证据不足。"

    @staticmethod
    def _jd_evidence(structured_jd) -> str:
        parts = structured_jd.responsibilities[:2] + structured_jd.required_skills[:5]
        return "；".join(parts)[:500] if parts else "JD 未提供足够结构化证据。"

    @staticmethod
    def _main_question(candidate: _TopicCandidate, target_role: str, variation_seed: str) -> str:
        label = candidate.topic.label
        variant = InterviewPlanService._stable_index(
            f"{variation_seed}:{candidate.topic.topic_key}:{candidate.question_type}",
            3,
        )
        if candidate.question_type == "PROJECT":
            evidence = candidate.evidence or "你的核心项目"
            variants = [
                (
                    f"我看到你简历里写到：{evidence}。我们先聊「{label}」这块。"
                    "你可以从当时要解决的问题讲起，然后说说你具体做了什么、为什么这么设计，以及最后怎么验证效果。"
                ),
                (
                    f"这次我换个角度追一下「{label}」。结合你简历中的经历：{evidence}，"
                    "请重点说明你的个人职责边界、关键技术动作，以及当时有没有做过替代方案比较。"
                ),
                (
                    f"假设面试官只围绕「{label}」深挖你的项目真实性。基于这段经历：{evidence}，"
                    "你会怎么证明这是你亲自做过的？请带上实现细节、异常情况和结果验证。"
                ),
            ]
            return variants[variant]
        if candidate.question_type == "SYSTEM_DESIGN":
            variants = [
                (
                    f"如果在「{target_role}」这个岗位上，需要你设计或优化一个和「{label}」相关的方案，"
                    "你会怎么拆？可以重点讲架构、数据流、可靠性，以及成本和延迟之间的取舍。"
                ),
                (
                    f"围绕「{label}」做一个系统设计题：先说明业务目标和约束，再拆核心模块、数据流和失败兜底。"
                    "如果容量或延迟压力变大，你会优先改哪里？"
                ),
                (
                    f"假设你要把「{label}」方案落到「{target_role}」场景里，请从 baseline、瓶颈、监控和扩展策略讲一版设计。"
                ),
            ]
            return variants[variant]
        variants = [
            f"这个岗位会经常问到「{label}」。你先按自己的理解讲讲它的原理、常见用法，以及实际落地时容易出问题的地方。",
            f"我们聊一下「{label}」：请用一个工程场景解释它解决什么问题、关键机制是什么、边界在哪里。",
            f"如果面试官追问「{label}」，你会如何从定义、核心流程、典型风险和排查方式四步回答？",
        ]
        return variants[variant]

    @staticmethod
    def _followup_goals(candidate: _TopicCandidate) -> list[str]:
        if candidate.question_type == "PROJECT":
            return ["验证个人职责是否清晰", "验证指标或结果是否可证明", "验证技术取舍和异常边界"]
        if candidate.question_type == "SYSTEM_DESIGN":
            return ["验证架构拆分", "验证容量、延迟或成本权衡", "验证失败恢复和可观测性"]
        return ["验证概念准确性", "验证关键步骤完整性", "验证工程适用边界"]

    @staticmethod
    def _exit_criteria(candidate: _TopicCandidate) -> list[str]:
        if candidate.question_type == "PROJECT":
            return ["能说清项目目标", "能说明个人贡献", "能给出结果或验证方式", "能补充一个取舍或异常处理"]
        if candidate.question_type == "SYSTEM_DESIGN":
            return ["能拆分核心模块", "能说明数据流", "能覆盖可靠性", "能说明至少一个取舍"]
        return ["能给出准确定义", "能说明机制", "能给出场景", "能指出边界或风险"]

    @staticmethod
    def _rubric(question_type: str) -> dict[str, str]:
        if question_type == "PROJECT":
            return {
                "authenticity": "个人职责、证据和结果是否可信",
                "technical_depth": "实现细节、异常边界和技术取舍是否扎实",
                "communication_structure": "是否结论先行、层次清楚",
            }
        if question_type == "SYSTEM_DESIGN":
            return {
                "system_thinking": "模块、数据流、可靠性和扩展性是否完整",
                "technical_depth": "关键取舍和瓶颈识别是否具体",
                "communication_structure": "是否按场景、约束、方案、权衡组织",
            }
        return {
            "knowledge_accuracy": "概念和机制是否准确",
            "technical_depth": "是否能讲到工程边界",
            "communication_structure": "是否结构清晰",
        }


class DynamicAnswerEvaluationService:
    STRUCTURE_MARKERS = (
        "首先",
        "然后",
        "最后",
        "第一",
        "第二",
        "1)",
        "2)",
        "3)",
        "：",
        "；",
        "背景",
        "方案",
        "流程",
        "结果",
        "复盘",
        "总结",
        "分三层",
        "四层",
    )
    METRIC_MARKERS = ("指标", "提升", "降低", "baseline", "准确率", "召回率", "qps", "延迟", "耗时", "%")
    OWNERSHIP_MARKERS = ("我负责", "我主导", "我实现", "我的职责", "我设计", "独立", "我推进")
    TRADEOFF_MARKERS = ("取舍", "权衡", "替代方案", "成本", "复杂度", "边界", "风险")
    RELIABILITY_MARKERS = ("异常", "重试", "降级", "监控", "告警", "兜底", "恢复")
    CONCRETE_MARKERS = (
        "先查",
        "再查",
        "回写",
        "互斥锁",
        "过期时间",
        "布隆过滤器",
        "二级缓存",
        "本地缓存",
        "caffeine",
        "explain",
        "联合索引",
        "覆盖索引",
        "慢 SQL",
        "慢查询",
        "执行计划",
        "索引失效",
        "OR 条件",
        "UNION ALL",
        "分库分表",
        "哈希",
        "user_id",
        "回表",
        "BM25",
        "向量检索",
        "Cross-Encoder",
        "重排序",
        "Query Rewrite",
        "intent classifier",
        "Top-20",
        "Top-5",
        "pgvector",
        "useState",
        "useContext",
        "useReducer",
        "useMemo",
        "Redux",
        "Zustand",
        "React Query",
        "服务端状态",
        "全局状态",
        "状态归一化",
        "虚拟滚动",
        "代码分割",
        "懒加载",
        "Redis Streams",
        "stream",
        "任务重试",
        "超时处理",
        "并行消费",
        "XADD",
        "XREADGROUP",
        "Consumer Group",
        "Idempotency-Key",
        "唯一 key",
        "处理过",
        "直接返回",
        "之前的结果",
        "去重",
        "message_id",
        "Stdio",
        "SSE",
        "工具注册",
        "工具描述",
        "外部工具",
        "用户意图",
        "schema",
        "input_schema",
        "endpoint",
        "token 预算",
        "工具返回",
        "声明式配置",
        "adapter",
        "少量参数",
        "全量微调",
        "指令微调",
        "A100",
        "rank=",
        "alpha=",
        "target_modules",
        "偏好数据",
        "对比数据",
        "reward model",
        "beta=",
        "reference model",
    )
    GENERIC_WEAK_MARKERS = (
        "效果还不错",
        "很好用",
        "很多地方",
        "大幅提升性能",
        "很多方案",
        "都可以",
        "就行",
        "写好代码",
        "现在很流行",
        "很多公司",
        "一般用",
        "主要是把",
        "团队熟悉",
    )
    OFF_TOPIC_MARKERS = (
        "不需要引入 Redis",
        "ThreadPoolExecutor",
        "应该用多线程",
        "不如直接写 Prompt",
        "zero-shot",
        "应该靠规则引擎",
        "写一些正则表达式",
        "前端只是展示层",
        "应该全部放到后端",
        "应该用 CDN",
        "前端渲染",
        "虚拟 DOM",
        "服务端渲染",
        "首屏速度",
        "应该用 MongoDB",
        "微服务架构",
        "Docker Compose",
        "Kubernetes",
        "服务发现",
        "负载均衡",
    )

    def evaluate(
        self,
        topic: DynamicTopicDTO,
        turn: DynamicTurnDTO,
        answer: str,
        previous_turns: list[DynamicTurnDTO],
    ) -> DynamicTurnEvaluationDTO:
        text = answer.strip()
        if not text:
            return DynamicTurnEvaluationDTO(
                ability_score=0,
                feedback="当前回答为空，无法判断能力。",
                signals={"strengths": [], "gaps": ["未作答"], "risks": ["面试中会被直接判定为无法评估"]},
                dimension_scores=self._dimension_scores(topic.question_type, 0, []),
            )

        score = 22
        signals = {"strengths": [], "gaps": [], "risks": []}
        score += min(len(text) // 18, 24)

        if self._contains_any(text, self.STRUCTURE_MARKERS):
            score += 12
            signals["strengths"].append("回答有基本结构")
        else:
            signals["gaps"].append("缺少清晰表达结构")

        topic_terms = self._topic_terms(topic)
        topic_hits = [term for term in topic_terms if term.lower() in text.lower()]
        if topic_hits:
            score += min(len(set(topic_hits)) * 5, 15)
            signals["strengths"].append("能贴合当前 topic 作答")
        else:
            signals["gaps"].append("没有明显扣住当前主题关键词")

        markers = self._question_type_markers(topic.question_type)
        marker_hits = [label for label, values in markers.items() if self._contains_any(text, values)]
        score += min(len(marker_hits) * 9, 27)
        signals["strengths"].extend([f"覆盖了{label}" for label in marker_hits[:3]])
        missing_labels = [label for label in markers if label not in marker_hits]
        signals["gaps"].extend([f"缺少{label}" for label in missing_labels[:3]])

        concrete_hits = [term for term in self.CONCRETE_MARKERS if term.lower() in text.lower()]
        if len(concrete_hits) >= 4:
            score += 20
            signals["strengths"].append("包含可追问的实现细节")
        elif len(concrete_hits) >= 2:
            score += 12
            signals["strengths"].append("包含部分实现细节")

        generic_hits = [term for term in self.GENERIC_WEAK_MARKERS if term.lower() in text.lower()]
        generic_cap = False
        if len(generic_hits) >= 2 and len(concrete_hits) < 3:
            score -= 8
            generic_cap = True
            signals["risks"].append("回答偏泛，缺少可验证实现细节")
        elif generic_hits and not marker_hits and len(concrete_hits) < 2:
            score -= 4
            generic_cap = True
            signals["risks"].append("表达偏泛，面试官难以判断真实掌握程度")

        off_topic_hits = [term for term in self.OFF_TOPIC_MARKERS if term.lower() in text.lower()]
        if off_topic_hits and len(concrete_hits) < 3:
            score -= 14
            signals["risks"].append("回答倾向替换或否定题目方案，存在跑题风险")

        if topic.question_type == "PROJECT" and topic.evidence_snippet:
            evidence_terms = self._evidence_terms(topic.evidence_snippet)
            evidence_hits = [term for term in evidence_terms if term.lower() in text.lower()]
            if len(evidence_hits) >= 2:
                score += 8
                signals["strengths"].append("能引用简历证据")
            else:
                signals["risks"].append("回答和简历证据连接不够，真实性容易被追问")

        if generic_cap:
            score = min(score, 60)

        if topic_hits and not off_topic_hits and score < 30:
            score = 30

        if len(text) < 60:
            score = min(score, 55)
            signals["risks"].append("回答过短，难以证明掌握程度")

        if previous_turns:
            previous_scores = [turn.ability_score or 0 for turn in previous_turns if turn.ability_score is not None]
            if previous_scores and score >= max(previous_scores) + 8:
                signals["strengths"].append("重答后有明显补充")
            elif previous_scores and score <= max(previous_scores) + 2:
                signals["risks"].append("提示后提升不明显")

        score = max(0, min(score, 95))
        feedback = self._feedback(score, signals)
        return DynamicTurnEvaluationDTO(
            ability_score=score,
            feedback=feedback,
            signals={key: self._dedupe(values)[:5] for key, values in signals.items()},
            dimension_scores=self._dimension_scores(topic.question_type, score, marker_hits),
        )

    def coach_hint(self, topic: DynamicTopicDTO, evaluation: DynamicTurnEvaluationDTO) -> dict:
        return self.fallback_coach_hint(topic, evaluation)

    def fallback_evaluation(self, topic: DynamicTopicDTO) -> DynamicTurnEvaluationDTO:
        return DynamicTurnEvaluationDTO(
            ability_score=50,
            feedback="评分暂时失败，已保存你的回答。可以先按结构补充一版，稍后继续查看复盘。",
            signals={
                "strengths": [],
                "gaps": ["评分服务暂时不可用"],
                "risks": ["本轮回答尚未得到稳定评分"],
            },
            dimension_scores=self._dimension_scores(topic.question_type, 50, []),
        )

    def fallback_coach_hint(self, topic: DynamicTopicDTO, evaluation: DynamicTurnEvaluationDTO) -> dict:
        gaps = evaluation.signals.get("gaps") or ["补充关键证据和表达结构"]
        if topic.question_type == "PROJECT":
            structure = ["背景目标", "个人职责", "关键方案", "结果指标", "取舍复盘"]
        elif topic.question_type == "SYSTEM_DESIGN":
            structure = ["场景约束", "模块拆分", "数据流", "可靠性", "成本/延迟权衡"]
        else:
            structure = ["结论定义", "核心原理", "关键步骤", "使用场景", "边界风险"]
        return {
            "type": "STRUCTURE_HINT",
            "message": (
                f"这一版可以再补一点：{'、'.join(gaps[:3])}。"
                f"你重答时不用背答案，按 {' -> '.join(structure)} 这个顺序把经历讲清楚就行。"
            ),
            "structure": structure,
            "focus_gaps": gaps[:3],
            "guardrail": "只给结构、方向和缺口，不提供完整可照抄答案。",
        }

    @classmethod
    def _question_type_markers(cls, question_type: str) -> dict[str, tuple[str, ...]]:
        if question_type == "PROJECT":
            return {
                "个人职责": cls.OWNERSHIP_MARKERS,
                "结果指标": cls.METRIC_MARKERS,
                "技术取舍": cls.TRADEOFF_MARKERS,
                "异常边界": cls.RELIABILITY_MARKERS,
            }
        if question_type == "SYSTEM_DESIGN":
            return {
                "架构模块": ("模块", "架构", "服务", "组件", "链路"),
                "数据流": ("数据流", "写入", "读取", "同步", "异步"),
                "可靠性": cls.RELIABILITY_MARKERS,
                "成本延迟权衡": cls.TRADEOFF_MARKERS + cls.METRIC_MARKERS,
            }
        return {
            "概念定义": ("定义", "本质", "核心", "概念", "原理", "管理", "协议", "训练目标"),
            "关键步骤": ("步骤", "流程", "链路", "过程", "机制", "策略", "实现", "schema", "数据集", "参数"),
            "适用场景": ("场景", "适合", "用于", "业务", "项目", "缓存", "工具", "模型", "服务端状态"),
            "边界风险": ("边界", "风险", "问题", "缺点", "坑", "一致性", "超时", "预算", "调参", "不可控"),
        }

    @staticmethod
    def _contains_any(text: str, markers: tuple[str, ...] | list[str]) -> bool:
        lowered = text.lower()
        return any(marker.lower() in lowered for marker in markers if marker)

    @staticmethod
    def _evidence_terms(evidence: str) -> list[str]:
        chunks = [chunk.strip(" ，。；;:：/-()（）") for chunk in re.split(r"[\s，。；;:：、/()（）]+", evidence)]
        known_terms = (
            "Redis",
            "MySQL",
            "慢 SQL",
            "慢查询",
            "执行计划",
            "联合索引",
            "分库分表",
            "React",
            "TypeScript",
            "FastAPI",
            "Cache-Aside",
            "互斥锁",
            "过期时间",
            "布隆过滤器",
            "热点",
            "缓存",
            "useState",
            "useContext",
            "Redux",
            "Zustand",
            "虚拟滚动",
            "代码分割",
            "Redis Streams",
            "Consumer Group",
            "幂等",
            "LoRA",
            "DPO",
        )
        broad_terms = {
            "python",
            "java",
            "prompt",
            "llm",
            "后端",
            "前端",
            "工程师",
            "项目",
            "参与",
            "开发",
            "使用",
            "实现",
            "负责",
        }
        terms = [term for term in known_terms if term.lower() in evidence.lower()]
        terms.extend(
            chunk
            for chunk in chunks
            if len(chunk) >= 2
            and chunk.lower() not in broad_terms
            and not any(broad in chunk.lower() for broad in ("工程师", "开发工程", "参与"))
        )
        return list(dict.fromkeys(terms))[:20]

    @staticmethod
    def _topic_terms(topic: DynamicTopicDTO) -> list[str]:
        terms: list[str] = []
        for raw in (topic.topic_title, topic.skill_key, topic.topic_key):
            if not raw:
                continue
            terms.append(raw)
            terms.extend(part for part in re.split(r"[_\s/]+", raw) if len(part) >= 2)
        topic_def = topic_registry_service.get_topic(topic.topic_key)
        if topic_def:
            terms.extend(topic_def.aliases)
        return list(dict.fromkeys(terms))

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in values if item))

    @staticmethod
    def _feedback(score: int, signals: dict[str, list[str]]) -> str:
        def naturalize(item: str) -> str:
            if item.startswith("缺少"):
                return f"再补一下{item[2:]}"
            if item == "没有明显扣住当前主题关键词":
                return "再更明确地扣住当前主题"
            if item == "回答和简历证据连接不够，真实性容易被追问":
                return "把回答和简历里的具体经历连得更紧"
            if item == "回答偏泛，缺少可验证实现细节":
                return "少一点泛讲，多给可验证的实现细节"
            if item == "表达偏泛，面试官难以判断真实掌握程度":
                return "用更具体的例子证明你真的做过"
            if item == "回答过短，难以证明掌握程度":
                return "展开到足够让面试官判断深度"
            return item

        if score >= 85:
            prefix = "回答已经比较扎实"
        elif score >= 70:
            prefix = "回答有基础，但还需要补证据和边界"
        elif score >= 55:
            prefix = "回答覆盖了一部分内容，但面试中容易被继续追问"
        else:
            prefix = "当前回答偏空，需要先按结构补齐核心信息"
        gap_text = "；".join(
            naturalize(item) for item in (signals.get("gaps") or signals.get("risks") or ["继续补充关键点"])
        )
        return f"{prefix}。下一步重点：{gap_text}。"

    @staticmethod
    def _dimension_scores(question_type: str, score: int, marker_hits: list[str]) -> dict[str, int]:
        dimensions = {
            "authenticity": score if question_type == "PROJECT" else max(45, score - 8),
            "technical_depth": max(0, score - (4 if "技术取舍" in marker_hits or "边界风险" in marker_hits else 12)),
            "knowledge_accuracy": score if question_type == "KNOWLEDGE" else max(45, score - 10),
            "system_thinking": score if question_type == "SYSTEM_DESIGN" else max(40, score - 14),
            "communication_structure": min(95, score + (4 if marker_hits else -8)),
        }
        return {key: max(0, min(value, 100)) for key, value in dimensions.items()}


class CoachInterviewPolicy:
    max_retries_per_topic = 2

    def decide(
        self,
        *,
        topic: DynamicTopicDTO,
        turn: DynamicTurnDTO,
        evaluation: DynamicTurnEvaluationDTO,
        answered_turns_after_current: list[DynamicTurnDTO],
        has_next_topic: bool,
        coach_hint: dict | None,
    ) -> DynamicDecisionDTO:
        retry_count = sum(1 for item in answered_turns_after_current if item.turn_type == TurnType.COACH_RETRY.value)
        initial_score = next(
            (item.ability_score for item in answered_turns_after_current if item.turn_type == TurnType.MAIN.value),
            evaluation.ability_score,
        )

        should_retry = False
        if turn.turn_type == TurnType.MAIN.value:
            should_retry = evaluation.ability_score < 85
        elif turn.turn_type == TurnType.COACH_RETRY.value:
            improvement = evaluation.ability_score - (initial_score or 0)
            should_retry = evaluation.ability_score < 75 and improvement < 10

        if should_retry and retry_count < self.max_retries_per_topic:
            return DynamicDecisionDTO(
                action=DecisionAction.COACH_RETRY.value,
                reason="教练模式下当前回答仍有可训练缺口，进入同题重答。",
                hint=coach_hint,
                next_question=topic.main_question,
            )

        if has_next_topic:
            return DynamicDecisionDTO(
                action=DecisionAction.NEXT_TOPIC.value,
                reason="当前 topic 已完成本轮训练，进入下一个 topic。",
            )
        return DynamicDecisionDTO(action=DecisionAction.END.value, reason="所有计划 topic 已完成，生成 topic 级报告。")


class StrictInterviewPolicy:
    max_followups_per_topic = 2

    def decide(
        self,
        *,
        topic: DynamicTopicDTO,
        turn: DynamicTurnDTO,
        evaluation: DynamicTurnEvaluationDTO,
        answered_turns_after_current: list[DynamicTurnDTO],
        has_next_topic: bool,
        coach_hint: dict | None = None,
    ) -> DynamicDecisionDTO:
        del coach_hint
        followup_count = sum(1 for item in answered_turns_after_current if item.turn_type == TurnType.FOLLOW_UP.value)
        if (
            turn.turn_type in {TurnType.MAIN.value, TurnType.FOLLOW_UP.value}
            and followup_count < self.max_followups_per_topic
        ):
            return DynamicDecisionDTO(
                action=DecisionAction.FOLLOW_UP.value,
                reason="严厉模式下继续验证回答真实性、细节和抗压稳定性。",
                hint=None,
                next_question=self._followup_question(topic, evaluation, followup_count + 1),
            )

        if has_next_topic:
            return DynamicDecisionDTO(
                action=DecisionAction.NEXT_TOPIC.value,
                reason="严厉模式当前 topic 已完成两轮追问，进入下一个 topic。",
                hint=None,
            )
        return DynamicDecisionDTO(action=DecisionAction.END.value, reason="所有计划 topic 已完成，生成严厉模式报告。")

    @staticmethod
    def _followup_question(
        topic: DynamicTopicDTO,
        evaluation: DynamicTurnEvaluationDTO,
        followup_number: int,
    ) -> str:
        gaps = evaluation.signals.get("gaps") or evaluation.signals.get("risks") or []
        gap = gaps[0] if gaps else ""
        if topic.question_type == "PROJECT":
            return StrictInterviewPolicy._project_followup_question(topic, gap, followup_number)
        if topic.question_type == "SYSTEM_DESIGN":
            if followup_number == 1:
                return (
                    "先不谈容量。你先口述最小链路：用户请求进来后，依次经过哪 3 到 5 个模块？每个模块一句话负责什么。"
                )
            return "现在只追一个瓶颈：这条链路里最慢或最容易失败的一步是哪一步？你会怎么限时、重试或降级？"
        if followup_number == 1:
            return f"我想确认你不是只记了概念。请用 3 步讲清楚「{topic.topic_title}」的核心机制，再补一个最容易踩错的边界。"
        return "最后只举一个工程场景：它什么时候适用，什么时候不适用？"

    @staticmethod
    def _project_followup_question(topic: DynamicTopicDTO, gap: str, followup_number: int) -> str:
        if followup_number == 1:
            lead = "先不讲整个项目。"
            if "结构" in gap:
                lead = "你刚才讲到了一些点，但我还没听清楚最小链路。"
            elif "技术取舍" in gap:
                lead = "你提到了方案，我先不追大而全的取舍。"
            elif "异常" in gap or "边界" in gap:
                lead = "我先不展开所有异常。"
            return f"{lead}{StrictInterviewPolicy._project_minimal_chain_prompt(topic.topic_title)}"

        if "指标" in gap or "效果" in gap:
            return "你刚才提到效果，先只讲一个指标：你们看的是延迟、成功率、召回率还是转化？上线前后怎么对比？"
        if "异常" in gap or "边界" in gap:
            return "只挑一个失败场景：超时、参数错误、依赖不可用或结果为空。它发生时系统怎么处理？"
        if "技术取舍" in gap or "取舍" in gap:
            return "只讲一个取舍：当时有哪两个方案？你们为什么选现在这个？"
        return "先补一个验证方式：你怎么判断这段功能真的有效？"

    @staticmethod
    def _project_minimal_chain_prompt(topic_title: str) -> str:
        title = topic_title.lower()
        if "mcp" in title or "工具" in topic_title:
            return "就选你实际接过的一个工具，从一次调用开始讲：请求进来后怎么识别工具、怎么组参数、怎么拿结果？"
        if any(keyword in topic_title for keyword in ("缓存", "热点", "穿透", "击穿")):
            return "就选一条商品查询或秒杀请求，讲它怎么查缓存、什么时候查 DB、怎么防穿透或热点击穿。"
        if "rag" in title or "检索" in topic_title:
            return "就选一次检索请求，讲 query 怎么处理、怎么召回、怎么排序、怎么把结果交给模型。"
        return "就选一个最小闭环，从一次请求或任务进来讲到结果返回。你具体负责哪一步？"


class DynamicInterviewReportService:
    def build_report(
        self,
        session: InterviewSessionEntity,
        topics: list[InterviewTopicEntity],
        turns: list[InterviewTurnEntity],
    ) -> DynamicReportDTO:
        turns_by_topic: dict[int, list[InterviewTurnEntity]] = {}
        for turn in turns:
            turns_by_topic.setdefault(turn.topic_id, []).append(turn)

        topic_summaries = [
            self._topic_summary(topic, sorted(turns_by_topic.get(topic.id, []), key=lambda item: item.turn_order))
            for topic in topics
        ]
        type_scores = self._type_scores(topic_summaries)
        ability_scores = self._ability_scores(turns)
        readiness_score = self._readiness_score(type_scores)
        top_risks = self._top_risks(topic_summaries)
        tomorrow_tasks = self._tomorrow_tasks(topic_summaries, session)
        retry_deltas = [
            {
                "topic_key": summary.topic_key,
                "initial_score": summary.initial_score,
                "final_score": summary.final_score,
                "score_delta": summary.score_delta,
            }
            for summary in topic_summaries
            if summary.score_delta is not None
        ]

        return DynamicReportDTO(
            session_id=session.session_id,
            readiness_score=readiness_score,
            type_scores=type_scores,
            ability_scores=ability_scores,
            top_risks=top_risks,
            topic_summaries=topic_summaries,
            tomorrow_tasks=tomorrow_tasks,
            retry_deltas=retry_deltas,
            resume_fix_suggestions=self._resume_fix_suggestions(topic_summaries),
        )

    def _topic_summary(self, topic: InterviewTopicEntity, turns: list[InterviewTurnEntity]) -> DynamicTopicSummaryDTO:
        answered = [turn for turn in turns if turn.answer]
        scores = [turn.ability_score or 0 for turn in answered]
        initial_score = next((turn.ability_score for turn in answered if turn.turn_type == TurnType.MAIN.value), None)
        final_score = scores[-1] if scores else None
        best_score = max(scores) if scores else None
        score_delta = final_score - initial_score if final_score is not None and initial_score is not None else None
        strengths, gaps, risks = self._merge_signals(answered)
        next_action = self._next_training_action(topic, gaps, risks, score_delta)
        return DynamicTopicSummaryDTO(
            topic_id=topic.id,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            question_type=topic.question_type,
            evidence_snippet=topic.evidence_snippet,
            main_question=topic.main_question,
            initial_score=initial_score,
            final_score=final_score,
            best_score=best_score,
            score_delta=score_delta,
            strengths=strengths[:4],
            risks=risks[:4],
            gaps=gaps[:4],
            next_training_action=next_action,
        )

    @staticmethod
    def _merge_signals(turns: list[InterviewTurnEntity]) -> tuple[list[str], list[str], list[str]]:
        strengths: list[str] = []
        gaps: list[str] = []
        risks: list[str] = []
        for turn in turns:
            signals = safe_json_loads(turn.signals_json, {})
            if not isinstance(signals, dict):
                continue
            strengths.extend(signals.get("strengths") or [])
            gaps.extend(signals.get("gaps") or [])
            risks.extend(signals.get("risks") or [])
        return (
            list(dict.fromkeys(strengths)),
            list(dict.fromkeys(gaps)),
            list(dict.fromkeys(risks)),
        )

    @staticmethod
    def _type_scores(topic_summaries: list[DynamicTopicSummaryDTO]) -> dict[str, int | None]:
        buckets = {"project": [], "knowledge": [], "system_design": []}
        for summary in topic_summaries:
            key = summary.question_type.lower()
            if key in buckets and summary.final_score is not None:
                buckets[key].append(summary.final_score)
        return {key: int(sum(values) / len(values)) if values else None for key, values in buckets.items()}

    @staticmethod
    def _readiness_score(type_scores: dict[str, int | None]) -> int:
        weights = {"project": 0.5, "knowledge": 0.3, "system_design": 0.2}
        present = {key: value for key, value in type_scores.items() if value is not None}
        if not present:
            return 0
        total_weight = sum(weights[key] for key in present)
        return int(sum((present[key] or 0) * weights[key] / total_weight for key in present))

    @staticmethod
    def _ability_scores(turns: list[InterviewTurnEntity]) -> dict[str, int]:
        buckets: dict[str, list[int]] = {
            "authenticity": [],
            "technical_depth": [],
            "knowledge_accuracy": [],
            "system_thinking": [],
            "communication_structure": [],
        }
        for turn in turns:
            evaluation = safe_json_loads(turn.evaluation_json, {})
            dimension_scores = evaluation.get("dimension_scores") if isinstance(evaluation, dict) else None
            if not isinstance(dimension_scores, dict):
                continue
            for key in buckets:
                value = dimension_scores.get(key)
                if isinstance(value, int):
                    buckets[key].append(value)
        return {key: int(sum(values) / len(values)) if values else 0 for key, values in buckets.items()}

    @staticmethod
    def _top_risks(topic_summaries: list[DynamicTopicSummaryDTO]) -> list[str]:
        risks = []
        ordered = sorted(topic_summaries, key=lambda item: item.final_score if item.final_score is not None else 0)
        for summary in ordered:
            reason = (summary.risks or summary.gaps or ["当前 topic 表达仍不稳定"])[0]
            risks.append(f"{summary.topic_title}：{reason}")
        return risks[:3]

    def _tomorrow_tasks(
        self,
        topic_summaries: list[DynamicTopicSummaryDTO],
        session: InterviewSessionEntity,
    ) -> list[TomorrowTaskDTO]:
        candidates = sorted(topic_summaries, key=lambda item: item.final_score if item.final_score is not None else 0)
        tasks: list[TomorrowTaskDTO] = []
        project = next((item for item in candidates if item.question_type == "PROJECT"), None)
        knowledge_or_system = next(
            (item for item in candidates if item.question_type in {"KNOWLEDGE", "SYSTEM_DESIGN"}), None
        )
        expression = (
            next((item for item in candidates if "表达" in " ".join(item.gaps + item.risks)), None) or candidates[0]
            if candidates
            else None
        )

        for summary in [project, knowledge_or_system, expression]:
            if summary and len(tasks) < 3:
                task = self._task_from_summary(summary, session)
                if not any(existing.title == task.title for existing in tasks):
                    tasks.append(task)

        while len(tasks) < 3 and candidates:
            task = self._task_from_summary(candidates[len(tasks) % len(candidates)], session)
            if any(existing.title == task.title for existing in tasks):
                task.title = f"{task.title}（第 {len(tasks) + 1} 轮）"
            tasks.append(task)
        return tasks[:3]

    @staticmethod
    def _task_from_summary(summary: DynamicTopicSummaryDTO, session: InterviewSessionEntity) -> TomorrowTaskDTO:
        gaps = summary.gaps or summary.risks or ["补齐表达结构"]
        score = summary.final_score if summary.final_score is not None else 0
        weakness_severity = max(0.0, (85 - score) / 85)
        low_improvement = 1.0 if summary.score_delta is not None and summary.score_delta < 8 else 0.2
        priority = round(weakness_severity * 0.55 + low_improvement * 0.2 + 0.25, 2)
        if summary.question_type == "PROJECT":
            task_type = "PROJECT_PROOF" if any("指标" in gap or "证据" in gap for gap in gaps) else "RETRY_TOPIC"
            action = "写清项目背景、个人职责、关键动作、指标口径和复盘取舍，控制在 2 分钟内。"
        elif summary.question_type == "SYSTEM_DESIGN":
            task_type = "SYSTEM_DESIGN_DRILL"
            action = "按场景约束、模块拆分、数据流、可靠性、成本/延迟权衡五段重答一次。"
        else:
            task_type = "KNOWLEDGE_DRILL"
            action = "用定义、原理、关键步骤、使用场景、边界风险五段补齐 80 分回答。"
        if any("表达" in gap or "结构" in gap for gap in gaps):
            task_type = "EXPRESSION_REWRITE"
        return TomorrowTaskDTO(
            task_type=task_type,
            topic_key=summary.topic_key,
            weakness_type=gaps[0],
            priority_score=priority,
            title=f"补齐{summary.topic_title}的{gaps[0]}",
            reason=f"{summary.topic_title}当前最终分 {score}，主要缺口是：{gaps[0]}。",
            action=action,
        )

    @staticmethod
    def _next_training_action(
        topic: InterviewTopicEntity, gaps: list[str], risks: list[str], score_delta: int | None
    ) -> str:
        focus = (gaps or risks or ["补齐结构化表达"])[0]
        if score_delta is not None and score_delta >= 10:
            return f"把本轮有效重答沉淀成模板，同时继续强化：{focus}"
        return f"下一步优先训练：{focus}"

    @staticmethod
    def _resume_fix_suggestions(topic_summaries: list[DynamicTopicSummaryDTO]) -> list[str]:
        suggestions = []
        for summary in topic_summaries:
            if summary.question_type == "PROJECT" and any(
                "简历证据" in risk or "证据" in risk for risk in summary.risks
            ):
                suggestions.append(f"在简历中补充「{summary.topic_title}」的指标、职责和结果证据。")
        return suggestions[:3]


class DynamicRagCoachService:
    min_confidence = 0.60

    async def build_topic_insight(
        self,
        db: AsyncSession,
        *,
        topic: InterviewTopicEntity,
        turns: list[InterviewTurnEntity],
        user_id: int,
    ) -> DynamicTopicRagInsightDTO:
        citations = await self._search_personal_knowledge(db, topic, user_id)
        confident_citations = [item for item in citations if item.score >= self.min_confidence][:3]
        confidence = max((item.score for item in confident_citations), default=0.0)
        source_status = "PERSONAL_KB_HIT" if confident_citations else "NO_KB_HIT"
        fallback_reason = (
            None if confident_citations else "个人知识库暂未找到足够相关资料，本次不强行引用知识库，以下为通用题解。"
        )
        answer_issue = self._answer_issue(turns, topic)

        return DynamicTopicRagInsightDTO(
            topic_id=topic.id,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            question_type=topic.question_type,
            source_status=source_status,
            retrieval_confidence=round(confidence, 2),
            fallback_reason=fallback_reason,
            answer_issue=answer_issue,
            explanation=self._explanation(topic, answer_issue, confident_citations),
            citations=confident_citations,
            recommended_materials=self._recommended_materials(topic, confident_citations),
            study_steps=self._study_steps(topic),
            next_practice=self._next_practice(topic),
        )

    async def _search_personal_knowledge(
        self,
        db: AsyncSession,
        topic: InterviewTopicEntity,
        user_id: int,
    ) -> list[DynamicRagCitationDTO]:
        keywords = self._keywords_for_topic(topic)
        completed_kbs = [
            kb
            for kb in await knowledge_base_persistence_service.find_all(db, user_id)
            if kb.index_status == AsyncTaskStatus.COMPLETED
        ]
        if not keywords or not completed_kbs:
            return []

        kb_names = {kb.id: kb.name for kb in completed_kbs}
        stmt = (
            select(KnowledgeChunkEntity, KnowledgeBaseEntity)
            .join(KnowledgeBaseEntity, KnowledgeChunkEntity.knowledge_base_id == KnowledgeBaseEntity.id)
            .where(KnowledgeBaseEntity.user_id == user_id)
            .where(KnowledgeBaseEntity.index_status == AsyncTaskStatus.COMPLETED)
            .limit(500)
        )
        result = await db.execute(stmt)
        citations: list[DynamicRagCitationDTO] = []
        for chunk, kb in result.all():
            score = self._score_text(chunk.content_preview or chunk.content, keywords)
            if score <= 0:
                continue
            preview = (chunk.content_preview or chunk.content or "").strip()
            citations.append(
                DynamicRagCitationDTO(
                    knowledge_base_id=kb.id,
                    chunk_id=chunk.id,
                    source_name=kb_names.get(kb.id) or kb.name,
                    title=chunk.title,
                    content_preview=preview[:260],
                    score=round(score, 2),
                )
            )
        return sorted(citations, key=lambda item: item.score, reverse=True)

    @classmethod
    def _keywords_for_topic(cls, topic: InterviewTopicEntity) -> list[str]:
        raw_parts = [
            topic.topic_key.replace("_", " "),
            topic.topic_title,
            topic.skill_key,
            topic.main_question,
            topic.evidence_snippet or "",
        ]
        text = " ".join(raw_parts).lower()
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]{1,}|[\u4e00-\u9fff]{2,}", text)
        topic_key_parts = [part for part in topic.topic_key.lower().split("_") if len(part) >= 2]
        title_terms = [topic.topic_title[i : i + 2] for i in range(max(0, len(topic.topic_title) - 1))]
        candidates = topic_key_parts + tokens + title_terms + [topic.skill_key.lower()]
        stop_words = {"the", "and", "with", "into", "topic", "project", "system", "design", "please", "question"}
        return list(dict.fromkeys(item for item in candidates if item and item not in stop_words))[:24]

    @staticmethod
    def _score_text(text: str, keywords: list[str]) -> float:
        if not text:
            return 0.0
        lowered = text.lower()
        matched = [keyword for keyword in keywords if keyword and keyword in lowered]
        if not matched:
            return 0.0
        denominator = min(max(len(keywords), 1), 10)
        length_bonus = 0.08 if len(text) >= 120 else 0.0
        return min(0.95, len(set(matched)) / denominator + length_bonus)

    @staticmethod
    def _answer_issue(turns: list[InterviewTurnEntity], topic: InterviewTopicEntity) -> str:
        answered = [turn for turn in turns if turn.answer]
        for turn in reversed(answered):
            signals = safe_json_loads(turn.signals_json, {})
            if isinstance(signals, dict):
                gaps = signals.get("gaps") or []
                risks = signals.get("risks") or []
                if gaps:
                    return str(gaps[0])
                if risks:
                    return str(risks[0])
        if topic.question_type == "PROJECT":
            return "需要把个人职责、技术动作和结果证据讲得更具体。"
        if topic.question_type == "SYSTEM_DESIGN":
            return "需要补齐约束、模块拆分、数据流和关键取舍。"
        return "需要补齐定义、原理、步骤、场景和边界。"

    @staticmethod
    def _explanation(topic: InterviewTopicEntity, answer_issue: str, citations: list[DynamicRagCitationDTO]) -> str:
        source_prefix = "结合你的知识库资料，" if citations else "未引用知识库资料，"
        if topic.question_type == "PROJECT":
            return (
                f"{source_prefix}{topic.topic_title} 的复盘重点不是背概念，而是证明你真实做过："
                f"先给项目目标和你的职责，再讲关键方案、指标口径、异常边界和复盘取舍。当前缺口是：{answer_issue}"
            )
        if topic.question_type == "SYSTEM_DESIGN":
            return (
                f"{source_prefix}{topic.topic_title} 需要先讲场景和约束，再拆模块、数据流、容量/延迟、可靠性，"
                f"最后说明取舍。当前缺口是：{answer_issue}"
            )
        return (
            f"{source_prefix}{topic.topic_title} 要讲清定义、核心机制、关键步骤、适用场景和风险边界。"
            f"当前缺口是：{answer_issue}"
        )

    @staticmethod
    def _recommended_materials(topic: InterviewTopicEntity, citations: list[DynamicRagCitationDTO]) -> list[str]:
        if citations:
            return [f"{item.source_name}：{item.title or item.content_preview[:28]}" for item in citations]
        if topic.question_type == "PROJECT":
            return [f"{topic.topic_title} 项目复盘模板", "指标口径与实验对比记录", "异常处理和技术取舍复盘"]
        if topic.question_type == "SYSTEM_DESIGN":
            return [f"{topic.topic_title} 架构拆解笔记", "容量估算与可靠性设计资料", "成本/延迟权衡案例"]
        return [f"{topic.topic_title} 原理讲解", "核心步骤与边界风险总结", "高频面试问答样例"]

    @staticmethod
    def _study_steps(topic: InterviewTopicEntity) -> list[str]:
        goals = safe_json_loads(topic.followup_goals_json, [])
        if isinstance(goals, list) and goals:
            return [f"补齐：{goal}" for goal in goals[:3]]
        if topic.question_type == "PROJECT":
            return ["写出项目背景和个人职责", "补充关键方案与指标口径", "准备一个异常处理或取舍案例"]
        if topic.question_type == "SYSTEM_DESIGN":
            return ["明确场景约束", "画出模块和数据流", "补充可靠性与成本/延迟取舍"]
        return ["先给准确定义", "补齐核心机制和步骤", "准备场景与边界风险"]

    @staticmethod
    def _next_practice(topic: InterviewTopicEntity) -> str:
        if topic.question_type == "PROJECT":
            return f"用 2 分钟重讲「{topic.topic_title}」，必须包含职责、方案、指标和复盘。"
        if topic.question_type == "SYSTEM_DESIGN":
            return f"用 3 分钟按约束、模块、数据流、可靠性、取舍重讲「{topic.topic_title}」。"
        return f"用 1 分钟解释「{topic.topic_title}」的定义、机制、场景和风险。"


class DynamicInterviewService:
    generation_stages = [
        ("RESUME_PROFILE", "正在分析简历项目"),
        ("JD_PARSE", "正在匹配 JD 重点"),
        ("TOPIC_PLAN", "正在选择面试主题"),
        ("MAIN_QUESTION_GENERATE", "正在准备第一题"),
    ]

    def __init__(self):
        self.plan_service = InterviewPlanService()
        self.evaluator = DynamicAnswerEvaluationService()
        self.report_service = DynamicInterviewReportService()
        self.rag_coach_service = DynamicRagCoachService()

    @staticmethod
    def _policy_for_mode(mode: str | None):
        if mode and mode.upper() == InterviewMode.STRICT.value:
            return StrictInterviewPolicy()
        return CoachInterviewPolicy()

    async def create_session(
        self,
        db: AsyncSession,
        request: DynamicInterviewCreateRequest,
        user_id: int,
    ) -> DynamicInterviewCreateResponse:
        resume_detail = None
        if request.resume_id:
            resume_detail = await resume_history_service.get_resume_detail(db, request.resume_id, user_id)

        session_id = uuid.uuid4().hex[:16]
        skill_id = request.skill_id or settings.interview.default_skill_id
        difficulty = request.difficulty or request.level or settings.interview.default_difficulty
        llm_provider = request.llm_provider or "dashscope"
        session = await dynamic_interview_persistence_service.create_planning_session(
            db,
            session_id=session_id,
            user_id=user_id,
            resume_id=request.resume_id,
            skill_id=skill_id,
            difficulty=difficulty,
            llm_provider=llm_provider,
            target_role=request.target_role,
            target_company=request.target_company,
            level=request.level,
            jd_text=request.jd_text,
            interview_mode=request.mode.upper(),
            plan_summary={
                "generation_status": SessionStatus.PLANNING.value,
                "generation_stages": self._generation_stage_summary(active_key="JD_PARSE"),
            },
        )
        await db.commit()

        import asyncio as _asyncio

        _asyncio.create_task(self._generate_plan_background(session.session_id, request, resume_detail, user_id))

        return DynamicInterviewCreateResponse(
            session_id=session.session_id,
            status=SessionStatus.PLANNING.value,
            structured_jd=jd_parse_service.parse(None, request.target_role, request.skill_id),
            current_topic=None,
            current_turn=None,
            plan_summary={
                "generation_status": SessionStatus.PLANNING.value,
                "generation_stages": self._generation_stage_summary(active_key="JD_PARSE"),
            },
        )

    async def create_topic_retry_session(
        self,
        db: AsyncSession,
        source_session_id: str,
        topic_id: int,
        user_id: int,
    ) -> DynamicInterviewCreateResponse:
        source_session = await dynamic_interview_persistence_service.find_session_or_throw(
            db, source_session_id, user_id
        )
        source_topic = await dynamic_interview_persistence_service.find_topic_or_throw(db, topic_id, user_id)
        if source_topic.session_id != source_session.id:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, "动态面试 topic 不属于当前会话")
        if source_session.status == SessionStatus.PLANNING:
            raise BusinessException(ErrorCode.BAD_REQUEST, "原面试计划仍在生成，暂时不能重练")
        if source_session.status == SessionStatus.FAILED:
            raise BusinessException(ErrorCode.BAD_REQUEST, "原面试计划生成失败，不能基于该 topic 重练")

        structured_jd = dynamic_interview_persistence_service.structured_jd_from_session(
            source_session
        ) or jd_parse_service.parse(source_session.jd_text, source_session.target_role, source_session.skill_id)
        source_plan = dynamic_interview_persistence_service.plan_summary_from_session(source_session)
        retry_session_id = uuid.uuid4().hex[:16]
        retry_plan_summary = {
            "generation_status": SessionStatus.INTERVIEWING.value,
            "retry_source_session_id": source_session.session_id,
            "retry_source_topic_id": source_topic.id,
            "retry_source_topic_title": source_topic.topic_title,
            "topic_count": 1,
            "topics": [
                {
                    "topic_key": source_topic.topic_key,
                    "topic_title": source_topic.topic_title,
                    "question_type": source_topic.question_type,
                    "source_type": source_topic.source_type,
                }
            ],
            "source_plan_summary": {
                key: source_plan.get(key)
                for key in ("target_role", "role_domain", "jd_quality_score")
                if key in source_plan
            },
        }
        retry_session = await dynamic_interview_persistence_service.create_session(
            db,
            session_id=retry_session_id,
            user_id=user_id,
            resume_id=source_session.resume_id,
            skill_id=source_session.skill_id or settings.interview.default_skill_id,
            difficulty=source_session.difficulty or settings.interview.default_difficulty,
            llm_provider=source_session.llm_provider or "dashscope",
            target_role=source_session.target_role,
            target_company=source_session.target_company,
            level=source_session.level,
            jd_text=source_session.jd_text,
            interview_mode=(source_session.interview_mode or InterviewMode.COACH.value).upper(),
            structured_jd=structured_jd,
            plan_summary=retry_plan_summary,
        )
        retry_session.total_questions = 1

        retry_topic_dto = dynamic_interview_persistence_service.topic_to_dto(source_topic).model_copy(
            update={
                "id": None,
                "topic_order": 1,
                "status": TopicStatus.ACTIVE.value,
                "turn_count": 0,
                "best_score": None,
                "final_score": None,
            }
        )
        retry_topic = await dynamic_interview_persistence_service.create_topic(
            db,
            session_entity_id=retry_session.id,
            user_id=user_id,
            resume_id=source_session.resume_id,
            topic=retry_topic_dto,
            evidence_hash=source_topic.evidence_hash or self._evidence_hash(source_topic.evidence_snippet),
        )
        await dynamic_interview_persistence_service.set_current_topic(db, retry_session.id, retry_topic.id)
        first_turn = await dynamic_interview_persistence_service.create_turn(
            db,
            session_entity_id=retry_session.id,
            topic_id=retry_topic.id,
            user_id=user_id,
            turn_type=TurnType.MAIN.value,
            turn_order=1,
            question=retry_topic.main_question,
        )

        logger.info(
            "创建动态 topic 重练会话: source=%s, topic=%s, retry=%s",
            source_session_id,
            topic_id,
            retry_session_id,
        )
        return DynamicInterviewCreateResponse(
            session_id=retry_session.session_id,
            status=SessionStatus.INTERVIEWING.value,
            structured_jd=structured_jd,
            current_topic=dynamic_interview_persistence_service.topic_to_dto(retry_topic),
            current_turn=dynamic_interview_persistence_service.turn_to_dto(first_turn),
            plan_summary=retry_plan_summary,
        )

    async def _generate_plan_background(
        self,
        session_id: str,
        request: DynamicInterviewCreateRequest,
        resume_detail: ResumeDetailDTO | None,
        user_id: int,
    ) -> None:
        from app.database import async_session_factory

        current_operation = "JD_PARSE"
        structured_jd = jd_parse_service.parse(None, request.target_role, request.skill_id)
        session = None
        async with async_session_factory() as bg_db:
            try:
                session = await dynamic_interview_persistence_service.find_session(bg_db, session_id, user_id)
                if session is None:
                    logger.warning("动态面试后台生成未找到会话: session_id=%s", session_id)
                    return

                structured_jd = await self._track_operation(
                    bg_db,
                    session,
                    "JD_PARSE",
                    lambda: jd_parse_service.parse(request.jd_text, request.target_role, request.skill_id),
                )
                recent_topics = await dynamic_interview_persistence_service.list_recent_topic_keys(bg_db, user_id)
                user_profile = await dynamic_interview_persistence_service.get_user_topic_profile(bg_db, user_id)
                current_operation = "TOPIC_PLAN"
                topics, plan_summary = await self._track_operation(
                    bg_db,
                    session,
                    "TOPIC_PLAN",
                    lambda: self.plan_service.build_plan(
                        request,
                        structured_jd,
                        resume_detail,
                        recent_topic_keys=recent_topics,
                        user_topic_profile=user_profile,
                        variation_seed=session_id,
                    ),
                )
            except Exception as exc:
                message = f"面试计划生成失败，可以重试；已保存你的会话配置。错误类型：{exc.__class__.__name__}"
                logger.warning("动态面试计划生成失败: session_id=%s, error=%s", session_id, exc, exc_info=True)
                if session is not None:
                    await dynamic_interview_persistence_service.mark_session_failed(
                        bg_db,
                        session,
                        message=message,
                        plan_summary={
                            "generation_stages": self._generation_stage_summary(failed_key=current_operation),
                        },
                        structured_jd=structured_jd,
                    )
                    await bg_db.commit()
                return

            plan_summary = {
                **plan_summary,
                "generation_status": SessionStatus.INTERVIEWING.value,
                "generation_stages": self._generation_stage_summary(completed=True),
                "latency_targets_ms": {
                    "create_session": 15000,
                    "submit_answer": 10000,
                },
            }
            await dynamic_interview_persistence_service.complete_planning_session(
                bg_db,
                session,
                structured_jd=structured_jd,
                plan_summary=plan_summary,
            )

            topic_entities: list[InterviewTopicEntity] = []
            for topic in topics:
                topic_entity = await dynamic_interview_persistence_service.create_topic(
                    bg_db,
                    session_entity_id=session.id,
                    user_id=user_id,
                    resume_id=request.resume_id,
                    topic=topic,
                    evidence_hash=self._evidence_hash(topic.evidence_snippet),
                )
                topic_entities.append(topic_entity)

            first_topic = topic_entities[0]
            await dynamic_interview_persistence_service.set_current_topic(bg_db, session.id, first_topic.id)
            await self._track_operation(
                bg_db,
                session,
                "MAIN_QUESTION_GENERATE",
                lambda: dynamic_interview_persistence_service.create_turn(
                    bg_db,
                    session_entity_id=session.id,
                    topic_id=first_topic.id,
                    user_id=user_id,
                    turn_type=TurnType.MAIN.value,
                    turn_order=1,
                    question=first_topic.main_question,
                ),
                topic_id=first_topic.id,
            )
            await bg_db.commit()

    async def submit_turn_answer(
        self,
        db: AsyncSession,
        session_id: str,
        turn_id: int,
        request: SubmitDynamicTurnAnswerRequest,
        user_id: int,
    ) -> DynamicTurnAnswerResponse:
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)
        if session.status == SessionStatus.COMPLETED:
            raise BusinessException(ErrorCode.INTERVIEW_ALREADY_COMPLETED)
        if session.status == SessionStatus.PLANNING:
            raise BusinessException(ErrorCode.BAD_REQUEST, "面试计划仍在生成，请稍后刷新")
        if session.status == SessionStatus.FAILED:
            raise BusinessException(ErrorCode.BAD_REQUEST, "面试计划生成失败，请返回创建页重试")

        turn = await dynamic_interview_persistence_service.find_turn_or_throw(db, turn_id, session.id, user_id)
        if turn.answer is not None:
            raise BusinessException(ErrorCode.BAD_REQUEST, "该轮回答已提交，不能重复提交")

        topic_entity = await dynamic_interview_persistence_service.find_topic_or_throw(db, turn.topic_id, user_id)
        topic = dynamic_interview_persistence_service.topic_to_dto(topic_entity)
        previous_turns = [
            dynamic_interview_persistence_service.turn_to_dto(item)
            for item in await dynamic_interview_persistence_service.list_turns_by_topic(db, topic_entity.id)
            if item.answer is not None
        ]
        turn_dto = dynamic_interview_persistence_service.turn_to_dto(turn)
        try:
            evaluation = await self._track_operation(
                db,
                session,
                "ANSWER_EVALUATE",
                lambda: self.evaluator.evaluate(topic, turn_dto, request.answer, previous_turns),
                topic_id=topic_entity.id,
                turn_id=turn.id,
            )
        except Exception as exc:
            logger.warning(
                "动态面试评分失败，使用兜底评分: session_id=%s, turn_id=%s, error=%s", session_id, turn_id, exc
            )
            evaluation = self.evaluator.fallback_evaluation(topic)

        try:
            coach_hint = None
            if session.interview_mode != InterviewMode.STRICT.value:
                coach_hint = await self._track_operation(
                    db,
                    session,
                    "COACH_HINT_GENERATE",
                    lambda: self.evaluator.coach_hint(topic, evaluation),
                    topic_id=topic_entity.id,
                    turn_id=turn.id,
                )
        except Exception as exc:
            logger.warning(
                "动态面试教练提示失败，使用规则提示: session_id=%s, turn_id=%s, error=%s", session_id, turn_id, exc
            )
            coach_hint = (
                None
                if session.interview_mode == InterviewMode.STRICT.value
                else self.evaluator.fallback_coach_hint(topic, evaluation)
            )

        answered_after = previous_turns + [
            turn_dto.model_copy(update={"answer": request.answer, "ability_score": evaluation.ability_score})
        ]
        all_topics = await dynamic_interview_persistence_service.list_topics(db, session.id)
        next_topic_entity = self._next_pending_topic(all_topics, topic_entity.topic_order)
        policy = self._policy_for_mode(session.interview_mode)
        decision = policy.decide(
            topic=topic,
            turn=turn_dto,
            evaluation=evaluation,
            answered_turns_after_current=answered_after,
            has_next_topic=next_topic_entity is not None,
            coach_hint=coach_hint,
        )
        if decision.action != DecisionAction.COACH_RETRY.value:
            coach_hint = None

        await dynamic_interview_persistence_service.save_turn_answer(
            db,
            turn,
            answer=request.answer,
            ability_score=evaluation.ability_score,
            feedback=evaluation.feedback,
            signals=evaluation.signals,
            evaluation=evaluation.model_dump(),
            decision_action=decision.action,
            decision=decision.model_dump(),
            coach_hint=coach_hint,
        )

        refreshed_turns = await dynamic_interview_persistence_service.list_turns_by_topic(db, topic_entity.id)
        answered_turns = [item for item in refreshed_turns if item.answer is not None]
        scores = [item.ability_score or 0 for item in answered_turns]
        completed = decision.action in {DecisionAction.NEXT_TOPIC.value, DecisionAction.END.value}
        await dynamic_interview_persistence_service.update_topic_after_answer(
            db,
            topic_entity,
            turn_count=len(answered_turns),
            best_score=max(scores) if scores else None,
            final_score=scores[-1] if scores else None,
            completed=completed,
        )

        next_turn = None
        current_topic = dynamic_interview_persistence_service.topic_to_dto(topic_entity)
        report = None
        if decision.action == DecisionAction.COACH_RETRY.value:
            next_turn_entity = await dynamic_interview_persistence_service.create_turn(
                db,
                session_entity_id=session.id,
                topic_id=topic_entity.id,
                user_id=user_id,
                turn_type=TurnType.COACH_RETRY.value,
                turn_order=len(refreshed_turns) + 1,
                question=topic_entity.main_question,
                coach_hint=coach_hint,
            )
            next_turn = dynamic_interview_persistence_service.turn_to_dto(next_turn_entity)
        elif decision.action == DecisionAction.FOLLOW_UP.value:
            next_turn_entity = await dynamic_interview_persistence_service.create_turn(
                db,
                session_entity_id=session.id,
                topic_id=topic_entity.id,
                user_id=user_id,
                turn_type=TurnType.FOLLOW_UP.value,
                turn_order=len(refreshed_turns) + 1,
                question=decision.next_question or topic_entity.main_question,
            )
            next_turn = dynamic_interview_persistence_service.turn_to_dto(next_turn_entity)
        elif decision.action == DecisionAction.NEXT_TOPIC.value and next_topic_entity is not None:
            await dynamic_interview_persistence_service.activate_topic(db, next_topic_entity.id, session.id)
            existing_next_turns = await dynamic_interview_persistence_service.list_turns_by_topic(
                db, next_topic_entity.id
            )
            next_turn_entity = next(
                (item for item in existing_next_turns if item.turn_type == TurnType.MAIN.value),
                None,
            )
            if next_turn_entity is None:
                next_turn_entity = await dynamic_interview_persistence_service.create_turn(
                    db,
                    session_entity_id=session.id,
                    topic_id=next_topic_entity.id,
                    user_id=user_id,
                    turn_type=TurnType.MAIN.value,
                    turn_order=1,
                    question=next_topic_entity.main_question,
                )
            next_turn = dynamic_interview_persistence_service.turn_to_dto(next_turn_entity)
            current_topic = dynamic_interview_persistence_service.topic_to_dto(next_topic_entity)
        elif decision.action == DecisionAction.END.value:
            report = await self._complete_and_report(db, session)

        return DynamicTurnAnswerResponse(
            status=session.status.value if session.status else SessionStatus.INTERVIEWING.value,
            evaluation=evaluation,
            decision=decision,
            next_turn=next_turn,
            current_topic=current_topic,
            topic_progress={
                "answered_turns": len(answered_turns),
                "max_turns": topic_entity.max_turns,
                "best_score": topic_entity.best_score,
                "final_score": topic_entity.final_score,
            },
            report=report,
        )

    async def get_session_detail(self, db: AsyncSession, session_id: str, user_id: int) -> DynamicSessionDetailDTO:
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)
        topics = await dynamic_interview_persistence_service.list_topics(db, session.id)
        turns = await dynamic_interview_persistence_service.list_turns(db, session.id)
        current_topic = next((topic for topic in topics if topic.id == session.current_topic_id), None)
        current_turn = dynamic_interview_persistence_service.latest_unanswered_turn(turns)
        final_report = None
        if session.final_report_json:
            final_report = DynamicReportDTO(**safe_json_loads(session.final_report_json, {}))
        return DynamicSessionDetailDTO(
            session_id=session.session_id,
            status=session.status.value if session.status else SessionStatus.INTERVIEWING.value,
            mode=session.interview_mode or "COACH",
            target_role=session.target_role,
            jd_text=session.jd_text,
            structured_jd=dynamic_interview_persistence_service.structured_jd_from_session(session),
            topics=[dynamic_interview_persistence_service.topic_to_dto(topic) for topic in topics],
            turns=[dynamic_interview_persistence_service.turn_to_dto(turn) for turn in turns],
            current_topic=dynamic_interview_persistence_service.topic_to_dto(current_topic) if current_topic else None,
            current_turn=dynamic_interview_persistence_service.turn_to_dto(current_turn) if current_turn else None,
            plan_summary=dynamic_interview_persistence_service.plan_summary_from_session(session),
            final_report=final_report,
        )

    async def complete_session(self, db: AsyncSession, session_id: str, user_id: int) -> DynamicReportDTO:
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)
        return await self._complete_and_report(db, session)

    async def get_report(self, db: AsyncSession, session_id: str, user_id: int) -> DynamicReportDTO:
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)
        if session.final_report_json:
            return DynamicReportDTO(**safe_json_loads(session.final_report_json, {}))
        if session.status != SessionStatus.COMPLETED:
            raise BusinessException(ErrorCode.INTERVIEW_NOT_COMPLETED, "动态面试尚未完成，无法查看报告")
        return await self._complete_and_report(db, session)

    async def get_topic_rag_insight(
        self,
        db: AsyncSession,
        session_id: str,
        topic_id: int,
        user_id: int,
    ) -> DynamicTopicRagInsightDTO:
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)
        topic = await dynamic_interview_persistence_service.find_topic_or_throw(db, topic_id, user_id)
        if topic.session_id != session.id:
            raise BusinessException(ErrorCode.INTERVIEW_QUESTION_NOT_FOUND, "动态面试 topic 不属于当前会话")
        turns = await dynamic_interview_persistence_service.list_turns_by_topic(db, topic.id)
        return await self.rag_coach_service.build_topic_insight(db, topic=topic, turns=turns, user_id=user_id)

    async def _complete_and_report(self, db: AsyncSession, session: InterviewSessionEntity) -> DynamicReportDTO:
        topics = await dynamic_interview_persistence_service.list_topics(db, session.id)
        turns = await dynamic_interview_persistence_service.list_turns(db, session.id)
        for topic in topics:
            if topic.status == TopicStatus.ACTIVE.value:
                answered = [turn for turn in turns if turn.topic_id == topic.id and turn.answer]
                scores = [turn.ability_score or 0 for turn in answered]
                await dynamic_interview_persistence_service.update_topic_after_answer(
                    db,
                    topic,
                    turn_count=len(answered),
                    best_score=max(scores) if scores else topic.best_score,
                    final_score=scores[-1] if scores else topic.final_score,
                    completed=True,
                )
        report = await self._track_operation(
            db,
            session,
            "REPORT_GENERATE",
            lambda: self.report_service.build_report(session, topics, turns),
        )
        await dynamic_interview_persistence_service.save_report(
            db,
            session,
            report.model_dump(),
            project_score=report.type_scores.get("project"),
            knowledge_score=report.type_scores.get("knowledge"),
            system_design_score=report.type_scores.get("system_design"),
        )
        return report

    async def _track_operation(
        self,
        db: AsyncSession,
        session: InterviewSessionEntity,
        operation_type: str,
        operation,
        *,
        topic_id: int | None = None,
        turn_id: int | None = None,
    ):
        start = time.perf_counter()
        try:
            result = operation()
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            await dynamic_interview_persistence_service.record_operation_metric(
                db,
                session_entity_id=session.id,
                user_id=session.user_id,
                operation_type=operation_type,
                topic_id=topic_id,
                turn_id=turn_id,
                llm_provider=session.llm_provider,
                latency_ms=self._latency_ms(start),
                success=False,
                error_type=exc.__class__.__name__,
            )
            raise

        await dynamic_interview_persistence_service.record_operation_metric(
            db,
            session_entity_id=session.id,
            user_id=session.user_id,
            operation_type=operation_type,
            topic_id=topic_id,
            turn_id=turn_id,
            llm_provider=session.llm_provider,
            latency_ms=self._latency_ms(start),
            success=True,
        )
        return result

    @classmethod
    def _generation_stage_summary(
        cls,
        *,
        active_key: str | None = None,
        failed_key: str | None = None,
        completed: bool = False,
    ) -> list[dict[str, str]]:
        stages: list[dict[str, str]] = []
        seen_active_or_failed = False
        for key, label in cls.generation_stages:
            if completed:
                status = "COMPLETED"
            elif key == failed_key:
                status = "FAILED"
                seen_active_or_failed = True
            elif key == active_key:
                status = "ACTIVE"
                seen_active_or_failed = True
            elif seen_active_or_failed:
                status = "PENDING"
            else:
                status = "COMPLETED"
            stages.append({"key": key, "label": label, "status": status})
        return stages

    @staticmethod
    def _latency_ms(start: float) -> int:
        return max(0, int((time.perf_counter() - start) * 1000))

    @staticmethod
    def _next_pending_topic(topics: list[InterviewTopicEntity], current_order: int) -> InterviewTopicEntity | None:
        return next(
            (
                topic
                for topic in sorted(topics, key=lambda item: item.topic_order)
                if topic.topic_order > current_order and topic.status == TopicStatus.PENDING.value
            ),
            None,
        )

    @staticmethod
    def _evidence_hash(evidence: str | None) -> str | None:
        if not evidence:
            return None
        return hashlib.sha256(evidence.strip().encode("utf-8")).hexdigest()


dynamic_interview_service = DynamicInterviewService()
