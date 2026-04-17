from datetime import datetime

from pydantic import BaseModel, Field


class InterviewQuestionDTO(BaseModel):
    question_index: int
    question: str
    type: str = "GENERAL"
    category: str | None = None
    topic_summary: str | None = None
    is_follow_up: bool = False
    parent_question_index: int | None = None
    answer: str | None = None


class CreateInterviewRequest(BaseModel):
    resume_id: int | None = None
    resume_text: str | None = None
    skill_id: str | None = None
    difficulty: str | None = None
    question_count: int = 8
    force_create: bool = False
    llm_provider: str | None = None
    custom_categories: list["CategoryDTO"] | None = None
    jd_text: str | None = None


class CategoryDTO(BaseModel):
    key: str
    label: str
    priority: str = "NORMAL"
    ref: str | None = None
    shared: bool | None = None


class SkillCategoryDTO(BaseModel):
    key: str
    label: str
    priority: str = "NORMAL"
    ref: str | None = None
    shared: bool = False


class SkillDTO(BaseModel):
    id: str
    name: str
    description: str | None = None
    categories: list[SkillCategoryDTO] = Field(default_factory=list)
    is_preset: bool = True
    source_jd: str | None = None
    display_name: str | None = None
    persona: str | None = None


class InterviewSessionDTO(BaseModel):
    session_id: str
    resume_text: str = ""
    total_questions: int = 0
    current_question_index: int = 0
    questions: list[InterviewQuestionDTO] = Field(default_factory=list)
    status: str = "CREATED"
    evaluate_status: str | None = None
    evaluate_error: str | None = None


class SubmitAnswerRequest(BaseModel):
    question_index: int
    answer: str


class SubmitAnswerResponse(BaseModel):
    has_next_question: bool
    next_question: InterviewQuestionDTO | None = None
    current_question_index: int
    total_questions: int


class SessionListItemDTO(BaseModel):
    id: int
    session_id: str
    skill_id: str | None = None
    difficulty: str | None = None
    resume_id: int | None = None
    total_questions: int | None = None
    current_question_index: int = 0
    status: str = "CREATED"
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class QuestionEvaluationDTO(BaseModel):
    question_index: int
    question: str
    category: str | None = None
    user_answer: str | None = None
    score: int = 0
    feedback: str | None = None


class ReferenceAnswerDTO(BaseModel):
    question_index: int
    question: str
    reference_answer: str | None = None
    key_points: list[str] = Field(default_factory=list)


class CategoryScoreDTO(BaseModel):
    category: str
    average_score: int
    question_count: int


class InterviewReportDTO(BaseModel):
    session_id: str
    total_questions: int
    overall_score: int = 0
    category_scores: list[CategoryScoreDTO] = Field(default_factory=list)
    question_evaluations: list[QuestionEvaluationDTO] = Field(default_factory=list)
    overall_feedback: str | None = None
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reference_answers: list[ReferenceAnswerDTO] = Field(default_factory=list)


class InterviewDetailDTO(BaseModel):
    session_id: str
    skill_id: str | None = None
    difficulty: str | None = None
    resume_id: int | None = None
    total_questions: int | None = None
    current_question_index: int = 0
    status: str = "CREATED"
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    overall_feedback: str | None = None
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    questions: list[InterviewQuestionDTO] = Field(default_factory=list)
    question_evaluations: list[QuestionEvaluationDTO] = Field(default_factory=list)
    reference_answers: list[ReferenceAnswerDTO] = Field(default_factory=list)
    created_at: datetime | None = None
    completed_at: datetime | None = None


class HistoricalQuestion(BaseModel):
    question: str
    type: str | None = None
    category: str | None = None
    topic_summary: str | None = None
