import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrainingTaskStatus(str, enum.Enum):
    TODO = "TODO"
    COMPLETED = "COMPLETED"


class TrainingTaskProgressEntity(Base):
    __tablename__ = "training_task_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "task_id", name="uk_training_task_progress_user_task"),
        Index("idx_training_task_progress_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    task_type: Mapped[str | None] = mapped_column(String(60))
    source_session_id: Mapped[str | None] = mapped_column(String(36))
    question_index: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[TrainingTaskStatus] = mapped_column(
        Enum(TrainingTaskStatus), default=TrainingTaskStatus.TODO, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
