from datetime import datetime

from pydantic import BaseModel

from app.common.model import AsyncTaskStatus


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


class ResumeAnalysisResponse(BaseModel):
    overall_score: int
    score_detail: ScoreDetail
    summary: str
    strengths: list[str]
    suggestions: list[Suggestion]
    original_text: str = ""


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
