import enum

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SessionStatus(str, enum.Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EVALUATED = "EVALUATED"


class InterviewSessionEntity(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        Index("idx_interview_session_resume_created", "resume_id", "created_at"),
        Index("idx_interview_session_resume_status_created", "resume_id", "status", "created_at"),
        Index("idx_interview_session_skill_created", "skill_id", "created_at"),
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
    created_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))

    answers: Mapped[list["InterviewAnswerEntity"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
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
