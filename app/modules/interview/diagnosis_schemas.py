from pydantic import BaseModel, Field


class InterviewDiagnosisRequest(BaseModel):
    resume_id: int | None = None
    resume_text: str | None = Field(default=None, max_length=50000)
    target_role: str = Field(..., min_length=2, max_length=80)
    target_company: str | None = Field(default=None, max_length=80)
    level: str = Field(default="校招/转岗", max_length=30)
    jd_text: str | None = Field(default=None, max_length=10000)


class DiagnosisItemDTO(BaseModel):
    title: str
    severity: str = "MEDIUM"
    evidence: str
    impact: str
    action: str


class RiskQuestionDTO(BaseModel):
    question: str
    risk: str
    answer_hint: str


class PracticeTaskDTO(BaseModel):
    title: str
    deliverable: str
    minutes: int = 25
    action_path: str | None = None


class SevenDayPlanItemDTO(BaseModel):
    day: int
    theme: str
    tasks: list[str] = Field(default_factory=list)


class InterviewDiagnosisDTO(BaseModel):
    target_role: str
    target_company: str | None = None
    level: str
    resume_id: int | None = None
    resume_filename: str | None = None
    readiness_score: int
    readiness_level: str
    score_explanation: str
    weakness_summary: str
    diagnosis_basis: list[str] = Field(default_factory=list)
    weaknesses: list[DiagnosisItemDTO] = Field(default_factory=list)
    resume_risks: list[RiskQuestionDTO] = Field(default_factory=list)
    project_follow_up_questions: list[str] = Field(default_factory=list)
    knowledge_gaps: list[DiagnosisItemDTO] = Field(default_factory=list)
    today_tasks: list[PracticeTaskDTO] = Field(default_factory=list)
    seven_day_plan: list[SevenDayPlanItemDTO] = Field(default_factory=list)
    next_actions: list[PracticeTaskDTO] = Field(default_factory=list)
