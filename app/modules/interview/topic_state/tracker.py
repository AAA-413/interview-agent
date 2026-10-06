"""TopicCoverageTracker：coverage 状态的确定性 reducer。

职责边界（**非常重要**）：

- 不查 DB、不调 LLM、不操作 ORM
- 输入相同 → 输出相同（纯函数语义）
- 只做三件事：
  1. 把「当前这一轮回答」的 coverage 贡献合并进累计状态（单调，只升不降）
  2. 累积 unique exact-quote 证据与 source_turn_ids
  3. 重算 covered/partial/unresolved、coverage_ratio、complete、next_target

LLM 只负责「这一轮回答对某个 target 覆盖到什么程度」；
「整个 topic 是否问清楚」「还要不要追问」全部由代码决定。
"""

from __future__ import annotations

import json
import logging
import re

from app.modules.interview.evaluation.models import normalize_evidence_text
from app.modules.interview.schemas import (
    COVERAGE_STATUS_COVERED,
    COVERAGE_STATUS_NOT_COVERED,
    COVERAGE_STATUS_PARTIAL,
    DynamicTopicDTO,
    DynamicTurnDTO,
    DynamicTurnEvaluationDTO,
    EvaluationCoverageAssessmentDTO,
    TopicCoveragePointDTO,
    TopicCoverageStateDTO,
    TopicStateDTO,
)
from app.modules.interview.topic_state.models import (
    COVERAGE_STATE_VERSION,
    MAX_COVERAGE_QUOTE_CHARS,
    MAX_EVIDENCE_PER_TARGET,
    build_coverage_state,
    canonical_target_keys,
    coverage_target_map,
    initial_coverage_points,
    merge_coverage_status,
)

logger = logging.getLogger(__name__)

#: heuristic fallback 时用于「最多升到 PARTIAL」的关键词表。
#:
#: 为什么需要它：LLM 超时后如果完全不给 coverage 信号，Policy 会一直看到
#: 「什么都没覆盖」；但只有关键词命中又不足以证明「问清楚了」。因此允许
#: deterministic marker 把状态推到 PARTIAL，**绝不允许推到 COVERED**。
HEURISTIC_COVERAGE_MARKERS: dict[str, tuple[str, ...]] = {
    "PROJECT_GOAL": ("目标", "背景", "需求", "为了", "要解决", "面向"),
    "PROJECT_OWNERSHIP": ("我负责", "我做的", "我主导", "我设计", "我实现", "本人", "我参与"),
    "PROJECT_RESULT_VALIDATION": ("指标", "延迟", "耗时", "成功率", "失败率", "提升", "下降", "p99", "qps", "baseline"),
    "PROJECT_TRADEOFF_OR_FAILURE": ("取舍", "权衡", "放弃", "替代", "异常", "失败", "降级", "重试", "兜底", "超时"),
    "KNOWLEDGE_DEFINITION": ("定义", "是指", "指的是", "本质", "概念"),
    "KNOWLEDGE_MECHANISM": ("原理", "机制", "流程", "步骤", "怎么实现", "内部"),
    "KNOWLEDGE_SCENARIO": ("场景", "适用于", "什么情况", "实践中", "项目里", "落地"),
    "KNOWLEDGE_BOUNDARY": ("边界", "限制", "风险", "不适用", "缺点", "注意", "坑"),
    "SYSTEM_COMPONENTS": ("模块", "组件", "拆分", "分层", "服务"),
    "SYSTEM_DATA_FLOW": ("数据流", "链路", "请求", "调用", "写入", "读取", "消息"),
    "SYSTEM_RELIABILITY": ("可用性", "容灾", "可靠性", "故障", "重试", "降级", "幂等", "一致性", "监控"),
    "SYSTEM_TRADEOFF": ("取舍", "权衡", "成本", "延迟", "放弃", "为什么选"),
}

# 句子切分：用于从回答里取出「包含 marker 的原文句」作为 exact quote。
_SENTENCE_SPLIT_PATTERN = re.compile(r"[。；！？!?;\n]+")


def _clip_quote(text: str) -> str:
    collapsed = " ".join(str(text).split()).strip()
    if len(collapsed) <= MAX_COVERAGE_QUOTE_CHARS:
        return collapsed
    return collapsed[:MAX_COVERAGE_QUOTE_CHARS]


class TopicCoverageTracker:
    """coverage reducer。"""

    # ------------------------------------------------------------------ state

    def initial_state(self, question_type: str | None) -> TopicCoverageStateDTO:
        """按 canonical targets 构造空状态（所有 target = NOT_COVERED）。"""
        return build_coverage_state(initial_coverage_points(question_type), question_type)

    @staticmethod
    def parse_state(raw: str | None, question_type: str | None) -> TopicCoverageStateDTO:
        """把持久化的 ``coverage_state_json`` 解析成状态。

        老 topic 为 NULL、或 JSON 非法 / schema 不兼容 → 直接返回 initial state，
        **不允许**因为脏数据把答题链路打挂，也不需要 backfill。
        """
        tracker = topic_coverage_tracker
        if not raw:
            return tracker.initial_state(question_type)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning("coverage_state_json 解析失败，回退初始状态: %s", exc)
            return tracker.initial_state(question_type)
        if not isinstance(payload, dict):
            logger.warning("coverage_state_json 不是对象，回退初始状态")
            return tracker.initial_state(question_type)
        try:
            state = TopicCoverageStateDTO.model_validate(payload)
        except Exception as exc:  # pydantic 校验失败同样降级
            logger.warning("coverage_state_json schema 不兼容，回退初始状态: %s", exc)
            return tracker.initial_state(question_type)
        return tracker._normalize(state, question_type)

    @staticmethod
    def dump_state(state: TopicCoverageStateDTO) -> str:
        return json.dumps(state.model_dump(), ensure_ascii=False)

    def _normalize(self, state: TopicCoverageStateDTO, question_type: str | None) -> TopicCoverageStateDTO:
        """把任意来源的状态补齐成当前题型完整的 canonical 形态并重算派生字段。

        这样即使持久化数据缺 target（例如题型定义升级过），也能安全继续。
        """
        points = initial_coverage_points(question_type)
        for key, existing in (state.points or {}).items():
            if key in points:
                points[key] = existing
        return build_coverage_state(points, question_type)

    # ----------------------------------------------------------------- update

    def update(
        self,
        *,
        topic: DynamicTopicDTO,
        current_state: TopicCoverageStateDTO,
        turn_id: int,
        answer: str,
        evaluation: DynamicTurnEvaluationDTO,
    ) -> TopicCoverageStateDTO:
        """把当前轮次的 coverage 贡献合并进累计状态（单调）。"""
        question_type = topic.question_type
        state = self._normalize(current_state, question_type)
        method = (evaluation.evaluation_method if evaluation else None) or "HEURISTIC_FALLBACK"

        if method == "RULE_ONLY":
            # 空回答 / 硬失败：不产生任何 coverage 信号，也不允许把状态改坏
            return state

        contributions = self._contributions(
            question_type=question_type,
            answer=answer,
            evaluation=evaluation,
            method=method,
        )
        if not contributions:
            return state

        answer_norm = normalize_evidence_text(answer or "")
        points = {key: point.model_copy(deep=True) for key, point in state.points.items()}

        for contribution in contributions:
            point = points.get(contribution.target_key)
            if point is None:
                # 非 canonical target：直接丢弃，不影响其它 target
                continue

            valid_quotes = self._valid_quotes(contribution.evidence_quotes, answer_norm)
            status = contribution.status
            if status in {COVERAGE_STATUS_PARTIAL, COVERAGE_STATUS_COVERED} and not valid_quotes:
                # 拿不出逐字原文证据 → 不接受 PARTIAL/COVERED，保守降级
                status = COVERAGE_STATUS_NOT_COVERED

            # provenance 只看「当前轮是否真的提供了 positive coverage contribution」，
            # 而不是 merged_status —— 否则 COVERED + 本轮 NOT_COVERED 会错误地
            # 把本轮 turn_id 记进 source_turn_ids、把本轮没讲的 quote 混进去。
            has_positive_contribution = status in {COVERAGE_STATUS_PARTIAL, COVERAGE_STATUS_COVERED} and bool(
                valid_quotes
            )

            merged_status = merge_coverage_status(point.status, status)
            merged_quotes = (
                self._append_quotes(point, valid_quotes) if has_positive_contribution else list(point.evidence_quotes)
            )
            merged_turn_ids = (
                self._append_turn_id(point, turn_id) if has_positive_contribution else list(point.source_turn_ids)
            )

            points[contribution.target_key] = point.model_copy(
                update={
                    "status": merged_status,
                    "evidence_quotes": merged_quotes,
                    "source_turn_ids": merged_turn_ids,
                }
            )

        return build_coverage_state(points, question_type)

    def _contributions(
        self,
        *,
        question_type: str,
        answer: str,
        evaluation: DynamicTurnEvaluationDTO | None,
        method: str,
    ) -> list[EvaluationCoverageAssessmentDTO]:
        if method == "HYBRID_LLM":
            return self._llm_contributions(question_type, evaluation)
        if method == "HEURISTIC_FALLBACK":
            return self.heuristic_contributions(question_type, answer)
        return []

    @staticmethod
    def _llm_contributions(
        question_type: str,
        evaluation: DynamicTurnEvaluationDTO | None,
    ) -> list[EvaluationCoverageAssessmentDTO]:
        """使用 evaluator 已经校验/降级过的 coverage 结果（防御性再过滤一次）。"""
        if evaluation is None:
            return []
        canonical = set(canonical_target_keys(question_type))
        seen: set[str] = set()
        result: list[EvaluationCoverageAssessmentDTO] = []
        for item in evaluation.coverage_assessments or []:
            key = getattr(item, "target_key", None)
            if not key or key not in canonical:
                continue
            if key in seen:
                # duplicate：只保留第一条，不影响其它 target
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def heuristic_contributions(question_type: str, answer: str) -> list[EvaluationCoverageAssessmentDTO]:
        """heuristic fallback：marker 命中最多把 status 推到 ``PARTIAL``。

        防止「LLM 超时 + 碰巧命中关键词」被当成 COVERED，进而让 Topic 提前结束。
        """
        text = (answer or "").lower()
        if not text.strip():
            return []
        targets = coverage_target_map(question_type)
        contributions: list[EvaluationCoverageAssessmentDTO] = []
        for key in canonical_target_keys(question_type):
            markers = HEURISTIC_COVERAGE_MARKERS.get(key)
            if not markers:
                continue
            matched = [marker for marker in markers if marker in text]
            if not matched:
                continue
            quote = _heuristic_quote(answer, matched)
            contributions.append(
                EvaluationCoverageAssessmentDTO(
                    target_key=key,
                    status=COVERAGE_STATUS_PARTIAL,
                    evidence_quotes=[quote] if quote else [],
                )
            )
            if len(contributions) >= len(targets):
                break
        return contributions

    # -------------------------------------------------------------- evidence

    @staticmethod
    def _valid_quotes(quotes: list[str], answer_norm: str) -> list[str]:
        """复用 PR2 的 exact substring 校验：quote 必须逐字来自当前回答。

        这里刻意只做校验、不做「归一化后写回」，保持与评分证据同一套语义。
        """
        valid: list[str] = []
        for raw in quotes or []:
            quote = _clip_quote(raw)
            if not quote:
                continue
            if normalize_evidence_text(quote) not in answer_norm:
                continue
            if quote in valid:
                continue
            valid.append(quote)
        return valid

    @staticmethod
    def _append_quotes(point: TopicCoveragePointDTO, new_quotes: list[str]) -> list[str]:
        """累积 unique exact quote，最多保留 ``MAX_EVIDENCE_PER_TARGET`` 条（保持插入顺序）。"""
        merged = list(point.evidence_quotes or [])
        fingerprints = {normalize_evidence_text(item) for item in merged}
        for quote in new_quotes:
            fingerprint = normalize_evidence_text(quote)
            if fingerprint in fingerprints:
                continue
            merged.append(quote)
            fingerprints.add(fingerprint)
        return merged[:MAX_EVIDENCE_PER_TARGET]

    @staticmethod
    def _append_turn_id(point: TopicCoveragePointDTO, turn_id: int) -> list[int]:
        """追加 source_turn_id（调用方保证本轮确有 positive contribution）。"""
        ids = list(point.source_turn_ids or [])
        if turn_id is None or turn_id in ids:
            return ids
        ids.append(int(turn_id))
        return ids

    # ----------------------------------------------------------- topic state

    def build_state(
        self,
        *,
        topic: DynamicTopicDTO,
        answered_turns: list[DynamicTurnDTO],
        coverage: TopicCoverageStateDTO,
        current_turn_type: str | None = None,
    ) -> TopicStateDTO:
        """由 topic / 已答轮次 / coverage 重建运行态（不整体持久化）。"""
        turn_count = len([turn for turn in answered_turns if turn.answer is not None])
        max_turns = topic.max_turns or 3
        scores = [turn.ability_score for turn in answered_turns if turn.ability_score is not None]
        initial_score = next((turn.ability_score for turn in answered_turns if turn.turn_type == "MAIN"), None)
        current_score = scores[-1] if scores else 0
        best_score = max(scores) if scores else 0
        improvement = current_score - initial_score if initial_score is not None else None
        followup_count = sum(1 for turn in answered_turns if turn.turn_type == "FOLLOW_UP")
        coach_retry_count = sum(1 for turn in answered_turns if turn.turn_type == "COACH_RETRY")

        return TopicStateDTO(
            coverage=coverage,
            turn_count=turn_count,
            max_turns=max_turns,
            remaining_turns=max(0, max_turns - turn_count),
            initial_score=initial_score,
            current_score=current_score,
            best_score=best_score,
            score_improvement=improvement,
            followup_count=followup_count,
            coach_retry_count=coach_retry_count,
        )


def _heuristic_quote(answer: str, markers: list[str]) -> str:
    """从回答里取出「包含 marker 的原文句」——它必然是回答的逐字片段。"""
    for sentence in _SENTENCE_SPLIT_PATTERN.split(answer or ""):
        collapsed = " ".join(sentence.split()).strip()
        if not collapsed:
            continue
        lowered = collapsed.lower()
        if any(marker in lowered for marker in markers):
            return _clip_quote(collapsed)
    return ""


topic_coverage_tracker = TopicCoverageTracker()

__all__ = [
    "COVERAGE_STATE_VERSION",
    "HEURISTIC_COVERAGE_MARKERS",
    "TopicCoverageTracker",
    "topic_coverage_tracker",
]
