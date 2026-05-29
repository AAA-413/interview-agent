import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SessionStatus(str, enum.Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EVALUATED = "EVALUATED"
    PLANNING = "PLANNING"
    INTERVIEWING = "INTERVIEWING"
    ABANDONED = "ABANDONED"
    FAILED = "FAILED"


class InterviewEngineType(str, enum.Enum):
    STATIC = "STATIC"
    DYNAMIC = "DYNAMIC"


class InterviewMode(str, enum.Enum):
    STRICT = "STRICT"
    COACH = "COACH"


class InterviewQuestionType(str, enum.Enum):
    PROJECT = "PROJECT"
    KNOWLEDGE = "KNOWLEDGE"
    SYSTEM_DESIGN = "SYSTEM_DESIGN"


class TopicStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class TurnType(str, enum.Enum):
    MAIN = "MAIN"
    FOLLOW_UP = "FOLLOW_UP"
    COACH_RETRY = "COACH_RETRY"


class DecisionAction(str, enum.Enum):
    FOLLOW_UP = "FOLLOW_UP"
    COACH_RETRY = "COACH_RETRY"
    NEXT_TOPIC = "NEXT_TOPIC"
    END = "END"


class InterviewSessionEntity(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        Index("idx_interview_session_resume_created", "resume_id", "created_at"),
        Index("idx_interview_session_resume_status_created", "resume_id", "status", "created_at"),
        Index("idx_interview_session_skill_created", "skill_id", "created_at"),
        Index("idx_interview_session_user_mode_created", "user_id", "interview_mode", "created_at"),
        Index("idx_interview_session_engine_status_created", "engine_type", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    skill_id: Mapped[str] = mapped_column(String(64), default="java-backend")
    difficulty: Mapped[str] = mapped_column(String(16), default="mid")
    resume_id: Mapped[int | None] = mapped_column(BigInteger)
    total_questions: Mapped[int | None] = mapped_column(Integer)
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[SessionStatus] = mapped_column(Enum(SessionStatus), default=SessionStatus.CREATED)
    questions_json: Mapped[str | None] = mapped_column(Text)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    overall_feedback: Mapped[str | None] = mapped_column(Text)
    strengths_json: Mapped[str | None] = mapped_column(Text)
    improvements_json: Mapped[str | None] = mapped_column(Text)
    reference_answers_json: Mapped[str | None] = mapped_column(Text)
    evaluate_status: Mapped[str | None] = mapped_column(String(20))
    evaluate_error: Mapped[str | None] = mapped_column(String(500))
    llm_provider: Mapped[str] = mapped_column(String(50), default="dashscope")
    engine_type: Mapped[str] = mapped_column(String(20), default=InterviewEngineType.STATIC.value)
    interview_mode: Mapped[str | None] = mapped_column(String(20))
    target_role: Mapped[str | None] = mapped_column(String(120))
    target_company: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str | None] = mapped_column(String(40))
    jd_text: Mapped[str | None] = mapped_column(Text)
    current_topic_id: Mapped[int | None] = mapped_column(BigInteger)
    project_score: Mapped[int | None] = mapped_column(Integer)
    knowledge_score: Mapped[int | None] = mapped_column(Integer)
    system_design_score: Mapped[int | None] = mapped_column(Integer)
    plan_summary_json: Mapped[str | None] = mapped_column(Text)
    final_report_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    answers: Mapped[list["InterviewAnswerEntity"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    topics: Mapped[list["InterviewTopicEntity"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin", order_by="InterviewTopicEntity.topic_order"
    )
    turns: Mapped[list["InterviewTurnEntity"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin", order_by="InterviewTurnEntity.created_at"
    )
    operation_metrics: Mapped[list["InterviewOperationMetricEntity"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InterviewOperationMetricEntity.created_at",
    )


class InterviewAnswerEntity(Base):
    __tablename__ = "interview_answers"
    __table_args__ = (
        UniqueConstraint("session_id", "question_index", name="uk_interview_answer_session_question"),
        Index("idx_interview_answer_session_question", "session_id", "question_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("interview_sessions.id"), nullable=False)
    question_index: Mapped[int] = mapped_column(Integer)
    question: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(200))
    user_answer: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[str | None] = mapped_column(Text)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    key_points_json: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["InterviewSessionEntity"] = relationship(back_populates="answers")


class InterviewTopicEntity(Base):
    __tablename__ = "interview_topics"
    __table_args__ = (
        UniqueConstraint("session_id", "topic_order", name="uk_interview_topic_session_order"),
        Index("idx_interview_topic_session_order", "session_id", "topic_order"),
        Index("idx_interview_topic_user_created", "user_id", "created_at"),
        Index("idx_interview_topic_user_topic_created", "user_id", "topic_key", "created_at"),
        Index("idx_interview_topic_user_type_created", "user_id", "question_type", "created_at"),
        Index("idx_interview_topic_user_skill_created", "user_id", "skill_key", "created_at"),
        Index("idx_interview_topic_evidence_hash", "user_id", "evidence_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    resume_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_key: Mapped[str] = mapped_column(String(120), nullable=False)
    topic_title: Mapped[str] = mapped_column(String(200), nullable=False)
    skill_key: Mapped[str] = mapped_column(String(80), nullable=False)
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="mixed", nullable=False)
    evidence_snippet: Mapped[str | None] = mapped_column(Text)
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    main_question: Mapped[str] = mapped_column(Text, nullable=False)
    topic_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=TopicStatus.PENDING.value, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_score: Mapped[int | None] = mapped_column(Integer)
    final_score: Mapped[int | None] = mapped_column(Integer)
    followup_goals_json: Mapped[str | None] = mapped_column(Text)
    exit_criteria_json: Mapped[str | None] = mapped_column(Text)
    rubric_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    session: Mapped["InterviewSessionEntity"] = relationship(back_populates="topics")
    turns: Mapped[list["InterviewTurnEntity"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan", lazy="selectin", order_by="InterviewTurnEntity.turn_order"
    )


class InterviewTurnEntity(Base):
    __tablename__ = "interview_turns"
    __table_args__ = (
        UniqueConstraint("topic_id", "turn_order", name="uk_interview_turn_topic_order"),
        Index("idx_interview_turn_session_created", "session_id", "created_at"),
        Index("idx_interview_turn_topic_order", "topic_id", "turn_order"),
        Index("idx_interview_turn_user_created", "user_id", "created_at"),
        Index("idx_interview_turn_user_type_created", "user_id", "turn_type", "created_at"),
        Index("idx_interview_turn_decision_action", "user_id", "decision_action", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("interview_topics.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    turn_type: Mapped[str] = mapped_column(String(30), nullable=False)
    turn_order: Mapped[int] = mapped_column(Integer, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    ability_score: Mapped[int | None] = mapped_column(Integer)
    decision_action: Mapped[str | None] = mapped_column(String(30))
    feedback: Mapped[str | None] = mapped_column(Text)
    evaluation_json: Mapped[str | None] = mapped_column(Text)
    signals_json: Mapped[str | None] = mapped_column(Text)
    decision_json: Mapped[str | None] = mapped_column(Text)
    coach_hint_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    session: Mapped["InterviewSessionEntity"] = relationship(back_populates="turns")
    topic: Mapped["InterviewTopicEntity"] = relationship(back_populates="turns")


class InterviewOperationMetricEntity(Base):
    __tablename__ = "interview_operation_metrics"
    __table_args__ = (
        Index("idx_interview_operation_session_created", "session_id", "created_at"),
        Index("idx_interview_operation_user_type_created", "user_id", "operation_type", "created_at"),
        Index("idx_interview_operation_success_created", "success", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("interview_topics.id", ondelete="SET NULL"))
    turn_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("interview_turns.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_estimate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["InterviewSessionEntity"] = relationship(back_populates="operation_metrics")
