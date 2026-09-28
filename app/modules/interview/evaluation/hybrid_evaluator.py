"""Hybrid Answer Evaluator：Deterministic Guard + LLM Semantic Evaluator + Evidence Validation
+ Score Calibration + Heuristic Fallback。

边界（PR2 核心原则）：

- LLM 只输出「每个 active dimension 的分数 + 原文证据 + 缺口」，**不输出最终 ability_score**；
- 最终分由代码计算：``weighted_average(dimension_scores)`` → hard caps / evidence caps；
- 规则（旧 heuristic）只承担 guard / fallback / coach hint，**不参与正常路径加权**；
- 不接受 ``heuristic * 0.3 + llm * 0.7`` 这类无语义的加权混合。

失败降级链路：timeout / provider exception / 结构化输出非法 / dimension 缺失或多余或重复 /
分数越界 / 0 条有效证据 → ``HEURISTIC_FALLBACK``，answer 提交不受影响。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.prompt_utils import load_prompt, render_template
from app.common.single_flight import build_single_flight_key, single_flight
from app.config import settings
from app.modules.interview.context.models import ContextBudget
from app.modules.interview.evaluation.models import (
    BANNED_SIGNAL_PHRASES,
    CONFIDENCE_TIERS,
    DIMENSION_LABELS,
    EVALUATOR_VERSION,
    EVIDENCE_SUPPORT_THRESHOLD,
    FALLBACK_CONFIDENCE,
    FEEDBACK_STRENGTH_CHARS,
    HIGH_SCORE_CAP,
    HIGH_SCORE_MIN_DIMENSIONS,
    HIGH_SCORE_MIN_EVIDENCE,
    HIGH_SCORE_THRESHOLD,
    KNOWLEDGE_CONFIDENCE_CAP,
    MAX_EVIDENCE_PER_DIMENSION,
    MAX_EVIDENCE_QUOTE_CHARS,
    MAX_EVIDENCE_TOTAL,
    MAX_FEEDBACK_CHARS,
    MAX_SIGNAL_CHARS,
    MAX_SIGNAL_ITEMS,
    MIN_ANSWER_CHARS_FOR_EVIDENCE,
    RULE_ONLY_CONFIDENCE,
    EvaluationSnapshot,
    GuardVerdict,
    LLMEvaluationResult,
    active_dimension_weights,
)
from app.modules.interview.schemas import DynamicTurnEvaluationDTO, EvaluationEvidenceDTO

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "prompts"

MAX_PREVIOUS_TURNS_IN_PROMPT = 3
MAX_PREVIOUS_ANSWER_CHARS = 600
MAX_ASSESSMENT_CHARS = 120


class _EvaluationRejectedError(Exception):
    """该次 LLM 语义评分不可采用（结构与证据校验未通过）。"""


@dataclass(frozen=True)
class HybridEvaluationOutcome:
    evaluation: DynamicTurnEvaluationDTO
    llm_attempted: bool
    llm_error: str | None = None


def _normalize_for_evidence(text: str) -> str:
    """证据比对用的归一化：去掉所有空白并小写（对换行/缩进不敏感）。"""
    return "".join(str(text).split()).lower()


class HybridAnswerEvaluationService:
    """LLM 语义评分 + 确定性校准。"""

    def __init__(self, heuristic_evaluator=None):
        if heuristic_evaluator is None:  # pragma: no cover - 生产路径由 orchestrator 注入
            from app.modules.interview.dynamic_service import DynamicAnswerEvaluationService

            heuristic_evaluator = DynamicAnswerEvaluationService()
        self._heuristic = heuristic_evaluator
        self._system_prompt = load_prompt(_PROMPTS_DIR, "dynamic-answer-evaluator-system.md")
        self._user_prompt = load_prompt(_PROMPTS_DIR, "dynamic-answer-evaluator-user.md")

    # ------------------------------------------------------------------ public

    async def evaluate(
        self,
        snapshot: EvaluationSnapshot,
        answer: str,
        *,
        llm_provider: str | None = None,
    ) -> HybridEvaluationOutcome:
        """评估一次回答。**调用期间不访问数据库，也不持有业务 transaction。**"""
        topic = snapshot.topic
        turn = snapshot.turn
        previous_turns = snapshot.previous_turns
        answer = answer or ""

        # 规则侧始终计算：既作为 fallback 分数来源，也提供 guard 判定
        heuristic = self._heuristic.evaluate(topic, turn, answer, previous_turns)
        guard = self._heuristic.detect_hard_guard(topic, answer)

        if guard.skip_semantic:
            method = "RULE_ONLY" if guard.rule_only else "HEURISTIC_FALLBACK"
            confidence = RULE_ONLY_CONFIDENCE if guard.rule_only else FALLBACK_CONFIDENCE
            return HybridEvaluationOutcome(
                evaluation=self._deterministic_evaluation(
                    heuristic=heuristic, guard=guard, method=method, confidence=confidence
                ),
                llm_attempted=False,
            )

        if not settings.interview.answer_evaluator_enabled:
            logger.info("Answer Evaluator 已关闭，使用 heuristic fallback: session=%s", snapshot.session_id)
            return HybridEvaluationOutcome(
                evaluation=self._fallback_evaluation(heuristic, guard, "DISABLED"), llm_attempted=False, llm_error=None
            )

        try:
            llm_result = await self._invoke_llm(snapshot, answer, llm_provider)
        except Exception as exc:  # timeout / provider exception / 结构化输出非法
            error_type = exc.__class__.__name__
            logger.warning(
                "LLM semantic evaluation 失败，回退 heuristic: session=%s, turn=%s, error=%s",
                snapshot.session_id,
                turn.id,
                exc,
            )
            return HybridEvaluationOutcome(
                evaluation=self._fallback_evaluation(heuristic, guard, error_type),
                llm_attempted=True,
                llm_error=error_type,
            )

        try:
            evaluation = self._compose_hybrid(topic, answer, llm_result, guard, previous_turns)
        except _EvaluationRejectedError as exc:
            reason = str(exc)
            logger.warning(
                "LLM semantic evaluation 结果被拒绝(%s)，回退 heuristic: session=%s, turn=%s",
                reason,
                snapshot.session_id,
                turn.id,
            )
            return HybridEvaluationOutcome(
                evaluation=self._fallback_evaluation(heuristic, guard, reason),
                llm_attempted=True,
                llm_error=reason,
            )

        return HybridEvaluationOutcome(evaluation=evaluation, llm_attempted=True)

    # ------------------------------------------------------------- LLM invoke

    async def _invoke_llm(
        self,
        snapshot: EvaluationSnapshot,
        answer: str,
        llm_provider: str | None,
    ) -> LLMEvaluationResult:
        weights = active_dimension_weights(snapshot.topic.question_type)
        user_prompt = render_template(
            self._user_prompt,
            {
                "topicTitle": snapshot.topic.topic_title,
                "questionType": snapshot.topic.question_type,
                "mainQuestion": _untrusted(snapshot.topic.main_question),
                "currentQuestion": _untrusted(snapshot.turn.question),
                "activeDimensions": _render_active_dimensions(weights),
                "rubric": _render_list(_safe_items(snapshot.topic.rubric.values())),
                "exitCriteria": _render_list(_safe_items(snapshot.topic.exit_criteria)),
                "followupGoals": _render_list(_safe_items(snapshot.topic.followup_goals)),
                "resumeEvidence": _untrusted(snapshot.topic.evidence_snippet) or "（无）",
                "previousTurns": self._render_previous_turns(snapshot.previous_turns),
                "candidateAnswer": _untrusted(answer),
            },
        )

        key = build_single_flight_key(
            "answer-evaluate",
            EVALUATOR_VERSION,
            FEEDBACK_STRENGTH_CHARS,
            snapshot.session_id,
            snapshot.turn.id,
            snapshot.topic.topic_key,
            snapshot.turn.question,
            _answer_hash(answer),
            (llm_provider or "").strip().lower() or "__default__",
        )

        async def _call() -> str:
            dto = await structured_output_invoker.invoke(
                chat_model=self._chat_model(llm_provider),
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                output_model=LLMEvaluationResult,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="回答语义评分失败：",
                log_context="回答语义评分",
            )
            return dto.model_dump_json()

        raw = await asyncio.wait_for(single_flight(key, _call), timeout=self._timeout_seconds())
        return LLMEvaluationResult.model_validate_json(raw)

    @staticmethod
    def _chat_model(llm_provider: str | None):
        from app.common.ai.llm_provider import llm_registry

        return llm_registry.get_chat_model(llm_provider)

    @staticmethod
    def _timeout_seconds() -> float:
        return max(1.0, float(settings.interview.answer_evaluator_timeout_seconds))

    def _render_previous_turns(self, previous_turns) -> str:
        if not previous_turns:
            return "（这是本 topic 的第一轮回答）"
        lines: list[str] = []
        for turn in previous_turns[-MAX_PREVIOUS_TURNS_IN_PROMPT:]:
            question = _untrusted(turn.question)
            answer = ContextBudget.sanitize(turn.answer or "")[:MAX_PREVIOUS_ANSWER_CHARS]
            lines.append(f"- 面试官：{question}")
            lines.append(f"  候选人：{answer}")
            if turn.ability_score is not None:
                lines.append(f"  （该轮历史分数：{turn.ability_score}）")
        return "\n".join(lines)

    # -------------------------------------------------- validate & compose

    def _compose_hybrid(
        self,
        topic,
        answer: str,
        llm_result: LLMEvaluationResult,
        guard: GuardVerdict,
        previous_turns,
    ) -> DynamicTurnEvaluationDTO:
        weights = active_dimension_weights(topic.question_type)
        active = set(weights)
        assessments = self._validate_dimensions(active, llm_result)

        answer_norm = _normalize_for_evidence(answer)
        evidence: list[EvaluationEvidenceDTO] = []
        gaps: list[str] = []
        strengths: list[str] = []
        dimension_scores: dict[str, int] = {}

        for dimension, assessment in assessments.items():
            dimension_scores[dimension] = assessment.score
            if assessment.score >= EVIDENCE_SUPPORT_THRESHOLD:
                strengths.append(_clip(assessment.assessment or DIMENSION_LABELS.get(dimension, dimension)))
            for gap in assessment.gaps:
                gaps.append(_clip(gap))

            valid_quotes = self._validate_quotes(assessment.evidence_quotes, answer_norm)
            for quote in valid_quotes:
                if len(evidence) >= MAX_EVIDENCE_TOTAL:
                    break
                evidence.append(
                    EvaluationEvidenceDTO(
                        dimension=dimension,
                        quote=quote,
                        assessment="SUPPORT" if assessment.score >= EVIDENCE_SUPPORT_THRESHOLD else "RISK",
                    )
                )

        # 无有效证据的正常长度回答 → 该次语义评分不可信
        if not evidence and len(answer.strip()) >= MIN_ANSWER_CHARS_FOR_EVIDENCE:
            raise _EvaluationRejectedError("NO_VALID_EVIDENCE")

        semantic_score = int(round(sum(score * weights[dim] for dim, score in dimension_scores.items())))

        caps: list[int] = list(guard.hard_caps)
        covered_dimensions = len({item.dimension for item in evidence})
        if semantic_score >= HIGH_SCORE_THRESHOLD and (
            len(evidence) < HIGH_SCORE_MIN_EVIDENCE or covered_dimensions < HIGH_SCORE_MIN_DIMENSIONS
        ):
            caps.append(HIGH_SCORE_CAP)
            guard = GuardVerdict(flags=[*guard.flags, "HIGH_SCORE_EVIDENCE_CAP"], hard_caps=guard.hard_caps)

        final_score = min([semantic_score, *caps]) if caps else semantic_score
        final_score = max(0, min(100, final_score))

        risks = [_clip(item) for item in llm_result.risks]
        strengths = _dedupe_clean(strengths)[:MAX_SIGNAL_ITEMS]
        gaps = _dedupe_clean(gaps)[:MAX_SIGNAL_ITEMS]
        risks = _dedupe_clean(risks)[:MAX_SIGNAL_ITEMS]

        strengths, risks = self._apply_previous_turn_comparison(strengths, risks, final_score, previous_turns)

        confidence = self._confidence(topic.question_type, evidence_count=len(evidence))

        return DynamicTurnEvaluationDTO(
            ability_score=final_score,
            feedback=_build_feedback(final_score, strengths, gaps),
            signals={"strengths": strengths, "gaps": gaps, "risks": risks},
            dimension_scores=dimension_scores,
            evaluation_method="HYBRID_LLM",
            confidence=confidence,
            evidence=evidence,
            guard_flags=guard.flags,
        )

    @staticmethod
    def _validate_dimensions(active: set[str], llm_result: LLMEvaluationResult) -> dict:
        names = [item.dimension for item in llm_result.dimensions]
        if len(names) != len(set(names)):
            raise _EvaluationRejectedError("DUPLICATE_DIMENSION")
        if set(names) != active:
            raise _EvaluationRejectedError("DIMENSION_MISMATCH")
        return {item.dimension: item for item in llm_result.dimensions}

    @staticmethod
    def _validate_quotes(quotes: list[str], answer_norm: str) -> list[str]:
        """只保留能在候选人回答原文中找到的 quote；模型编造的一律丢弃。"""
        valid: list[str] = []
        for raw in quotes:
            quote = " ".join(str(raw).split()).strip().strip('"').strip("“").strip("”")
            if not quote or len(quote) > MAX_EVIDENCE_QUOTE_CHARS:
                continue
            if _normalize_for_evidence(quote) not in answer_norm:
                continue
            valid.append(quote)
            if len(valid) >= MAX_EVIDENCE_PER_DIMENSION:
                break
        return valid

    @staticmethod
    def _apply_previous_turn_comparison(
        strengths: list[str], risks: list[str], final_score: int, previous_turns
    ) -> tuple[list[str], list[str]]:
        """上一轮只用于判断「是否补齐缺口 / 是否明显退步」，**绝不参与分数锚定**。"""
        previous_scores = [turn.ability_score for turn in previous_turns if turn.ability_score is not None]
        if not previous_scores:
            return strengths, risks
        previous_best = max(previous_scores)
        if final_score >= previous_best + 8:
            strengths = [*strengths, "重答后有明显补充"][:MAX_SIGNAL_ITEMS]
        elif final_score <= previous_best + 2:
            risks = [*risks, "提示后提升不明显"][:MAX_SIGNAL_ITEMS]
        return strengths, risks

    @staticmethod
    def _confidence(question_type: str, *, evidence_count: int) -> float:
        confidence = FALLBACK_CONFIDENCE
        for minimum, value in CONFIDENCE_TIERS:
            if evidence_count >= minimum:
                confidence = value
                break
        if (question_type or "").upper() == "KNOWLEDGE":
            # 本轮没有 RAG / reference answer factual grounding，不能假装有事实依据
            confidence = min(confidence, KNOWLEDGE_CONFIDENCE_CAP)
        return round(confidence, 2)

    # ------------------------------------------------------------- fallbacks

    def _deterministic_evaluation(
        self,
        *,
        heuristic: DynamicTurnEvaluationDTO,
        guard: GuardVerdict,
        method: str,
        confidence: float,
    ) -> DynamicTurnEvaluationDTO:
        cap = guard.cap
        score = heuristic.ability_score if cap is None else min(heuristic.ability_score, cap)
        return heuristic.model_copy(
            update={
                "ability_score": max(0, min(100, score)),
                "evaluation_method": method,
                "confidence": round(confidence, 2),
                "evidence": [],
                "guard_flags": guard.flags,
            }
        )

    def _fallback_evaluation(
        self, heuristic: DynamicTurnEvaluationDTO, guard: GuardVerdict, reason: str
    ) -> DynamicTurnEvaluationDTO:
        """heuristic fallback：明确标注来源，绝不假装是 LLM 结果。"""
        capped = self._deterministic_evaluation(
            heuristic=heuristic, guard=guard, method="HEURISTIC_FALLBACK", confidence=FALLBACK_CONFIDENCE
        )
        return capped.model_copy(update={"guard_flags": [*guard.flags, f"FALLBACK:{reason}"]})


def _untrusted(text: str | None) -> str:
    """不可信文本进入 prompt 前：单行折叠 + 模板标记转义。"""
    return ContextBudget.sanitize(text)


def _safe_items(items) -> list[str]:
    return [_untrusted(item) for item in items if item]


def _render_list(items: list[str]) -> str:
    if not items:
        return "（topic 未提供）"
    return "\n".join(f"- {item}" for item in items)


def _render_active_dimensions(weights: dict[str, float]) -> str:
    return "\n".join(
        f"- {dimension}（{DIMENSION_LABELS.get(dimension, dimension)}，权重 {weight:.0%}）"
        for dimension, weight in weights.items()
    )


def _answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode("utf-8")).hexdigest()[:16]


def _clip(text: str | None, limit: int = MAX_SIGNAL_CHARS) -> str:
    collapsed = " ".join(str(text or "").split()).strip()
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}…"


def _dedupe_clean(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = _clip(item)
        if not text or text in result:
            continue
        if any(banned in text for banned in BANNED_SIGNAL_PHRASES):
            # 不允许把「证据不足」写成「造假」这类越界判断
            continue
        result.append(text)
    return result


def _build_feedback(score: int, strengths: list[str], gaps: list[str]) -> str:
    if score >= 85:
        prefix = "回答已经比较扎实"
    elif score >= 70:
        prefix = "回答有基础，但还需要补证据和边界"
    elif score >= 55:
        prefix = "回答覆盖了一部分内容，但面试中容易被继续追问"
    else:
        prefix = "当前回答偏空，需要先按结构补齐核心信息"

    parts = [f"{prefix}。"]
    if score >= 70 and strengths:
        # 只取最亮点的一句摘要，避免整段评语过长
        parts.append(f"已经讲到：{_clip(strengths[0], FEEDBACK_STRENGTH_CHARS)}。")
    if gaps:
        parts.append(f"下一步重点：{'；'.join(_clip(item, FEEDBACK_STRENGTH_CHARS) for item in gaps[:2])}。")
    feedback = "".join(parts)
    return feedback if len(feedback) <= MAX_FEEDBACK_CHARS else f"{feedback[:MAX_FEEDBACK_CHARS]}…"
