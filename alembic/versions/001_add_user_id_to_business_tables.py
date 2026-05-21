"""添加 user_id 列实现用户级数据隔离

Revision ID: 001_add_user_id
Revises:
Create Date: 2026-05-03

"""

import sqlalchemy as sa

from alembic import op

revision = "001_add_user_id"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # resumes 表
    op.add_column("resumes", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE resumes SET user_id = 1 WHERE user_id IS NULL")
    op.alter_column("resumes", "user_id", nullable=False)
    op.create_foreign_key("resumes_user_id_fkey", "resumes", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("idx_resumes_user_id", "resumes", ["user_id"])

    # interview_sessions 表
    op.add_column("interview_sessions", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE interview_sessions SET user_id = 1 WHERE user_id IS NULL")
    op.alter_column("interview_sessions", "user_id", nullable=False)
    op.create_foreign_key(
        "interview_sessions_user_id_fkey", "interview_sessions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("idx_interview_sessions_user_id", "interview_sessions", ["user_id"])

    # knowledge_bases 表
    op.add_column("knowledge_bases", sa.Column("user_id", sa.BigInteger(), nullable=True))
    op.execute("UPDATE knowledge_bases SET user_id = 1 WHERE user_id IS NULL")
    op.alter_column("knowledge_bases", "user_id", nullable=False)
    op.create_foreign_key(
        "knowledge_bases_user_id_fkey", "knowledge_bases", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("idx_knowledge_bases_user_id", "knowledge_bases", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_knowledge_bases_user_id", table_name="knowledge_bases")
    op.drop_constraint("knowledge_bases_user_id_fkey", "knowledge_bases", type_="foreignkey")
    op.drop_column("knowledge_bases", "user_id")

    op.drop_index("idx_interview_sessions_user_id", table_name="interview_sessions")
    op.drop_constraint("interview_sessions_user_id_fkey", "interview_sessions", type_="foreignkey")
    op.drop_column("interview_sessions", "user_id")

    op.drop_index("idx_resumes_user_id", table_name="resumes")
    op.drop_constraint("resumes_user_id_fkey", "resumes", type_="foreignkey")
    op.drop_column("resumes", "user_id")
