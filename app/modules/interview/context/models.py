"""面试对话主链路的上下文模型。

设计约定：

1. ``InterviewContext`` 是「确定性策略层」与「自然语言生成层」之间唯一的状态契约。
   Policy、QuestionRealizer、Prompt 都不允许各自去查库或拼装会话状态，
   只能消费 ``InterviewContextBuilder`` 产出的 Context。
2. 候选人回答、简历证据属于**不可信数据**。它们进入 prompt 之前必须经过：
   - ``ContextBudget`` 的长度截断（防止 context 无限增长 / 超 token）
   - 空白折叠（防止候选人伪造 "面试官：" / "候选人：" 对话行）
   - 模板标记转义（防止 ``{{ ... }}`` 注入到 prompt 模板变量里）
3. 本模块只做「结构化」，不做任何 LLM 调用与 DB 查询。
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

INTERVIEW_MODE_STRICT = "STRICT"
INTERVIEW_MODE_COACH = "COACH"

# 模板标记：不可信数据里出现 "{{" / "}}" 可能被 render_template 二次解析
_TEMPLATE_OPEN = "{{"
_TEMPLATE_CLOSE = "}}"
_TEMPLATE_OPEN_SAFE = "｛｛"
_TEMPLATE_CLOSE_SAFE = "｝｝"

_WHITESPACE_PATTERN = re.compile(r"\s+")


class FollowUpIntent(str, enum.Enum):
    """追问意图（有限集合）。

    Policy 只负责在这 6 个意图里选一个；具体措辞由 QuestionRealizer 生成。
    """

    VERIFY_IMPLEMENTATION = "VERIFY_IMPLEMENTATION"
    VERIFY_BOUNDARY = "VERIFY_BOUNDARY"
    VERIFY_METRIC = "VERIFY_METRIC"
    VERIFY_FAILURE = "VERIFY_FAILURE"
    VERIFY_TRADEOFF = "VERIFY_TRADEOFF"
    VERIFY_OWNERSHIP = "VERIFY_OWNERSHIP"


FOLLOW_UP_INTENT_GUIDANCE: dict[str, str] = {
    FollowUpIntent.VERIFY_IMPLEMENTATION.value: "验证实现细节：他说的机制/链路到底是怎么落地的",
    FollowUpIntent.VERIFY_BOUNDARY.value: "验证边界条件：异常输入、并发、极端场景下的行为",
    FollowUpIntent.VERIFY_METRIC.value: "验证指标口径：数字怎么测、baseline 是什么、提升如何证明",
    FollowUpIntent.VERIFY_FAILURE.value: "验证故障排查：出问题怎么定位、怎么恢复、怎么兜底",
    FollowUpIntent.VERIFY_TRADEOFF.value: "验证技术取舍：为什么选这个方案，放弃了什么",
    FollowUpIntent.VERIFY_OWNERSHIP.value: "验证个人职责：哪部分是他本人做的，团队边界在哪",
}

DEFAULT_FOLLOW_UP_INTENT = FollowUpIntent.VERIFY_IMPLEMENTATION.value


def intent_guidance(intent: str | None) -> str:
    """把 intent 转成给模型看的中文说明；未知 intent 返回空串（不臆造）。"""
    if not intent:
        return ""
    return FOLLOW_UP_INTENT_GUIDANCE.get(intent, "")


@dataclass(frozen=True)
class ContextBudget:
    """Context 的字符级预算。

    项目当前没有统一的 token budget util，这里先做字符级上限并集中封装，
    避免 magic number 散落在 builder / prompt / realizer 多处。
    后续接入 tokenizer 后只需改这一个地方。
    """

    max_recent_turns: int = 4
    max_turn_question_chars: int = 260
    max_turn_answer_chars: int = 800
    max_current_answer_chars: int = 2000
    max_evidence_chars: int = 400
    max_gap_items: int = 4
    max_gap_item_chars: int = 120
    max_covered_points: int = 6
    max_covered_point_chars: int = 60

    @staticmethod
    def sanitize(text: str | None) -> str:
        """把不可信文本压成单行并中和模板标记。"""
        if not text:
            return ""
        collapsed = _WHITESPACE_PATTERN.sub(" ", str(text)).strip()
        return collapsed.replace(_TEMPLATE_OPEN, _TEMPLATE_OPEN_SAFE).replace(_TEMPLATE_CLOSE, _TEMPLATE_CLOSE_SAFE)

    def clip(self, text: str | None, limit: int) -> str:
        """先 sanitize 再按字符上限截断。"""
        sanitized = self.sanitize(text)
        if len(sanitized) <= limit:
            return sanitized
        return f"{sanitized[:limit]}…"


DEFAULT_CONTEXT_BUDGET = ContextBudget()


class TopicSnapshot(BaseModel):
    """当前（或下一个）topic 的只读快照。"""

    topic_id: int | None = None
    topic_key: str = ""
    topic_title: str = ""
    question_type: str = ""
    main_question: str = ""
    followup_goals: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)


class ContextTurn(BaseModel):
    """一轮已经回答过的 Q/A（不含当前轮）。"""

    turn_order: int = 0
    question: str = ""
    answer: str = ""


class InterviewContext(BaseModel):
    """一次回答之后、生成下一个问题之前，链路需要的全部状态。"""

    session_id: str = ""
    interview_mode: str = INTERVIEW_MODE_COACH

    current_topic: TopicSnapshot = Field(default_factory=TopicSnapshot)
    current_question: str = ""

    recent_turns: list[ContextTurn] = Field(default_factory=list)
    current_answer: str = ""

    resume_evidence: str = ""
    unresolved_gaps: list[str] = Field(default_factory=list)
    covered_points: list[str] = Field(default_factory=list)

    follow_up_count: int = 0
    question_type: str = ""

    def render_history(self) -> str:
        """渲染成给模型看的「当前 Topic 对话历史」。"""
        if not self.recent_turns:
            return "（这是本题目的第一轮回答，暂无历史对话）"
        lines: list[str] = []
        for turn in self.recent_turns:
            lines.append(f"面试官：{turn.question}")
            lines.append(f"候选人：{turn.answer}")
        return "\n".join(lines)

    def render_gaps(self) -> str:
        return self._render_list(self.unresolved_gaps, "（规则评分未识别到明确缺口）")

    def render_covered_points(self) -> str:
        return self._render_list(self.covered_points, "（暂无已覆盖信号）")

    @staticmethod
    def _render_list(items: list[str], empty_text: str) -> str:
        if not items:
            return empty_text
        return "\n".join(f"- {item}" for item in items)

    def fingerprint_parts(self) -> tuple[str, ...]:
        """SingleFlight / 调试用的内容指纹入参。

        只要会影响模型输出的字段都必须进来，否则不同会话状态会错误复用同一份结果。
        """
        parts: list[str] = [
            self.session_id,
            self.interview_mode,
            self.current_topic.topic_key,
            self.current_topic.topic_title,
            self.current_question,
            self.current_answer,
            self.resume_evidence,
            str(self.follow_up_count),
            self.question_type,
        ]
        for turn in self.recent_turns:
            parts.append(f"{turn.turn_order}|{turn.question}|{turn.answer}")
        parts.append("|".join(self.unresolved_gaps))
        parts.append("|".join(self.covered_points))
        return tuple(parts)


class TopicTransitionContext(BaseModel):
    """NEXT_TOPIC 场景的上下文：上一个 topic 的最后回答 + 下一个 topic。"""

    session_id: str = ""
    interview_mode: str = INTERVIEW_MODE_COACH

    previous_topic: TopicSnapshot = Field(default_factory=TopicSnapshot)
    previous_question: str = ""
    previous_answer: str = ""

    next_topic: TopicSnapshot = Field(default_factory=TopicSnapshot)
    resume_evidence: str = ""

    def fingerprint_parts(self) -> tuple[str, ...]:
        return (
            self.session_id,
            self.interview_mode,
            self.previous_topic.topic_key,
            self.previous_question,
            self.previous_answer,
            self.next_topic.topic_key,
            self.next_topic.topic_title,
            self.next_topic.main_question,
            self.resume_evidence,
        )
