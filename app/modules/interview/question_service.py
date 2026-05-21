import asyncio
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.prompt_utils import load_prompt, render_template
from app.config import settings
from app.modules.interview.schemas import (
    CategoryDTO,
    HistoricalQuestion,
    InterviewQuestionDTO,
    SkillDTO,
)
from app.modules.interview.skill_service import interview_skill_service

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

DEFAULT_QUESTION_TYPE = "GENERAL"
MAX_FOLLOW_UP_COUNT = 2
RESUME_QUESTION_RATIO = 0.6

GENERIC_MODE_SYSTEM_APPEND = """

# 通用面试模式
本次面试无候选人简历，请出该方向的标准面试题。
- 禁止出现"你在简历中提到..."、"你在项目中..."等暗示存在简历的表述
- 问题表述应与简历无关，直接考察该方向的技术能力
"""

DIFFICULTY_DESCRIPTIONS = {
    "junior": "校招/0-1年经验。考察基础概念和简单应用。",
    "mid": "1-3年经验。考察原理理解和实战经验。",
    "senior": "3年+经验。考察架构设计和深度调优。",
}

GENERIC_FALLBACK_QUESTIONS = [
    ("请描述一个你主导解决的技术难题，你的分析思路是什么？", "GENERAL", "综合能力"),
    ("你在做技术方案选型时，通常考虑哪些因素？请举例说明。", "GENERAL", "综合能力"),
    ("请分享一次你处理线上故障的经历，从发现到修复的完整过程。", "GENERAL", "综合能力"),
    ("你如何保证代码质量？介绍你实践过的有效手段。", "GENERAL", "综合能力"),
    ("描述一个你做过的技术优化案例，优化的动机、方案和效果。", "GENERAL", "综合能力"),
    ("你在团队协作中遇到过最大的分歧是什么？如何解决的？", "GENERAL", "综合能力"),
]


class _StructuredDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _KeyPointDTO(_StructuredDTO):
    point: str
    score_range: str = Field(alias="scoreRange")
    weight: str


class _QuestionDTO(_StructuredDTO):
    question: str
    type: str = DEFAULT_QUESTION_TYPE
    category: str | None = None
    topic_summary: str | None = Field(default=None, alias="topicSummary")
    follow_ups: list[str] | None = Field(default=None, alias="followUps")
    question_type: str = Field(default="knowledge", alias="questionType")
    reference_answer: str | None = Field(default=None, alias="referenceAnswer")
    key_points: list[_KeyPointDTO] | None = Field(default=None, alias="keyPoints")


class _QuestionListDTO(_StructuredDTO):
    questions: list[_QuestionDTO] | None = None


class _FollowUpDecisionDTO(_StructuredDTO):
    should_follow_up: bool = Field(alias="shouldFollowUp")
    follow_up_question: str | None = Field(default=None, alias="followUpQuestion")
    reference_answer: str | None = Field(default=None, alias="referenceAnswer")
    key_points: list[_KeyPointDTO] | None = Field(default=None, alias="keyPoints")
    reason: str = ""


class InterviewQuestionService:
    def __init__(self):
        self._skill_system_prompt = load_prompt(_PROMPTS_DIR, "interview-question-skill-system.md")
        self._skill_user_prompt = load_prompt(_PROMPTS_DIR, "interview-question-skill-user.md")
        self._resume_system_prompt = load_prompt(_PROMPTS_DIR, "interview-question-resume-system.md")
        self._resume_user_prompt = load_prompt(_PROMPTS_DIR, "interview-question-resume-user.md")
        self._follow_up_decision_prompt = load_prompt(_PROMPTS_DIR, "follow-up-decision-system.md")

    async def generate_questions(
        self,
        chat_model: ChatOpenAI,
        skill_id: str,
        difficulty: str,
        resume_text: str | None,
        question_count: int,
        historical_questions: list[HistoricalQuestion],
        custom_categories: list[CategoryDTO] | None = None,
        jd_text: str | None = None,
    ) -> list[InterviewQuestionDTO]:
        skill = self._resolve_skill(skill_id, custom_categories, jd_text)
        difficulty_desc = DIFFICULTY_DESCRIPTIONS.get(difficulty or "mid", DIFFICULTY_DESCRIPTIONS["mid"])
        has_resume = bool(resume_text and resume_text.strip())
        historical_section = self._build_historical_section(historical_questions)

        if not has_resume:
            return await self._generate_direction_only(
                chat_model, skill, difficulty_desc, question_count, historical_section
            )

        resume_count = max(1, round(question_count * RESUME_QUESTION_RATIO))
        direction_count = question_count - resume_count

        logger.info(
            "并行出题: skill=%s, total=%d, resumeCount=%d, directionCount=%d",
            skill_id,
            question_count,
            resume_count,
            direction_count,
        )

        try:
            resume_questions, direction_questions = await asyncio.gather(
                self._generate_resume_questions(resume_text, resume_count, skill, difficulty_desc, historical_section),
                self._generate_direction_only(chat_model, skill, difficulty_desc, direction_count, historical_section),
                return_exceptions=True,
            )
        except Exception as e:
            logger.error("并行出题失败: %s", e)
            return await self._generate_direction_only(
                chat_model, skill, difficulty_desc, question_count, historical_section
            )

        if isinstance(resume_questions, Exception):
            logger.error("简历题生成失败，降级为全方向题: %s", resume_questions)
            return await self._generate_direction_only(
                chat_model, skill, difficulty_desc, question_count, historical_section
            )

        if isinstance(direction_questions, Exception):
            logger.error("方向题生成失败: %s", direction_questions)
            if not resume_questions:
                return self._generate_fallback_questions(skill, question_count)
            return resume_questions

        if not resume_questions and not direction_questions:
            logger.warning("简历题和方向题均为空，回退到默认问题")
            return self._generate_fallback_questions(skill, question_count)

        merged = self._merge_question_batches(resume_questions, direction_questions)
        logger.info(
            "并行出题成功: 简历题=%d, 方向题=%d, 合计=%d", len(resume_questions), len(direction_questions), len(merged)
        )
        return merged

    async def _generate_resume_questions(
        self,
        resume_text: str,
        question_count: int,
        skill: SkillDTO,
        difficulty_desc: str,
        historical_section: str,
    ) -> list[InterviewQuestionDTO]:
        try:
            from app.common.ai.llm_provider import llm_registry

            chat_model = llm_registry.get_chat_model(None)

            variables = {
                "questionCount": question_count,
                "skillName": skill.name,
                "skillDescription": skill.description or "",
                "difficultyDescription": difficulty_desc,
                "resumeText": resume_text,
                "historicalSection": historical_section,
            }

            system_prompt = self._resume_system_prompt
            user_prompt = render_template(self._resume_user_prompt, variables)

            dto = await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=_QuestionListDTO,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="简历题生成失败：",
                log_context="简历题",
            )

            questions = self._convert_to_questions(dto)
            questions = self._cap_to_main_count(questions, question_count)
            logger.info(
                "简历题生成完成: 请求=%d, 实际主问题=%d",
                question_count,
                sum(1 for q in questions if not q.is_follow_up),
            )
            return questions
        except BusinessException:
            raise
        except Exception as e:
            logger.error("简历题生成异常: %s", e)
            raise

    async def _generate_direction_only(
        self,
        chat_model: ChatOpenAI,
        skill: SkillDTO,
        difficulty_desc: str,
        question_count: int,
        historical_section: str,
    ) -> list[InterviewQuestionDTO]:
        allocation = interview_skill_service.calculate_allocation(skill.categories, question_count)
        allocation_table = interview_skill_service.build_allocation_description(allocation, skill.categories)

        logger.info("方向题生成: skill=%s, total=%d, allocation=%s", skill.id, question_count, allocation)

        try:
            variables = {
                "questionCount": question_count,
                "difficultyDescription": difficulty_desc,
                "skillName": skill.name,
                "skillDescription": skill.description or "",
                "skillToolCommand": skill.id,
                "allocationTable": allocation_table,
                "historicalSection": historical_section,
                "referenceSection": interview_skill_service.build_reference_section(skill, allocation),
                "jdSection": self._build_jd_section(skill.source_jd),
            }

            system_prompt = self._skill_system_prompt + GENERIC_MODE_SYSTEM_APPEND
            user_prompt = render_template(self._skill_user_prompt, variables)

            dto = await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                output_model=_QuestionListDTO,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="方向题生成失败：",
                log_context="方向题",
            )

            questions = self._convert_to_questions(dto)
            main_count = sum(1 for q in questions if not q.is_follow_up)
            if main_count == 0:
                logger.warning("方向题返回空题单，回退到默认问题")
                return self._generate_fallback_questions(skill, question_count)
            questions = self._cap_to_main_count(questions, question_count)
            logger.info("方向题生成完成: 请求=%d, 实际主问题=%d", question_count, main_count)
            return questions
        except BusinessException:
            raise
        except Exception as e:
            logger.error("方向题生成失败，回退到默认问题: %s", e)
            return self._generate_fallback_questions(skill, question_count)

    def _resolve_skill(
        self, skill_id: str | None, custom_categories: list[CategoryDTO] | None, jd_text: str | None
    ) -> SkillDTO:
        if skill_id == "custom" and custom_categories:
            return interview_skill_service.build_custom_skill(custom_categories, jd_text or "")
        return interview_skill_service.get_skill(skill_id or settings.interview.default_skill_id)

    def _convert_to_questions(self, dto: _QuestionListDTO | None) -> list[InterviewQuestionDTO]:
        from app.modules.interview.schemas import KeyPoint

        questions = []
        if not dto or not dto.questions:
            return questions

        index = 0
        for q in dto.questions:
            if not q.question or not q.question.strip():
                continue
            q_type = q.type.upper() if q.type else DEFAULT_QUESTION_TYPE
            q_question_type = q.question_type if q.question_type else "knowledge"

            key_points = None
            if q.key_points:
                key_points = [
                    KeyPoint(point=kp.point, score_range=kp.score_range, weight=kp.weight) for kp in q.key_points
                ]

            questions.append(
                InterviewQuestionDTO(
                    question_index=index,
                    question=q.question,
                    type=q_type,
                    category=q.category,
                    topic_summary=q.topic_summary,
                    is_follow_up=False,
                    question_type=q_question_type,
                    reference_answer=q.reference_answer,
                    key_points=key_points,
                )
            )
            index += 1

        return questions

    def _cap_to_main_count(
        self, questions: list[InterviewQuestionDTO], max_main_count: int
    ) -> list[InterviewQuestionDTO]:
        current_main = sum(1 for q in questions if not q.is_follow_up)
        if current_main <= max_main_count:
            if current_main < max_main_count:
                logger.warning("AI 生成主问题不足: 请求=%d, 实际=%d", max_main_count, current_main)
            return questions

        capped = []
        main_seen = 0
        for q in questions:
            if not q.is_follow_up:
                main_seen += 1
            if main_seen > max_main_count:
                break
            capped.append(q)
        logger.info("题目截断: 主问题 %d → %d", current_main, max_main_count)
        return capped

    def _merge_question_batches(
        self, first: list[InterviewQuestionDTO], second: list[InterviewQuestionDTO]
    ) -> list[InterviewQuestionDTO]:
        if not second:
            return first
        if not first:
            return second

        offset = len(first)
        merged = list(first)
        for q in second:
            new_index = q.question_index + offset
            new_parent = q.parent_question_index + offset if q.parent_question_index is not None else None
            merged.append(
                InterviewQuestionDTO(
                    question_index=new_index,
                    question=q.question,
                    type=q.type,
                    category=q.category,
                    topic_summary=q.topic_summary,
                    is_follow_up=q.is_follow_up,
                    parent_question_index=new_parent,
                    question_type=q.question_type,
                    reference_answer=q.reference_answer,
                    key_points=q.key_points,
                )
            )
        return merged

    def _generate_fallback_questions(self, skill: SkillDTO, count: int) -> list[InterviewQuestionDTO]:
        categories = skill.categories if skill else []
        questions = []
        index = 0

        if categories:
            for generated in range(count):
                cat = categories[generated % len(categories)]
                question = f'请谈谈你在"{cat.label}"方向的技术理解和实践经验。'
                questions.append(
                    InterviewQuestionDTO(
                        question_index=index,
                        question=question,
                        type=cat.key,
                        category=cat.label,
                        is_follow_up=False,
                        question_type="knowledge",
                    )
                )
                index += 1
            return questions

        for i in range(min(count, len(GENERIC_FALLBACK_QUESTIONS))):
            q_text, q_type, q_cat = GENERIC_FALLBACK_QUESTIONS[i]
            questions.append(
                InterviewQuestionDTO(
                    question_index=index,
                    question=q_text,
                    type=q_type,
                    category=q_cat,
                    is_follow_up=False,
                    question_type="knowledge",
                )
            )
            index += 1
        return questions

    def _build_historical_section(self, historical_questions: list[HistoricalQuestion]) -> str:
        if not historical_questions:
            return "暂无历史提问"

        grouped: dict[str, list[str]] = {}
        for hq in historical_questions:
            q_type = hq.type or DEFAULT_QUESTION_TYPE
            summary = hq.topic_summary or (hq.question[:30] + "…" if len(hq.question) > 30 else hq.question)
            grouped.setdefault(q_type, []).append(summary)

        lines = ["已考过的知识点（避免重复出题）："]
        for q_type, summaries in grouped.items():
            lines.append(f"- {q_type}: {', '.join(summaries)}")
        return "\n".join(lines)

    @staticmethod
    def _build_jd_section(source_jd: str | None) -> str:
        if not source_jd:
            return ""
        return f"## 职位描述（JD）\n根据以下 JD 关键要求出题，确保题目与岗位实际需求相关：\n{source_jd}"

    async def generate_follow_up(
        self,
        chat_model: ChatOpenAI,
        question: str,
        user_answer: str,
        question_type: str = "knowledge",
        category: str | None = None,
        follow_up_count: int = 0,
    ) -> _FollowUpDecisionDTO | None:
        if follow_up_count >= MAX_FOLLOW_UP_COUNT:
            return None

        try:
            from app.common.ai.llm_provider import llm_registry

            model = llm_registry.get_chat_model(None)

            user_prompt = f"""## 原问题
{question}

## 候选人回答
{user_answer}

## 当前已追问次数
{follow_up_count}（最多追问{MAX_FOLLOW_UP_COUNT}次）

## 问题类型
{question_type}"""

            dto = await structured_output_invoker.invoke(
                chat_model=model,
                system_prompt=self._follow_up_decision_prompt,
                user_prompt=user_prompt,
                output_model=_FollowUpDecisionDTO,
                error_code=ErrorCode.INTERVIEW_QUESTION_GENERATION_FAILED,
                error_prefix="追问决策失败：",
                log_context="追问决策",
            )

            if dto.should_follow_up and dto.follow_up_question:
                logger.info("生成追问: 原问题=%s, 原因=%s", question[:30], dto.reason)
                return dto
            else:
                logger.info("不追问: 原因=%s", dto.reason)
                return None
        except Exception as e:
            logger.error("追问生成失败: %s", e)
            return None


interview_question_service = InterviewQuestionService()
