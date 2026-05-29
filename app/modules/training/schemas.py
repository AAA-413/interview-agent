from pydantic import BaseModel, Field


class TrainingTaskProgressDTO(BaseModel):
    task_id: str
    status: str = "TODO"
    completed_at: str | None = None
    notes: str | None = None


class UpdateTrainingTaskProgressRequest(BaseModel):
    task_id: str = Field(..., min_length=1, max_length=160)
    status: str = Field(default="COMPLETED", pattern="^(TODO|COMPLETED)$")
    title: str | None = Field(default=None, max_length=300)
    task_type: str | None = Field(default=None, max_length=60)
    source_session_id: str | None = Field(default=None, max_length=36)
    question_index: int | None = None
    notes: str | None = Field(default=None, max_length=1000)


class CalibrationQuestionDTO(BaseModel):
    session_id: str
    question_index: int
    question: str
    category: str | None = None
    question_type: str = "knowledge"
    raw_score: int | None = None
    calibrated_score: int | None = None
    confidence: int = 0
    confidence_label: str
    review_priority: str
    score_band: str
    reasons: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    missing_count: int = 0
    action: str
    retry_attempt_count: int = 0
    latest_retry_score: int | None = None
    latest_retry_delta: int | None = None
    retry_signal: str | None = None


class CalibrationDimensionDTO(BaseModel):
    name: str
    average_score: int
    question_count: int
    weak_count: int
    suggested_action: str


class ScoreCalibrationDTO(BaseModel):
    total_sessions: int = 0
    evaluated_sessions: int = 0
    total_questions: int = 0
    average_raw_score: int = 0
    calibrated_score: int = 0
    confidence: int = 0
    confidence_label: str = "暂无"
    review_needed_count: int = 0
    high_risk_count: int = 0
    summary: str
    questions: list[CalibrationQuestionDTO] = Field(default_factory=list)
    dimensions: list[CalibrationDimensionDTO] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class TrainingTaskDTO(BaseModel):
    id: str
    day: int
    title: str
    task_type: str
    priority: str
    estimate_minutes: int
    reason: str
    source_session_id: str | None = None
    question_index: int | None = None
    action_path: str | None = None
    checklist: list[str] = Field(default_factory=list)
    status: str = "TODO"
    completed_at: str | None = None
    retry_attempt_count: int = 0
    latest_retry_delta: int | None = None
    retry_signal: str | None = None


class TrainingDayDTO(BaseModel):
    day: int
    title: str
    focus: str
    total_minutes: int
    tasks: list[TrainingTaskDTO] = Field(default_factory=list)


class PersonalTrainingPlanDTO(BaseModel):
    days: int
    generated_from: list[str] = Field(default_factory=list)
    readiness_score: int = 0
    summary: str
    calibration: ScoreCalibrationDTO
    plan: list[TrainingDayDTO] = Field(default_factory=list)
    quick_wins: list[str] = Field(default_factory=list)


class TrainingTrendPointDTO(BaseModel):
    date: str
    occurred_at: str | None = None
    label: str
    metric_type: str
    score: int | None = None
    delta: int | None = None
    completed_tasks: int = 0
    source_id: str | None = None


class TrainingTrendDTO(BaseModel):
    summary: str
    latest_interview_score: int | None = None
    latest_resume_score: int | None = None
    latest_retry_delta: int | None = None
    completed_task_count: int = 0
    trend: list[TrainingTrendPointDTO] = Field(default_factory=list)
