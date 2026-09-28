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
    ) -> InterviewContext:
        """构造 FOLLOW_UP 场景的 Context。

        Args:
            session_id: 会话业务 ID（用于 SingleFlight 指纹与日志）。
            interview_mode: STRICT / COACH。
            topic: 当前 topic。
            current_question: 当前这一轮问的问题。
            current_answer: 候选人刚刚提交的回答（不可信数据）。
            answered_turns: 当前 topic 下**在此之前**已经回答过的轮次。
            evaluation: 当前回答的规则评分结果。
            follow_up_count: 当前 topic 已经追问过的次数。
        """
        budget = self.budget
        recent_turns = self._recent_turns(answered_turns or [], budget)

        return InterviewContext(
            session_id=session_id,
            interview_mode=(interview_mode or INTERVIEW_MODE_COACH).upper(),
            current_topic=self._topic_snapshot(topic, budget),
            current_question=budget.clip(current_question, budget.max_turn_question_chars),
            recent_turns=recent_turns,
            current_answer=budget.clip(current_answer, budget.max_current_answer_chars),
            resume_evidence=budget.clip(topic.evidence_snippet, budget.max_evidence_chars),
            unresolved_gaps=self._unresolved_gaps(evaluation, budget),
            covered_points=self._covered_points(answered_turns or [], evaluation, budget),
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

    def _unresolved_gaps(self, evaluation: DynamicTurnEvaluationDTO | None, budget: ContextBudget) -> list[str]:
        if evaluation is None:
            return []
        signals = evaluation.signals or {}
        items: list[str] = []
        for key in ("gaps", "risks"):
            for item in signals.get(key) or []:
                clipped = budget.clip(item, budget.max_gap_item_chars)
                if clipped and clipped not in items:
                    items.append(clipped)
            if len(items) >= budget.max_gap_items:
                break
        return items[: budget.max_gap_items]

    def _covered_points(
        self,
        answered_turns: list[DynamicTurnDTO],
        evaluation: DynamicTurnEvaluationDTO | None,
        budget: ContextBudget,
    ) -> list[str]:
        """简单版 coverage：汇总历史轮次 + 当前轮次评分里的 strengths 信号。

        本 PR 不实现完整 TopicTracker，只保证「已经明确答过的点」能被下游看到，
        避免追问重复内容。
        """
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
