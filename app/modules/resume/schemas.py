from datetime import datetime

from pydantic import BaseModel

from app.common.model import AsyncTaskStatus
from app.modules.resume.canonical.models import (
    ResumeCanonicalProfileDTO,
    ResumeCanonicalStatus,
)


class ScoreDetail(BaseModel):
    content_score: int = 0
    structure_score: int = 0
    skill_match_score: int = 0
    expression_score: int = 0
    project_score: int = 0


class Suggestion(BaseModel):
    category: str
    priority: str
    issue: str
    recommendation: str


class ProjectInfo(BaseModel):
    name: str
    role: str
    tech_stack: list[str]
    description: str
    highlights: list[str]


class TechStack(BaseModel):
    name: str
    proficiency: str
    context: str


class ResumeProfile(BaseModel):
    """Legacy 简历画像（PR4 起定位为 **compatibility / display artifact**）。

    保留原因：老数据、旧 API（``ResumeAnalysisResponse.profile``）、已有测试，
    以及 canonical extraction 不可用时的兜底路径。

    注意：**它不是 source-validated canonical facts**。当 canonical READY 时，
    不应作为 interview 的事实来源 —— 事实来源只认
    ``ResumeCanonicalProfileDTO``（每条 claim 都带校验过的简历原文 span）。
    """

    projects: list[ProjectInfo] = []
    tech_stacks: list[TechStack] = []
    experience_level: str = "unknown"
    has_projects: bool = False
    summary: str = ""


class ResumeAnalysisResponse(BaseModel):
    overall_score: int
    score_detail: ScoreDetail
    summary: str
    strengths: list[str]
    suggestions: list[Suggestion]
    original_text: str = ""
    profile: ResumeProfile = ResumeProfile()


class AnalysisHistoryDTO(BaseModel):
    id: int
    overall_score: int | None = None
    content_score: int | None = None
    structure_score: int | None = None
    skill_match_score: int | None = None
    expression_score: int | None = None
    project_score: int | None = None
    summary: str | None = None
    analyzed_at: datetime
    strengths: list[str] = []
    suggestions: list[Suggestion] = []
    profile: ResumeProfile | None = None


class ResumeListItemDTO(BaseModel):
    id: int
    filename: str
    file_size: int | None = None
    uploaded_at: datetime
    access_count: int = 0
    latest_score: int | None = None
    last_analyzed_at: datetime | None = None
    interview_count: int = 0
    analyze_status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    analyze_error: str | None = None


class ResumeDetailDTO(BaseModel):
    id: int
    filename: str
    file_size: int | None = None
    content_type: str | None = None
    storage_url: str | None = None
    uploaded_at: datetime
    access_count: int = 0
    resume_text: str | None = None
    analyze_status: AsyncTaskStatus = AsyncTaskStatus.PENDING
    analyze_error: str | None = None
    analyses: list[AnalysisHistoryDTO] = []

    # ---- PR4：Canonical Resume（全部为 backward-compatible 默认值的附加字段） ----
    canonical_profile: ResumeCanonicalProfileDTO | None = None
    canonical_status: str = ResumeCanonicalStatus.NOT_EXTRACTED.value
    canonical_schema_version: str | None = None
    canonical_extract_error: str | None = None
    canonical_extracted_at: datetime | None = None
