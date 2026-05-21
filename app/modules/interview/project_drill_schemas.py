from pydantic import BaseModel, Field


class ProjectDrillRequest(BaseModel):
    resume_id: int
    target_role: str = Field(..., min_length=2, max_length=80)
    project_name: str | None = Field(default=None, max_length=120)
    target_company: str | None = Field(default=None, max_length=80)
    level: str = Field(default="校招/转岗", max_length=30)
    jd_text: str | None = Field(default=None, max_length=10000)


class ProjectCandidateDTO(BaseModel):
    name: str
    role: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    reason: str


class ProjectDrillQuestionDTO(BaseModel):
    category: str
    question: str
    risk: str
    answer_framework: list[str] = Field(default_factory=list)
    strong_answer_signals: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)


class ProjectDrillDTO(BaseModel):
    resume_id: int
    resume_filename: str
    target_role: str
    target_company: str | None = None
    level: str
    selected_project: ProjectCandidateDTO
    project_candidates: list[ProjectCandidateDTO] = Field(default_factory=list)
    risk_summary: str
    warmup_prompt: str
    questions: list[ProjectDrillQuestionDTO] = Field(default_factory=list)
    practice_checklist: list[str] = Field(default_factory=list)
