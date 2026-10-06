"""InterviewContext 的统一构造器。

链路里所有需要「当前 topic 对话状态」的组件（Policy 之后的 QuestionRealizer、
Prompt 渲染）都必须从这里拿 Context，不允许各自查库拼装。
"""

from __future__ import annotations

import logging

from app.modules.interview.context.models import (
    DEFAULT_CONTEXT_BUDGET,
    INTERVIEW_MODE_COACH,
    ContextBudget,
    ContextTurn,
    InterviewContext,
    TopicSnapshot,
    TopicTransitionContext,
)
from app.modules.interview.schemas import (
    DynamicTopicDTO,
    DynamicTurnDTO,
    DynamicTurnEvaluationDTO,
    TopicCoverageStateDTO,
)

logger = logging.getLogger(__name__)


class InterviewContextBuilder:
    """把 topic / turn / evaluation 状态折叠成结构化 InterviewContext。"""

    def __init__(self, budget: ContextBudget | None = None):
        self.budget = budget or DEFAULT_CONTEXT_BUDGET

    def build(
        self,
        *,
        session_id: str,
        interview_mode: str | None,
        topic: DynamicTopicDTO,
        current_question: str,
        current_answer: str,
        answered_turns: list[DynamicTurnDTO] | None = None,
        evaluation: DynamicTurnEvaluationDTO | None = None,
        follow_up_count: int = 0,
        coverage_state: TopicCoverageStateDTO | None = None,
        target_coverage_key: str | None = None,
    ) -> InterviewContext:
        """构造 FOLLOW_UP 场景的 Context。

        Args:
            session_id: 会话业务 ID（用于 SingleFlight 指纹与日志）。
            interview_mode: STRICT / COACH。
            topic: 当前 topic。
            current_question: 当前这一轮问的问题。
            current_answer: 候选人刚刚提交的回答（不可信数据）。
            answered_turns: 当前 topic 下**在此之前**已经回答过的轮次。
            evaluation: 当前回答的评分结果。
            follow_up_count: 当前 topic 已经追问过的次数。
            coverage_state: PR3 的 topic 级 coverage 累计状态（None → 全 NOT_COVERED）。
            target_coverage_key: Policy 本轮瞄准的 coverage target。
        """
        budget = self.budget
        recent_turns = self._recent_turns(answered_turns or [], budget)
        coverage = self._coverage_view(topic, coverage_state, target_coverage_key, budget)
        # 有真实 coverage 时以它为准；没有（尚未接入 coverage 的调用方 / 旧测试）
        # 时退回 PR1/PR2 的 strengths 汇总，保证行为不倒退。
        covered_points = (
            coverage["covered"]
            if coverage_state is not None
            else self._legacy_strength_points(answered_turns or [], evaluation, budget)
        )

        return InterviewContext(
            session_id=session_id,
            interview_mode=(interview_mode or INTERVIEW_MODE_COACH).upper(),
            current_topic=self._topic_snapshot(topic, budget),
            current_question=budget.clip(current_question, budget.max_turn_question_chars),
            recent_turns=recent_turns,
            current_answer=budget.clip(current_answer, budget.max_current_answer_chars),
            resume_evidence=budget.clip(topic.evidence_snippet, budget.max_evidence_chars),
            unresolved_gaps=self._unresolved_gaps(evaluation, coverage["unresolved"], budget),
            covered_points=covered_points,
            partial_points=coverage["partial"],
            target_coverage_key=coverage["target_key"],
            target_coverage_label=coverage["target_label"],
            follow_up_count=follow_up_count,
            question_type=topic.question_type,
        )

    def build_topic_transition(
        self,
        *,
        session_id: str,
        interview_mode: str | None,
        previous_topic: DynamicTopicDTO,
        previous_question: str,
        previous_answer: str,
        next_topic: DynamicTopicDTO,
    ) -> TopicTransitionContext:
        """构造 NEXT_TOPIC 场景的 Context（上一个 topic 的最后回答 + 下一个 topic）。"""
        budget = self.budget
        return TopicTransitionContext(
            session_id=session_id,
            interview_mode=(interview_mode or INTERVIEW_MODE_COACH).upper(),
            previous_topic=self._topic_snapshot(previous_topic, budget),
            previous_question=budget.clip(previous_question, budget.max_turn_question_chars),
            previous_answer=budget.clip(previous_answer, budget.max_turn_answer_chars),
            next_topic=self._topic_snapshot(next_topic, budget),
            resume_evidence=budget.clip(next_topic.evidence_snippet, budget.max_evidence_chars),
        )

    def _recent_turns(self, answered_turns: list[DynamicTurnDTO], budget: ContextBudget) -> list[ContextTurn]:
        """只保留当前 topic 最近 N 轮，避免 context 无限增长。"""
        selected = list(answered_turns)[-budget.max_recent_turns :]
        turns: list[ContextTurn] = []
        for turn in selected:
            answer = budget.clip(turn.answer, budget.max_turn_answer_chars)
            if not answer:
                continue
            turns.append(
                ContextTurn(
                    turn_order=turn.turn_order,
                    question=budget.clip(turn.question, budget.max_turn_question_chars),
                    answer=answer,
                )
            )
        return turns

    def _topic_snapshot(self, topic: DynamicTopicDTO, budget: ContextBudget) -> TopicSnapshot:
        return TopicSnapshot(
            topic_id=topic.id,
            topic_key=topic.topic_key,
            topic_title=topic.topic_title,
            question_type=topic.question_type,
            main_question=budget.clip(topic.main_question, budget.max_turn_question_chars),
            followup_goals=[budget.clip(item, budget.max_gap_item_chars) for item in topic.followup_goals][:4],
            exit_criteria=[budget.clip(item, budget.max_covered_point_chars) for item in topic.exit_criteria][:4],
        )

    def _unresolved_gaps(
        self,
        evaluation: DynamicTurnEvaluationDTO | None,
        coverage_unresolved: list[str],
        budget: ContextBudget,
    ) -> list[str]:
        """「还不清楚的点」= coverage 未完全覆盖的 target + 本轮评分识别出的 gaps/risks。

        两者都是「还没讲清楚」的信息，合并后一起去重截断；coverage 优先，
        因为它表达的是 topic 级累计状态，比单轮自由文本更稳定。
        """
        items: list[str] = []
        for item in coverage_unresolved:
            clipped = budget.clip(item, budget.max_gap_item_chars)
            if clipped and clipped not in items:
                items.append(clipped)
            if len(items) >= budget.max_gap_items:
                return items[: budget.max_gap_items]

        if evaluation is not None:
            signals = evaluation.signals or {}
            for key in ("gaps", "risks"):
                for item in signals.get(key) or []:
                    clipped = budget.clip(item, budget.max_gap_item_chars)
                    if clipped and clipped not in items:
                        items.append(clipped)
                if len(items) >= budget.max_gap_items:
                    break
        return items[: budget.max_gap_items]

    def _coverage_view(
        self,
        topic: DynamicTopicDTO,
        coverage_state: TopicCoverageStateDTO | None,
        target_coverage_key: str | None,
        budget: ContextBudget,
    ) -> dict:
        """把 TopicCoverageState 折成 Context 需要的四个视图。

        没有 coverage（PR3 之前的调用方）时返回空视图，Context 行为与 PR1/PR2 一致。
        """
        empty = {"covered": [], "partial": [], "unresolved": [], "target_key": None, "target_label": None}
        if coverage_state is None:
            return empty

        def labels(keys: list[str]) -> list[str]:
            result: list[str] = []
            for key in keys:
                point = coverage_state.points.get(key)
                if point is None:
                    continue
                clipped = budget.clip(point.label or key, budget.max_covered_point_chars)
                if clipped and clipped not in result:
                    result.append(clipped)
                if len(result) >= budget.max_covered_points:
                    break
            return result

        target_point = coverage_state.points.get(target_coverage_key) if target_coverage_key else None
        return {
            "covered": labels(coverage_state.covered_keys),
            "partial": labels(coverage_state.partial_keys),
            # Context 口径：unresolved = PARTIAL + NOT_COVERED
            "unresolved": labels([*coverage_state.partial_keys, *coverage_state.unresolved_keys]),
            "target_key": target_coverage_key,
            "target_label": (target_point.label if target_point else None) or coverage_state.next_target_label,
        }

    def _legacy_strength_points(
        self,
        answered_turns: list[DynamicTurnDTO],
        evaluation: DynamicTurnEvaluationDTO | None,
        budget: ContextBudget,
    ) -> list[str]:
        """PR1/PR2 的 strengths 汇总（保留给没有 coverage 的旧路径/测试使用）。"""
        items: list[str] = []
        for turn in answered_turns:
            for item in self._turn_strengths(turn):
                clipped = budget.clip(item, budget.max_covered_point_chars)
                if clipped and clipped not in items:
                    items.append(clipped)
        if evaluation:
            for item in (evaluation.signals or {}).get("strengths") or []:
                clipped = budget.clip(item, budget.max_covered_point_chars)
                if clipped and clipped not in items:
                    items.append(clipped)
        return items[: budget.max_covered_points]

    @staticmethod
    def _turn_strengths(turn: DynamicTurnDTO) -> list[str]:
        signals = turn.signals or {}
        strengths = signals.get("strengths")
        if strengths:
            return list(strengths)
        evaluation = turn.evaluation or {}
        nested = evaluation.get("signals") if isinstance(evaluation, dict) else None
        if isinstance(nested, dict):
            return list(nested.get("strengths") or [])
        return []


interview_context_builder = InterviewContextBuilder()
