from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.organization.models import OrganizationRole


class OrganizationCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class OrganizationMemberAddRequest(BaseModel):
    username_or_email: str = Field(..., min_length=2, max_length=100)
    role: OrganizationRole = OrganizationRole.STUDENT
    note: str | None = Field(default=None, max_length=500)


class OrganizationMemberDTO(BaseModel):
    id: int
    organization_id: int
    user_id: int
    username: str
    email: str
    full_name: str | None = None
    role: OrganizationRole
    note: str | None = None
    joined_at: datetime


class OrganizationDTO(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None = None
    member_count: int = 0
    current_user_role: OrganizationRole
    created_at: datetime
    updated_at: datetime


class OrganizationDashboardSummaryDTO(BaseModel):
    member_count: int = 0
    active_member_count: int = 0
    resume_count: int = 0
    analyzed_resume_count: int = 0
    average_resume_score: int = 0
    interview_count: int = 0
    evaluated_interview_count: int = 0
    retry_session_count: int = 0
    completed_retry_session_count: int = 0
    low_score_question_count: int = 0


class OrganizationMemberTrainingDTO(BaseModel):
    user_id: int
    username: str
    email: str
    full_name: str | None = None
    role: OrganizationRole
    note: str | None = None
    resume_count: int = 0
    analyzed_resume_count: int = 0
    latest_resume_score: int | None = None
    interview_count: int = 0
    evaluated_interview_count: int = 0
    retry_session_count: int = 0
    completed_retry_session_count: int = 0
    low_score_question_count: int = 0
    readiness_score: int = 0
    next_action: str
    last_activity_at: datetime | None = None


class OrganizationDashboardDTO(BaseModel):
    organization_id: int
    generated_at: datetime
    summary: OrganizationDashboardSummaryDTO
    members: list[OrganizationMemberTrainingDTO]
