from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class KnowledgeGraphEntity(Base):
    __tablename__ = "kg_entities"
    __table_args__ = (
        UniqueConstraint("name", "entity_type", name="uq_kg_entity_name_type"),
        Index("idx_kg_entity_name", "name"),
        Index("idx_kg_entity_type", "entity_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    properties_json: Mapped[str | None] = mapped_column(Text)
    mention_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    subject_triples: Mapped[list["KnowledgeTriple"]] = relationship(
        foreign_keys="KnowledgeTriple.subject_id", back_populates="subject_entity"
    )
    object_triples: Mapped[list["KnowledgeTriple"]] = relationship(
        foreign_keys="KnowledgeTriple.object_id", back_populates="object_entity"
    )


class KnowledgeTriple(Base):
    __tablename__ = "kg_triples"
    __table_args__ = (
        UniqueConstraint("subject_id", "predicate", "object_id", name="uq_kg_triple_spo"),
        Index("idx_kg_triple_subject", "subject_id"),
        Index("idx_kg_triple_object", "object_id"),
        Index("idx_kg_triple_predicate", "predicate"),
        Index("idx_kg_triple_source_kb", "source_kb_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False
    )
    source_kb_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    source_chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_chunks.id", ondelete="SET NULL")
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    subject_entity: Mapped["KnowledgeGraphEntity"] = relationship(
        foreign_keys=[subject_id], back_populates="subject_triples"
    )
    object_entity: Mapped["KnowledgeGraphEntity"] = relationship(
        foreign_keys=[object_id], back_populates="object_triples"
    )
