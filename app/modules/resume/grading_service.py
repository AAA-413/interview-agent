import json
import logging
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.common.ai.structured_output import structured_output_invoker
from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.modules.resume.schemas import ResumeAnalysisResponse, ScoreDetail, Suggestion

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class _SuggestionDTO(BaseModel):
    category: str
    priority: str
    issue: str
    recommendation: str


class _ScoreDetailDTO(BaseModel):
    projectScore: int
    skillMatchScore: int
    contentScore: int
    structureScore: int
    expressionScore: int


class _AnalysisDTO(BaseModel):
    overallScore: int
    scoreDetail: _ScoreDetailDTO
    summary: str
    strengths: list[str]
    suggestions: list[_SuggestionDTO]


class ResumeGradingService:
    def __init__(self):
        self._system_prompt = self._load_prompt("resume-analysis-system.md")
        self._user_prompt_template = self._load_prompt("resume-analysis-user.md")

    @staticmethod
    def _load_prompt(filename: str) -> str:
        path = _PROMPTS_DIR / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        logger.warning("Prompt 文件不存在: %s", path)
        return ""

    async def analyze_resume(self, chat_model: ChatOpenAI, resume_text: str) -> ResumeAnalysisResponse:
        logger.info("开始分析简历，文本长度: %d 字符", len(resume_text))
        try:
            user_prompt = self._user_prompt_template.replace("{{ resumeText }}", resume_text)

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
            content_score=dto.scoreDetail.contentScore,
            structure_score=dto.scoreDetail.structureScore,
            skill_match_score=dto.scoreDetail.skillMatchScore,
            expression_score=dto.scoreDetail.expressionScore,
            project_score=dto.scoreDetail.projectScore,
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
        return ResumeAnalysisResponse(
            overall_score=dto.overallScore,
            score_detail=score_detail,
            summary=dto.summary,
            strengths=dto.strengths,
            suggestions=suggestions,
            original_text=original_text,
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
        )


resume_grading_service = ResumeGradingService()
