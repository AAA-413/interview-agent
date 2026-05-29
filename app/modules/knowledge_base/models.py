import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.model import AsyncTaskStatus
from app.models.base import Base


class RagChatStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class KnowledgeBaseEntity(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("idx_kb_user_file_hash", "user_id", "file_hash", unique=True),
        Index("idx_kb_created_at", "created_at"),
        Index("idx_kb_index_status_created", "index_status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(200))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    storage_url: Mapped[str | None] = mapped_column(String(1000))
    source_text: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    index_status: Mapped[AsyncTaskStatus] = mapped_column(
        Enum(AsyncTaskStatus), default=AsyncTaskStatus.PENDING, nullable=False
    )
    index_error: Mapped[str | None] = mapped_column(String(500))
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["KnowledgeChunkEntity"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", lazy="selectin"
    )
    chats: Mapped[list["RagChatEntity"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan", lazy="selectin"
    )


class KnowledgeChunkEntity(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("idx_kb_chunk_kb_id", "knowledge_base_id"),
        Index("idx_kb_chunk_order", "knowledge_base_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_preview: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    embedding_json: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge_base: Mapped["KnowledgeBaseEntity"] = relationship(back_populates="chunks")


class RagChatEntity(Base):
    __tablename__ = "rag_chats"
    __table_args__ = (
        Index("idx_rag_chat_kb_created", "knowledge_base_id", "created_at"),
        Index("idx_rag_chat_session", "session_id"),
        Index("idx_rag_chat_user_session", "user_id", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    knowledge_base_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    references_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RagChatStatus] = mapped_column(Enum(RagChatStatus), default=RagChatStatus.PENDING, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge_base: Mapped["KnowledgeBaseEntity | None"] = relationship(back_populates="chats")
