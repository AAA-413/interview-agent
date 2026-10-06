"""面试对话主链路的上下文层。

对外只暴露三个入口：
- ``InterviewContextBuilder``：唯一的 Context 构造入口
- ``InterviewContext`` / ``TopicTransitionContext``：结构化上下文
- ``FollowUpIntent``：Policy 产出的追问意图集合
"""

from app.modules.interview.context.builder import InterviewContextBuilder, interview_context_builder
from app.modules.interview.context.models import (
    DEFAULT_CONTEXT_BUDGET,
    FOLLOW_UP_INTENT_GUIDANCE,
    ContextBudget,
    ContextTurn,
    FollowUpIntent,
    InterviewContext,
    TopicSnapshot,
    TopicTransitionContext,
)

__all__ = [
    "DEFAULT_CONTEXT_BUDGET",
    "FOLLOW_UP_INTENT_GUIDANCE",
    "ContextBudget",
    "ContextTurn",
    "FollowUpIntent",
    "InterviewContext",
    "InterviewContextBuilder",
    "TopicSnapshot",
    "TopicTransitionContext",
    "interview_context_builder",
]
