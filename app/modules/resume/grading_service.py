import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.common.prompt_utils import load_prompt, render_template
from app.modules.resume.schemas import ResumeAnalysisResponse, ResumeProfile, ScoreDetail, Suggestion

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class _StructuredDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _SuggestionDTO(_StructuredDTO):
    category: str
    priority: str
    issue: str
    recommendation: str


class _ScoreDetailDTO(_StructuredDTO):
    project_score: int = Field(alias="projectScore")
    skill_match_score: int = Field(alias="skillMatchScore")
    content_score: int = Field(alias="contentScore")
    structure_score: int = Field(alias="structureScore")
    expression_score: int = Field(alias="expressionScore")


class _ProjectInfoDTO(_StructuredDTO):
    name: str
    role: str
    tech_stack: list[str] = Field(alias="techStack")
    description: str
    highlights: list[str]


class _TechStackDTO(_StructuredDTO):
    name: str
    proficiency: str
    context: str


class _ResumeProfileDTO(_StructuredDTO):
    projects: list[_ProjectInfoDTO]
    tech_stacks: list[_TechStackDTO] = Field(alias="techStacks")
    experience_level: str = Field(alias="experienceLevel")
    has_projects: bool = Field(alias="hasProjects")
    summary: str


class _AnalysisDTO(_StructuredDTO):
    overall_score: int = Field(alias="overallScore")
    score_detail: _ScoreDetailDTO = Field(alias="scoreDetail")
    summary: str
    strengths: list[str]
    suggestions: list[_SuggestionDTO]
    profile: _ResumeProfileDTO


class ResumeGradingService:
    def __init__(self):
        self._system_prompt = load_prompt(_PROMPTS_DIR, "resume-analysis-system.md")
        self._user_prompt_template = load_prompt(_PROMPTS_DIR, "resume-analysis-user.md")

    async def analyze_resume(self, chat_model: ChatOpenAI, resume_text: str) -> ResumeAnalysisResponse:
        logger.info("开始分析简历，文本长度: %d 字符", len(resume_text))
        try:
            user_prompt = render_template(self._user_prompt_template, {"resumeText": resume_text})

            dto = await structured_output_invoker.invoke(
                chat_model=chat_model,
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                output_model=_AnalysisDTO,
                error_code=ErrorCode.AI_SERVICE_ERROR,
                error_prefix="简历分析失败：",
                log_context="简历分析",
            )

            result = self._convert_to_response(dto, resume_text)
            logger.info("简历分析完成，总分: %d", result.overall_score)
            return result
        except BusinessException:
            raise
        except Exception as e:
            logger.error("简历分析失败: %s", str(e))
            return self._create_error_response(resume_text, str(e))

    @staticmethod
    def _convert_to_response(dto: _AnalysisDTO, original_text: str) -> ResumeAnalysisResponse:
        score_detail = ScoreDetail(
            content_score=dto.score_detail.content_score,
            structure_score=dto.score_detail.structure_score,
            skill_match_score=dto.score_detail.skill_match_score,
            expression_score=dto.score_detail.expression_score,
            project_score=dto.score_detail.project_score,
        )
        suggestions = [
            Suggestion(
                category=s.category,
                priority=s.priority,
                issue=s.issue,
                recommendation=s.recommendation,
            )
            for s in dto.suggestions
        ]
        profile = ResumeProfile(
            projects=[
                {
                    "name": p.name,
                    "role": p.role,
                    "tech_stack": p.tech_stack,
                    "description": p.description,
                    "highlights": p.highlights,
                }
                for p in dto.profile.projects
            ],
            tech_stacks=[
                {
                    "name": t.name,
                    "proficiency": t.proficiency,
                    "context": t.context,
                }
                for t in dto.profile.tech_stacks
            ],
            experience_level=dto.profile.experience_level,
            has_projects=dto.profile.has_projects,
            summary=dto.profile.summary,
        )
        return ResumeAnalysisResponse(
            overall_score=dto.overall_score,
            score_detail=score_detail,
            summary=dto.summary,
            strengths=dto.strengths,
            suggestions=suggestions,
            original_text=original_text,
            profile=profile,
        )

    @staticmethod
    def _create_error_response(original_text: str, error_message: str) -> ResumeAnalysisResponse:
        return ResumeAnalysisResponse(
            overall_score=0,
            score_detail=ScoreDetail(),
            summary=f"分析过程中出现错误: {error_message}",
            strengths=[],
            suggestions=[
                Suggestion(
                    category="系统",
                    priority="高",
                    issue="AI分析服务暂时不可用",
                    recommendation="请稍后重试，或检查AI服务是否正常运行",
                )
            ],
            original_text=original_text,
            profile=ResumeProfile(),
        )


resume_grading_service = ResumeGradingService()
