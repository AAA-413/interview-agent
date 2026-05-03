from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.model import AsyncTaskStatus
from app.models.base import Base


class ResumeEntity(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        Index("idx_resume_hash", "file_hash", unique=True),
        Index("idx_resume_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(200))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    storage_url: Mapped[str | None] = mapped_column(String(1000))
    resume_text: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    analyze_status: Mapped[AsyncTaskStatus] = mapped_column(
        Enum(AsyncTaskStatus), default=AsyncTaskStatus.PENDING, nullable=False
    )
    analyze_error: Mapped[str | None] = mapped_column(String(500))

    analyses: Mapped[list["ResumeAnalysisEntity"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", lazy="selectin"
    )

    def increment_access_count(self) -> None:
        self.access_count += 1
        self.last_accessed_at = datetime.now()


class ResumeAnalysisEntity(Base):
    __tablename__ = "resume_analyses"
    __table_args__ = (
        Index("idx_analysis_resume_id", "resume_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    resume_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    overall_score: Mapped[int | None] = mapped_column(Integer)
    content_score: Mapped[int | None] = mapped_column(Integer)
    structure_score: Mapped[int | None] = mapped_column(Integer)
    skill_match_score: Mapped[int | None] = mapped_column(Integer)
    expression_score: Mapped[int | None] = mapped_column(Integer)
    project_score: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    strengths_json: Mapped[str | None] = mapped_column(Text)
    suggestions_json: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    resume: Mapped["ResumeEntity"] = relationship(back_populates="analyses")
