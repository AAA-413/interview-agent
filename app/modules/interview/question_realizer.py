"""QuestionRealizer：把 InterviewContext + Policy Intent 变成一句自然的面试问题。

职责边界（本 PR 的核心解耦点）：

- Policy（``StrictInterviewPolicy``）决定「做什么」：FOLLOW_UP / NEXT_TOPIC / END、追问意图。
- QuestionRealizer 决定「怎么问」：追问措辞、topic 转场措辞。
- Realizer **不接管**确定性控制：最大追问次数、topic 生命周期、是否结束都由 Policy 管。
- Realizer 失败（超时 / 异常 / 结构化输出非法）时返回 ``None``，由调用方回退规则模板，
  面试链路不会因为模型生成失败而中断。

LLM 调用复用项目既有的 ``structured_output_invoker`` + ``llm_registry``，不新增封装。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.prompt_utils import load_prompt, render_template
from app.common.single_flight import build_single_flight_key, single_flight
from app.config import settings
from app.modules.interview.context.models import (
    INTERVIEW_MODE_STRICT,
    FollowUpIntent,
    InterviewContext,
    TopicTransitionContext,
    intent_guidance,
)
from app.modules.interview.schemas import DynamicDecisionDTO

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# 输出长度保护：防止模型把追问写成一段教学材料
MAX_FOLLOW_UP_QUESTION_CHARS = 300
MAX_TRANSITION_CHARS = 120


class _StructuredDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _FollowUpQuestionDTO(_StructuredDTO):
    question: str
    anchor: str | None = None


class _TransitionDTO(_StructuredDTO):
    """只输出转场语：下一题由 Planner 的 main_question 决定，不允许 LLM 改写。"""

    transition: str = ""


class QuestionRealizerService:
    """LLM 问题生成服务（FOLLOW_UP + NEXT_TOPIC 两个场景）。"""

    def __init__(self):
        self._followup_system_prompt = load_prompt(_PROMPTS_DIR, "dynamic-followup-realizer-system.md")
        self._followup_user_prompt = load_prompt(_PROMPTS_DIR, "dynamic-followup-realizer-user.md")
        self._transition_system_prompt = load_prompt(_PROMPTS_DIR, "dynamic-topic-transition-system.md")
        self._transition_user_prompt = load_prompt(_PROMPTS_DIR, "dynamic-topic-transition-user.md")

    # ---------- 场景 A：FOLLOW_UP ----------

    async def realize_follow_up(
        self,
        context: InterviewContext,
        decision: DynamicDecisionDTO,
    ) -> str | None:
        """根据上下文 + 追问意图生成追问原话；失败返回 ``None``（调用方回退模板）。"""
        if not self._enabled():
            return None
        if not context.current_answer.strip():
            logger.info("QuestionRealizer 跳过：当前回答为空, session=%s", context.session_id)
            return None

        intent = decision.follow_up_intent or FollowUpIntent.VERIFY_IMPLEMENTATION.value
        user_prompt = render_template(
            self._followup_user_prompt,
            {
                "topicTitle": context.current_topic.topic_title,
                "topicMainQuestion": context.current_topic.main_question,
                "questionType": context.question_type or context.current_topic.question_type,
                "followUpIntent": intent,
                "intentGuidance": intent_guidance(intent),
                "targetGap": decision.target_gap or "（未指定具体缺口，请基于候选人回答自行判断）",
                "followUpCount": context.follow_up_count,
                "conversationHistory": context.render_history(),
                "currentQuestion": context.current_question,
                "currentAnswer": context.current_answer,
                "coveredPoints": context.render_covered_points(),
                "resumeEvidence": context.resume_evidence or "（无）",
            },
        )

        key = build_single_flight_key(
            "followup-realize",
            *context.fingerprint_parts(),
            intent,
            decision.target_gap or "",
        )

        async def _invoke() -> str:
            dto = await structured_output_invoker.invoke(
                chat_model=self._chat_model(),
                system_prompt=self._system_prompt(context.interview_mode),
                user_prompt=user_prompt,
                output_model=_FollowUpQuestionDTO,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="追问生成失败：",
                log_context="追问生成",
            )
            return dto.model_dump_json()

        raw = await asyncio.wait_for(
            single_flight(key, _invoke),
            timeout=self._timeout_seconds(),
        )
        dto = _FollowUpQuestionDTO.model_validate_json(raw)
        question = _clean_text(dto.question, MAX_FOLLOW_UP_QUESTION_CHARS)
        if not question:
            logger.warning("QuestionRealizer 返回空追问，回退模板: session=%s", context.session_id)
            return None
        logger.info(
            "QuestionRealizer 生成追问: session=%s, intent=%s, anchor=%s",
            context.session_id,
            intent,
            (dto.anchor or "")[:40],
        )
        return question

    # ---------- 场景 B：NEXT_TOPIC ----------

    async def realize_topic_transition(
        self,
        context: TopicTransitionContext,
    ) -> str | None:
        """只生成「转场语」；失败返回 ``None``（调用方使用 main_question）。

        下一题本身由 Topic Planner / Policy 决定（``next_topic.main_question``），
        LLM 不得改写核心问题语义，只允许负责怎么衔接。
        """
        if not self._enabled():
            return None
        if not context.previous_answer.strip():
            logger.info("QuestionRealizer 跳过转场：上一 topic 无有效回答, session=%s", context.session_id)
            return None

        user_prompt = render_template(
            self._transition_user_prompt,
            {
                "previousTopicTitle": context.previous_topic.topic_title,
                "previousQuestionType": context.previous_topic.question_type,
                "previousQuestion": context.previous_question,
                "previousAnswer": context.previous_answer,
                "nextTopicTitle": context.next_topic.topic_title,
                "nextQuestionType": context.next_topic.question_type,
                "nextMainQuestion": context.next_topic.main_question,
                "resumeEvidence": context.resume_evidence or "（无）",
            },
        )

        key = build_single_flight_key("topic-transition-realize", *context.fingerprint_parts())

        async def _invoke() -> str:
            dto = await structured_output_invoker.invoke(
                chat_model=self._chat_model(),
                system_prompt=self._transition_system_prompt,
                user_prompt=user_prompt,
                output_model=_TransitionDTO,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="topic 转场生成失败：",
                log_context="topic 转场",
            )
            return dto.model_dump_json()

        raw = await asyncio.wait_for(
            single_flight(key, _invoke),
            timeout=self._timeout_seconds(),
        )
        dto = _TransitionDTO.model_validate_json(raw)
        transition = _clean_text(dto.transition, MAX_TRANSITION_CHARS)
        if not transition:
            logger.info("QuestionRealizer 未生成转场语，直接使用主问题: session=%s", context.session_id)
            return None
        return transition

    # ---------- internal ----------

    def _system_prompt(self, interview_mode: str) -> str:
        base = self._followup_system_prompt
        if (interview_mode or "").upper() == INTERVIEW_MODE_STRICT:
            return f"{base}\n\n# 当前模式\nSTRICT：不给提示、不安慰、不引导，只追问。"
        return f"{base}\n\n# 当前模式\nCOACH：可以稍微具体一点地提示追问方向，但依然不给答案。"

    @staticmethod
    def _chat_model():
        # 延迟导入：避免模块加载时就初始化 LLM provider
        from app.common.ai.llm_provider import llm_registry

        return llm_registry.get_chat_model(None)

    @staticmethod
    def _enabled() -> bool:
        return bool(settings.interview.question_realizer_enabled)

    @staticmethod
    def _timeout_seconds() -> float:
        return max(1.0, float(settings.interview.question_realizer_timeout_seconds))


def compose_utterance(transition: str, question: str) -> str:
    """把转场语和下一题拼成面试官的一句话（无转场语时只返回问题）。"""
    if not transition:
        return question
    return f"{transition}\n\n{question}"


def _clean_text(text: str | None, limit: int) -> str:
    """整理模型输出：去空白、去包裹引号、限长。"""
    if not text:
        return ""
    cleaned = " ".join(str(text).split()).strip()
    cleaned = cleaned.strip('"').strip("“").strip("”").strip()
    if len(cleaned) > limit:
        cleaned = f"{cleaned[:limit]}…"
    return cleaned


question_realizer = QuestionRealizerService()
