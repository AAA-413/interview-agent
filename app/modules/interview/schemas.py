from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KeyPoint(BaseModel):
    point: str
    score_range: str
    weight: str


class InterviewQuestionDTO(BaseModel):
    question_index: int
    question: str
    type: str = "GENERAL"
    category: str | None = None
    topic_summary: str | None = None
    is_follow_up: bool = False
    parent_question_index: int | None = None
    answer: str | None = None
    question_type: str = "knowledge"
    reference_answer: str | None = None
    key_points: list[KeyPoint] | None = None
    retry_source_session_id: str | None = None
    retry_source_question_index: int | None = None


class CreateInterviewRequest(BaseModel):
    resume_id: int | None = None
    resume_text: str | None = Field(default=None, max_length=50000)
    skill_id: str | None = None
    difficulty: str | None = None
    question_count: int = Field(default=8, ge=1, le=20)
    force_create: bool = False
    llm_provider: str | None = None
    custom_categories: list["CategoryDTO"] | None = None
    jd_text: str | None = Field(default=None, max_length=10000)
    interview_mode: str | None = Field(default=None, max_length=40)
    project_name: str | None = Field(default=None, max_length=120)
    target_role: str | None = Field(default=None, max_length=80)
    target_company: str | None = Field(default=None, max_length=80)
    level: str | None = Field(default=None, max_length=30)


class StructuredJD(BaseModel):
    raw_jd: str = ""
    quality_score: int = Field(default=0, ge=0, le=100)
    quality_level: str = "LOW"
    missing_parts: list[str] = Field(default_factory=list)
    user_suggestion: str | None = None
    role_title: str | None = None
    role_domain: str = "common_engineering"
    seniority: str = "unknown"
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)
    topic_weights: dict[str, float] = Field(default_factory=dict)
    question_type_mix: dict[str, float] = Field(default_factory=dict)


class JDParseRequest(BaseModel):
    target_role: str | None = Field(default=None, max_length=120)
    skill_id: str | None = Field(default=None, max_length=64)
    jd_text: str | None = Field(default=None, max_length=10000)


class DynamicInterviewCreateRequest(BaseModel):
    resume_id: int | None = None
    target_role: str | None = Field(default=None, max_length=120)
    target_company: str | None = Field(default=None, max_length=120)
    level: str | None = Field(default=None, max_length=40)
    jd_text: str | None = Field(default=None, max_length=10000)
    mode: Literal["COACH", "STRICT"] = "COACH"
    topic_count: int = Field(default=4, ge=4, le=4)
    skill_id: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    llm_provider: str | None = Field(default=None, max_length=50)


COVERAGE_STATUS_NOT_COVERED = "NOT_COVERED"
COVERAGE_STATUS_PARTIAL = "PARTIAL"
COVERAGE_STATUS_COVERED = "COVERED"

CoverageStatusLiteral = Literal["NOT_COVERED", "PARTIAL", "COVERED"]


class TopicCoveragePointDTO(BaseModel):
    """单个 canonical coverage target 的**累计**状态。"""

    target_key: str
    label: str = ""
    status: CoverageStatusLiteral = COVERAGE_STATUS_NOT_COVERED
    evidence_quotes: list[str] = Field(default_factory=list)
    source_turn_ids: list[int] = Field(default_factory=list)


class TopicCoverageStateDTO(BaseModel):
    """一个 topic 的 coverage 累计状态（可持久化到 coverage_state_json）。"""

    version: str = "topic-coverage-v1"
    points: dict[str, TopicCoveragePointDTO] = Field(default_factory=dict)

    covered_keys: list[str] = Field(default_factory=list)
    partial_keys: list[str] = Field(default_factory=list)
    unresolved_keys: list[str] = Field(default_factory=list)

    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    complete: bool = False

    next_target_key: str | None = None
    next_target_label: str | None = None


class TopicStateDTO(BaseModel):
    """由确定性数据重建的 topic 运行态视图（**不整体持久化**，只持久化 coverage）。"""

    coverage: TopicCoverageStateDTO = Field(default_factory=TopicCoverageStateDTO)

    turn_count: int = 0
    max_turns: int = 3
    remaining_turns: int = 0

    initial_score: int | None = None
    current_score: int = 0
    best_score: int = 0
    score_improvement: int | None = None

    followup_count: int = 0
    coach_retry_count: int = 0


class DynamicTopicDTO(BaseModel):
    id: int | None = None
    topic_key: str
    topic_title: str
    skill_key: str
    question_type: str
    source_type: str = "mixed"
    evidence_snippet: str | None = None
    main_question: str
    topic_order: int
    status: str = "PENDING"
    max_turns: int = 3
    turn_count: int = 0
    best_score: int | None = None
    final_score: int | None = None
    followup_goals: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    rubric: dict[str, str] = Field(default_factory=dict)
    # PR3：topic 级 coverage 累计状态。backward compatible：老 topic 为 None，
    # 读取方按 initial_state(question_type) 处理，不需要 backfill。
    coverage_state: "TopicCoverageStateDTO | None" = None


class DynamicTurnDTO(BaseModel):
    id: int | None = None
    topic_id: int | None = None
    turn_type: str
    turn_order: int
    question: str
    # 说明：NEXT_TOPIC 时 question 存的是面试官完整话术（转场语 + 下一题），
    # 这样 submit 返回与重新 GET session 的结果完全一致，不引入额外展示字段。
    answer: str | None = None
    ability_score: int | None = None
    decision_action: str | None = None
    feedback: str | None = None
    signals: dict[str, list[str]] = Field(default_factory=dict)
    evaluation: dict = Field(default_factory=dict)
    decision: dict = Field(default_factory=dict)
    coach_hint: dict | None = None
    answered_at: datetime | None = None


class DynamicInterviewCreateResponse(BaseModel):
    session_id: str
    status: str
    structured_jd: StructuredJD
    current_topic: DynamicTopicDTO | None = None
    current_turn: DynamicTurnDTO | None = None
    plan_summary: dict = Field(default_factory=dict)


class SubmitDynamicTurnAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=10000)


class EvaluationEvidenceDTO(BaseModel):
    """评分证据：quote 必须是候选人回答原文片段（非总结、非改写）。"""

    dimension: str
    quote: str
    assessment: Literal["SUPPORT", "RISK"] = "SUPPORT"


class EvaluationCoverageAssessmentDTO(BaseModel):
    """**当前这一轮回答**对某个 canonical coverage target 的贡献。

    - ``target_key`` 必须是当前 question_type 的 canonical target；
    - ``PARTIAL`` / ``COVERED`` 必须至少带 1 条逐字来自当前回答的 quote，
      否则会被代码保守降级为 ``NOT_COVERED``；
    - 历史累计状态不在这里，由 ``TopicCoverageTracker`` 负责。
    """

    target_key: str
    status: CoverageStatusLiteral = COVERAGE_STATUS_NOT_COVERED
    evidence_quotes: list[str] = Field(default_factory=list)


class DynamicTurnEvaluationDTO(BaseModel):
    ability_score: int = Field(default=0, ge=0, le=100)
    feedback: str
    signals: dict[str, list[str]] = Field(default_factory=dict)
    dimension_scores: dict[str, int] = Field(default_factory=dict)

    # ---- PR2 新增：可解释 / 可降级 / 证据驱动（全部带默认值，旧 evaluation_json 仍可解析） ----
    evaluation_method: Literal["HYBRID_LLM", "HEURISTIC_FALLBACK", "RULE_ONLY"] = "HEURISTIC_FALLBACK"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvaluationEvidenceDTO] = Field(default_factory=list)
    guard_flags: list[str] = Field(default_factory=list)

    # ---- PR3 新增：**当前这一轮回答**对 canonical coverage targets 的贡献 ----
    # 只描述 CURRENT CANDIDATE ANSWER；历史累计由 TopicCoverageTracker 负责。
    coverage_assessments: list[EvaluationCoverageAssessmentDTO] = Field(default_factory=list)


class DynamicDecisionDTO(BaseModel):
    action: str
    reason: str
    hint: dict | None = None
    next_question: str | None = None
    # Policy 只产出「意图」，不产出最终措辞；next_question 由 QuestionRealizer 填充，
    # QuestionRealizer 失败时回退为 StrictInterviewPolicy 的模板追问。
    follow_up_intent: str | None = None
    target_gap: str | None = None
    # PR3：这一轮追问瞄准的 canonical coverage target（解释「为什么追这个点」）。
    target_coverage_key: str | None = None


class ConversationTurn(BaseModel):
    """标准面试模式下，当前 topic 内已经发生的一轮 Q/A（不可信数据）。"""

    question: str
    answer: str


class DynamicTurnAnswerResponse(BaseModel):
    status: str = "INTERVIEWING"
    evaluation: DynamicTurnEvaluationDTO
    decision: DynamicDecisionDTO
    next_turn: DynamicTurnDTO | None = None
    current_topic: DynamicTopicDTO | None = None
    topic_progress: dict = Field(default_factory=dict)
    report: "DynamicReportDTO | None" = None


class DynamicSessionDetailDTO(BaseModel):
    session_id: str
    status: str
    mode: str = "COACH"
    target_role: str | None = None
    jd_text: str | None = None
    structured_jd: StructuredJD | None = None
    topics: list[DynamicTopicDTO] = Field(default_factory=list)
    turns: list[DynamicTurnDTO] = Field(default_factory=list)
    current_topic: DynamicTopicDTO | None = None
    current_turn: DynamicTurnDTO | None = None
    plan_summary: dict = Field(default_factory=dict)
    final_report: "DynamicReportDTO | None" = None


class DynamicTopicSummaryDTO(BaseModel):
    topic_id: int | None = None
    topic_key: str
    topic_title: str
    question_type: str
    evidence_snippet: str | None = None
    main_question: str
    initial_score: int | None = None
    final_score: int | None = None
    best_score: int | None = None
    score_delta: int | None = None
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_training_action: str
    # PR3：最终 coverage 展示（只读派生；不影响 readiness_score / type score 公式）
    coverage_ratio: float = 0.0
    covered_points: list[str] = Field(default_factory=list)
    partial_points: list[str] = Field(default_factory=list)
    unresolved_points: list[str] = Field(default_factory=list)


class TomorrowTaskDTO(BaseModel):
    task_type: str
    topic_key: str
    evidence_hash: str | None = None
    weakness_type: str
    priority_score: float
    title: str
    reason: str
    action: str
    status: str = "TODO"


class DynamicReportDTO(BaseModel):
    session_id: str
    readiness_score: int = 0
    type_scores: dict[str, int | None] = Field(default_factory=dict)
    ability_scores: dict[str, int] = Field(default_factory=dict)
    top_risks: list[str] = Field(default_factory=list)
    topic_summaries: list[DynamicTopicSummaryDTO] = Field(default_factory=list)
    tomorrow_tasks: list[TomorrowTaskDTO] = Field(default_factory=list)
    retry_deltas: list[dict] = Field(default_factory=list)
    resume_fix_suggestions: list[str] = Field(default_factory=list)


class DynamicRagCitationDTO(BaseModel):
    knowledge_base_id: int
    chunk_id: int
    source_name: str
    title: str | None = None
    content_preview: str
    score: float


class DynamicTopicRagInsightDTO(BaseModel):
    topic_id: int | None = None
    topic_key: str
    topic_title: str
    question_type: str
    source_status: str
    retrieval_confidence: float = 0.0
    fallback_reason: str | None = None
    answer_issue: str
    explanation: str
    citations: list[DynamicRagCitationDTO] = Field(default_factory=list)
    recommended_materials: list[str] = Field(default_factory=list)
    study_steps: list[str] = Field(default_factory=list)
    next_practice: str


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
    answer: str = Field(..., min_length=1, max_length=10000)


class SubmitAnswerResponse(BaseModel):
    has_next_question: bool
    next_question: InterviewQuestionDTO | None = None
    current_question_index: int
    total_questions: int


class VoiceTranscriptionDTO(BaseModel):
    text: str
    language: str | None = None
    duration: float | None = None


class SessionListItemDTO(BaseModel):
    id: int
    session_id: str
    skill_id: str | None = None
    difficulty: str | None = None
    resume_id: int | None = None
    engine_type: str | None = None
    interview_mode: str | None = None
    total_questions: int | None = None
    current_question_index: int = 0
    status: str = "CREATED"
    evaluate_status: str | None = None
    evaluate_error: str | None = None
    overall_score: int | None = None
    report_ready: bool = False
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ProjectDimensionsDTO(BaseModel):
    authenticity: int = 0
    technical_depth: int = 0
    depth: int = 0
    expression: int = 0


class QuestionEvaluationDTO(BaseModel):
    question_index: int
    question: str
    category: str | None = None
    user_answer: str | None = None
    score: int = 0
    feedback: str | None = None
    question_type: str = "knowledge"
    covered_points: list[str] | None = None
    missed_points: list[str] | None = None
    errors: list[str] | None = None
    dimensions: ProjectDimensionsDTO | None = None
    interviewer_judgement: str | None = None
    answer_issues: list[str] | None = None
    answer_framework: list[str] | None = None
    answer_80: str | None = None
    answer_90: str | None = None
    next_practice_question: str | None = None


class ReferenceAnswerDTO(BaseModel):
    question_index: int
    question: str
    reference_answer: str | None = None
    key_points: list[str] | None = None


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


class RetryQuestionRequest(BaseModel):
    question_index: int = Field(..., ge=0)


class RetryAnswerComparisonDTO(BaseModel):
    session_id: str
    source_session_id: str
    source_question_index: int
    retry_question_index: int = 0
    source_question: str
    retry_question: str
    original_answer: str | None = None
    retry_answer: str | None = None
    original_score: int | None = None
    retry_score: int | None = None
    score_delta: int | None = None
    original_feedback: str | None = None
    retry_feedback: str | None = None
    improvement_summary: str
    next_action: str
    status: str


class HistoricalQuestion(BaseModel):
    question: str
    type: str | None = None
    category: str | None = None
    topic_summary: str | None = None
