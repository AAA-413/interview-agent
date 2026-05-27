import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class OrganizationRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    STUDENT = "STUDENT"


class OrganizationEntity(Base):
    __tablename__ = "organizations"
    __table_args__ = (Index("idx_organization_owner_created", "owner_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.now, onupdate=datetime.now, nullable=False
    )

    members: Mapped[list["OrganizationMemberEntity"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan", lazy="selectin"
    )


class OrganizationMemberEntity(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uk_organization_member_user"),
        Index("idx_organization_member_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[OrganizationRole] = mapped_column(Enum(OrganizationRole), default=OrganizationRole.STUDENT)
    note: Mapped[str | None] = mapped_column(String(500))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.now, nullable=False)

    organization: Mapped["OrganizationEntity"] = relationship(back_populates="members")
