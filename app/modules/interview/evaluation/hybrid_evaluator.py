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
    LLMCoverageAssessment,
    LLMEvaluationResult,
    active_dimension_weights,
    filter_active_dimension_scores,
    normalize_evidence_text,
)
from app.modules.interview.schemas import (
    COVERAGE_STATUS_COVERED,
    COVERAGE_STATUS_NOT_COVERED,
    COVERAGE_STATUS_PARTIAL,
    GROUNDED_KNOWLEDGE_VERDICTS,
    KNOWLEDGE_GROUNDING_READY,
    KNOWLEDGE_VERDICT_INSUFFICIENT,
    MAX_GROUNDING_CANDIDATE_QUOTES,
    MAX_GROUNDING_EVIDENCE_IDS,
    DynamicTurnEvaluationDTO,
    EvaluationCoverageAssessmentDTO,
    EvaluationEvidenceDTO,
    KnowledgeGroundingAssessmentDTO,
    KnowledgeGroundingDTO,
)
from app.modules.interview.topic_state.models import (
    COVERAGE_STATUS_RANK,
    MAX_COVERAGE_QUOTES_PER_TURN,
    coverage_target_map,
    coverage_targets_for,
)

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
    """证据比对用的归一化：去掉所有空白并小写（对换行/缩进不敏感）。

    实现收敛在 ``evaluation.models.normalize_evidence_text``：
    评分证据（PR2）与 coverage 证据（PR3）共用同一套 substring 语义。
    """
    return normalize_evidence_text(text)


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
                    question_type=topic.question_type,
                    heuristic=heuristic,
                    guard=guard,
                    method=method,
                    confidence=confidence,
                ),
                llm_attempted=False,
            )

        if not settings.interview.answer_evaluator_enabled:
            logger.info("Answer Evaluator 已关闭，使用 heuristic fallback: session=%s", snapshot.session_id)
            return HybridEvaluationOutcome(
                evaluation=self._fallback_evaluation(topic.question_type, heuristic, guard, "DISABLED"),
                llm_attempted=False,
                llm_error=None,
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
                evaluation=self._fallback_evaluation(topic.question_type, heuristic, guard, error_type),
                llm_attempted=True,
                llm_error=error_type,
            )

        try:
            evaluation = self._compose_hybrid(
                topic, answer, llm_result, guard, previous_turns, snapshot.knowledge_grounding
            )
        except _EvaluationRejectedError as exc:
            reason = str(exc)
            logger.warning(
                "LLM semantic evaluation 结果被拒绝(%s)，回退 heuristic: session=%s, turn=%s",
                reason,
                snapshot.session_id,
                turn.id,
            )
            return HybridEvaluationOutcome(
                evaluation=self._fallback_evaluation(topic.question_type, heuristic, guard, reason),
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
                "coverageTargets": _render_coverage_targets(snapshot.topic.question_type),
                "rubric": _render_rubric(snapshot.topic.rubric, weights),
                "exitCriteria": _render_list(_safe_items(snapshot.topic.exit_criteria)),
                "followupGoals": _render_list(_safe_items(snapshot.topic.followup_goals)),
                "resumeEvidence": _untrusted(snapshot.topic.evidence_snippet) or "（无）",
                "knowledgeEvidence": self._render_knowledge_evidence(snapshot.knowledge_grounding),
                "previousTurns": self._render_previous_turns(snapshot.previous_turns),
                "candidateAnswer": _untrusted(answer),
            },
        )

        # SingleFlight key 必须包含 grounding fingerprint（status + query +
        # sorted(evidence_id, content_hash)）—— 否则用户重新索引知识库后，
        # 相同 question + answer 会错误命中旧 factual context 的评分缓存。
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
            *(snapshot.knowledge_grounding.fingerprint_parts() if snapshot.knowledge_grounding else ()),
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
        """历史轮次**只**给 LLM 看 question / answer。

        刻意不输出 ``ability_score``：历史分数会变成锚点，让模型倾向于把本轮
        压在上一轮分数附近。历史分数的用途只有一个 —— 代码侧的
        ``_apply_previous_turn_comparison()``（比较本轮是否补齐缺口 / 是否退步），
        它不经过 LLM。
        """
        if not previous_turns:
            return "（这是本 topic 的第一轮回答）"
        lines: list[str] = []
        for turn in previous_turns[-MAX_PREVIOUS_TURNS_IN_PROMPT:]:
            question = _untrusted(turn.question)
            answer = ContextBudget.sanitize(turn.answer or "")[:MAX_PREVIOUS_ANSWER_CHARS]
            lines.append(f"- 面试官：{question}")
            lines.append(f"  候选人：{answer}")
        return "\n".join(lines)

    # -------------------------------------------------- validate & compose

    def _compose_hybrid(
        self,
        topic,
        answer: str,
        llm_result: LLMEvaluationResult,
        guard: GuardVerdict,
        previous_turns,
        grounding: KnowledgeGroundingDTO | None = None,
    ) -> DynamicTurnEvaluationDTO:
        weights = active_dimension_weights(topic.question_type)
        active = set(weights)
        assessments = self._validate_dimensions(active, llm_result)

        answer_norm = _normalize_for_evidence(answer)
        evidence: list[EvaluationEvidenceDTO] = []
        gaps: list[str] = []
        strengths: list[str] = []
        dimension_scores: dict[str, int] = {}
        grounded_dimensions: set[str] = set()

        for dimension, assessment in assessments.items():
            dimension_scores[dimension] = assessment.score
            for gap in assessment.gaps:
                gaps.append(_clip(gap))

            valid_quotes = self._validate_quotes(assessment.evidence_quotes, answer_norm)
            if valid_quotes:
                # 只有拿到「该维度自己的」原文证据，才允许这个维度算作有据可依
                grounded_dimensions.add(dimension)
            if assessment.score >= EVIDENCE_SUPPORT_THRESHOLD and dimension in grounded_dimensions:
                strengths.append(_clip(assessment.assessment or DIMENSION_LABELS.get(dimension, dimension)))

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

        # 正向判断（score >= EVIDENCE_SUPPORT_THRESHOLD）必须有该维度自己的原文证据。
        # 同一句 quote 挂在多个维度上不能同时给多个维度「背书」以外的豁免：
        # 只要某个正向维度拿不出自己的 quote，就说明本次语义结果不完整。
        ungrounded_positive = sorted(
            dimension
            for dimension, assessment in assessments.items()
            if assessment.score >= EVIDENCE_SUPPORT_THRESHOLD and dimension not in grounded_dimensions
        )
        if ungrounded_positive:
            raise _EvaluationRejectedError("UNGROUNDED_POSITIVE_DIMENSION")

        # 全局唯一原文证据数：同一句 quote 即使挂在两个维度上，也只能算 1 条。
        # confidence 与高分门槛都必须用它，否则模型重复同一句就能刷高置信度。
        unique_evidence_count = len({_normalize_for_evidence(item.quote) for item in evidence})

        semantic_score = int(round(sum(score * weights[dim] for dim, score in dimension_scores.items())))

        caps: list[int] = list(guard.hard_caps)
        covered_dimensions = len({item.dimension for item in evidence})
        if semantic_score >= HIGH_SCORE_THRESHOLD and (
            unique_evidence_count < HIGH_SCORE_MIN_EVIDENCE or covered_dimensions < HIGH_SCORE_MIN_DIMENSIONS
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

        # PR5：Knowledge Grounding 与 Semantic Evaluation 也是**独立失败域** ——
        # grounding assessment 不合法只是降级为 INSUFFICIENT，绝不影响上面的分数。
        knowledge_grounding = self._build_knowledge_grounding(answer_norm, llm_result, grounding)
        grounded_knowledge = bool(knowledge_grounding and knowledge_grounding.is_validated_grounding())

        confidence = self._confidence(
            topic.question_type,
            unique_evidence_count=unique_evidence_count,
            grounded_knowledge=grounded_knowledge,
        )

        return DynamicTurnEvaluationDTO(
            ability_score=final_score,
            feedback=_build_feedback(final_score, strengths, gaps),
            signals={"strengths": strengths, "gaps": gaps, "risks": risks},
            dimension_scores=filter_active_dimension_scores(topic.question_type, dimension_scores),
            evaluation_method="HYBRID_LLM",
            confidence=confidence,
            evidence=evidence,
            guard_flags=guard.flags,
            # Coverage 与 Score 是**独立失败域**：这里只做保守过滤/降级，
            # 绝不允许 coverage 的局部异常把已经可信的 score 打成 fallback。
            coverage_assessments=self._build_coverage_assessments(topic.question_type, answer_norm, llm_result),
            knowledge_grounding=knowledge_grounding,
        )

    def _build_coverage_assessments(
        self,
        question_type: str,
        answer_norm: str,
        llm_result: LLMEvaluationResult,
    ) -> list[EvaluationCoverageAssessmentDTO]:
        """校验 coverage 输出：unknown → drop / duplicate → 取第一条 / missing → NOT_COVERED。

        本方法必须是**全函数**：任何异常都只能退化成「本轮没有 coverage 贡献」，
        不能向上抛 —— 否则会破坏 score 的可信结果（PR3 §12）。
        """
        try:
            return self._validate_coverage(question_type, answer_norm, llm_result)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning("coverage 校验异常，本轮按无贡献处理（score 不受影响）: %s", exc)
            return []

    def _validate_coverage(
        self,
        question_type: str,
        answer_norm: str,
        llm_result: LLMEvaluationResult,
    ) -> list[EvaluationCoverageAssessmentDTO]:
        canonical = coverage_target_map(question_type)
        by_key: dict[str, LLMCoverageAssessment] = {}
        for item in llm_result.coverage or []:
            key = str(getattr(item, "target_key", "") or "").strip()
            if key not in canonical:
                # unknown（含其它题型的 target）→ 直接丢弃，不影响任何其它 target
                continue
            if key in by_key:
                # duplicate → 只取第一条，不做语义猜测
                continue
            by_key[key] = item

        result: list[EvaluationCoverageAssessmentDTO] = []
        for key, definition in canonical.items():
            item = by_key.get(key)
            if item is None:
                # missing → NOT_COVERED（本轮没有贡献）
                result.append(
                    EvaluationCoverageAssessmentDTO(
                        target_key=key,
                        status=COVERAGE_STATUS_NOT_COVERED,
                    )
                )
                continue

            status = str(getattr(item, "status", "") or "").strip().upper()
            if status not in COVERAGE_STATUS_RANK:
                status = COVERAGE_STATUS_NOT_COVERED

            quotes = self._validate_quotes(list(item.evidence_quotes or []), answer_norm)
            # 每个 target 最多 2 条 quote
            quotes = quotes[:MAX_COVERAGE_QUOTES_PER_TURN]
            if status in {COVERAGE_STATUS_PARTIAL, COVERAGE_STATUS_COVERED} and not quotes:
                # 拿不出逐字原文证据 → 不接受 PARTIAL/COVERED，保守降级
                status = COVERAGE_STATUS_NOT_COVERED

            result.append(EvaluationCoverageAssessmentDTO(target_key=key, status=status, evidence_quotes=quotes))
        return result

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
    def _confidence(question_type: str, *, unique_evidence_count: int, grounded_knowledge: bool = False) -> float:
        """置信度由代码产生，不采信模型自报值。

        ``unique_evidence_count`` 是**去重后**的唯一原文证据条数：同一句 quote
        重复出现或同时挂在两个维度上，都只能算 1 条。

        KNOWLEDGE 默认 cap 0.75 —— 系统无法证明模型判断技术事实时有什么外部依据。
        只有**同时**满足以下条件才解除 cap（见 ``KnowledgeGroundingDTO.is_validated_grounding``）：

        - ``grounding.status == READY`` 且至少 1 条 reference
        - assessment ``validated == True``
        - verdict ∈ {SUPPORTED, PARTIAL, **CONTRADICTED**}
          （CONTRADICTED 也可以高 confidence：confidence 表示「我们对评分判断有多大
          把握」，不是「候选人答得有多好」—— 候选人可以很确定地答错）
        - 至少 1 个代码校验过的 evidence_id + 1 条代码校验过的 candidate quote

        注意：解除 cap **不等于**加分。分数仍完全来自 PR2 的 weighted semantic score。
        """
        confidence = FALLBACK_CONFIDENCE
        for minimum, value in CONFIDENCE_TIERS:
            if unique_evidence_count >= minimum:
                confidence = value
                break
        if (question_type or "").upper() == "KNOWLEDGE" and not grounded_knowledge:
            confidence = min(confidence, KNOWLEDGE_CONFIDENCE_CAP)
        return round(confidence, 2)

    # ------------------------------------------------------- knowledge grounding

    def _build_knowledge_grounding(
        self,
        answer_norm: str,
        llm_result: LLMEvaluationResult,
        grounding: KnowledgeGroundingDTO | None,
    ) -> KnowledgeGroundingDTO | None:
        """把 LLM 的 grounding 判断校验成可持久化的结果。

        与 PR3 coverage 完全同源的失败域原则：grounding 的局部异常**只降级自己**，
        绝不把已经可信的 dimension score 打成 fallback。
        """
        if grounding is None:
            return None
        try:
            grounding.assessment = self._validate_grounding_assessment(answer_norm, llm_result, grounding)
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.warning("knowledge grounding assessment 校验异常，降级 INSUFFICIENT: %s", exc)
            grounding.assessment = KnowledgeGroundingAssessmentDTO()
        return grounding

    def _validate_grounding_assessment(
        self,
        answer_norm: str,
        llm_result: LLMEvaluationResult,
        grounding: KnowledgeGroundingDTO,
    ) -> KnowledgeGroundingAssessmentDTO:
        """代码校验 LLM 的 grounding 判断；LLM 自己说的不算数。

        - ``evidence_ids`` 只允许出现在**最终 prompt 里的** references 中（unknown drop、
          duplicate dedup、最多 4 条）；
        - ``candidate_quotes`` 必须是候选人本轮回答的逐字片段（与 dimension evidence
          同一套 normalize 校验，最多 2 条）；
        - verdict ∈ {SUPPORTED, PARTIAL, CONTRADICTED} 但缺任一侧有效证据 →
          保守降级为 INSUFFICIENT / validated=False。
        """
        assessment = KnowledgeGroundingAssessmentDTO()
        raw = llm_result.knowledge_grounding
        if raw is None or grounding.status != KNOWLEDGE_GROUNDING_READY:
            return assessment

        allowed_ids = {ref.evidence_id for ref in grounding.references}
        valid_ids: list[str] = []
        for raw_id in raw.evidence_ids or []:
            text = str(raw_id or "").strip()
            if text in allowed_ids and text not in valid_ids:
                valid_ids.append(text)
            if len(valid_ids) >= MAX_GROUNDING_EVIDENCE_IDS:
                break

        valid_quotes: list[str] = []
        for raw_quote in raw.candidate_quotes or []:
            if len(valid_quotes) >= MAX_GROUNDING_CANDIDATE_QUOTES:
                break
            quote = str(raw_quote or "").strip()
            if not quote or len(quote) > MAX_EVIDENCE_QUOTE_CHARS:
                continue
            if _normalize_for_evidence(quote) not in answer_norm:
                continue
            if quote in valid_quotes:
                continue
            valid_quotes.append(quote)

        verdict = str(raw.verdict or "").strip().upper()
        if verdict not in GROUNDED_KNOWLEDGE_VERDICTS:
            # 未知 / INSUFFICIENT → 保留已校验的 citation，但不算 grounded
            return KnowledgeGroundingAssessmentDTO(
                verdict=KNOWLEDGE_VERDICT_INSUFFICIENT,
                evidence_ids=valid_ids,
                candidate_quotes=valid_quotes,
                validated=False,
            )

        validated = bool(valid_ids) and bool(valid_quotes)
        return KnowledgeGroundingAssessmentDTO(
            verdict=verdict if validated else KNOWLEDGE_VERDICT_INSUFFICIENT,
            evidence_ids=valid_ids,
            candidate_quotes=valid_quotes,
            validated=validated,
        )

    @staticmethod
    def _render_knowledge_evidence(grounding: KnowledgeGroundingDTO | None) -> str:
        """渲染 KNOWLEDGE_EVIDENCE。

        只渲染**最终 top refs**（LLM 只能引用这些 id），内容直接来自 chunk 前缀，
        不做任何改写。整段作为 untrusted data → **只进 user prompt**。
        """
        if grounding is None or grounding.status != KNOWLEDGE_GROUNDING_READY or not grounding.references:
            return "（无）"
        blocks: list[str] = []
        for ref in grounding.references:
            header = f"[{ref.evidence_id} / {ref.source_name}]"
            if ref.title:
                header = f"{header} title: {ref.title}"
            blocks.append(f"{header}\nscore: {ref.score}\ncontent:\n{_untrusted(ref.content_excerpt)}")
        return "\n\n".join(blocks)

    # ------------------------------------------------------------- fallbacks

    def _deterministic_evaluation(
        self,
        *,
        question_type: str,
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
                # 旧 heuristic evaluator 会返回 5 个维度；RULE_ONLY / HEURISTIC_FALLBACK
                # 同样必须只暴露当前 question_type 的 active dimensions
                "dimension_scores": filter_active_dimension_scores(question_type, heuristic.dimension_scores),
                "guard_flags": guard.flags,
            }
        )

    def _fallback_evaluation(
        self, question_type: str, heuristic: DynamicTurnEvaluationDTO, guard: GuardVerdict, reason: str
    ) -> DynamicTurnEvaluationDTO:
        """heuristic fallback：明确标注来源，绝不假装是 LLM 结果。"""
        capped = self._deterministic_evaluation(
            question_type=question_type,
            heuristic=heuristic,
            guard=guard,
            method="HEURISTIC_FALLBACK",
            confidence=FALLBACK_CONFIDENCE,
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


def _render_rubric(rubric: dict[str, str], active_dimensions) -> str:
    """渲染 rubric，**保留 dimension → description 映射**。

    旧实现直接取 ``rubric.values()`` 会把 key 丢掉，模型只能看到一堆没有归属的
    描述句；这里只输出当前 active dimensions 对应的条目，格式为 ``- <dim>: <desc>``。
    """
    rubric = rubric or {}
    lines: list[str] = []
    for dimension in active_dimensions:
        description = rubric.get(dimension)
        if description:
            lines.append(f"- {dimension}: {_untrusted(description)}")
    return "\n".join(lines) if lines else "（topic 未提供）"


def _render_coverage_targets(question_type: str | None) -> str:
    """渲染 canonical coverage targets（key + 判定说明）。

    target 定义来自 ``topic_state.models`` 的**唯一来源**，这里不重复维护文案。
    """
    definitions = coverage_targets_for(question_type)
    return "\n".join(f"- {definition.key}: {definition.description}" for definition in definitions)


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
