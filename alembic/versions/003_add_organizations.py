"""add organizations and members

Revision ID: 003_add_organizations
Revises: a1b2c3d4e5f6
Create Date: 2026-05-22

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003_add_organizations"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

organization_role = sa.Enum("OWNER", "ADMIN", "STUDENT", name="organizationrole")


def upgrade() -> None:
    organization_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_organization_owner_created", "organizations", ["owner_id", "created_at"])

    op.create_table(
        "organization_members",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", organization_role, nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uk_organization_member_user"),
    )
    op.create_index("idx_organization_member_user", "organization_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_organization_member_user", table_name="organization_members")
    op.drop_table("organization_members")
    op.drop_index("idx_organization_owner_created", table_name="organizations")
    op.drop_table("organizations")
    organization_role.drop(op.get_bind(), checkfirst=True)
