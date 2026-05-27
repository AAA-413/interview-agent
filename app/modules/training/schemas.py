from pydantic import BaseModel, Field


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
