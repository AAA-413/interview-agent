"""add dynamic interview operation metrics

Revision ID: 007_dynamic_interview_metrics
Revises: 006_dynamic_interview_mvp
Create Date: 2026-05-29

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "007_dynamic_interview_metrics"
down_revision: Union[str, None] = "006_dynamic_interview_mvp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_operation_metrics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=True),
        sa.Column("turn_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_estimate", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["interview_topics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["turn_id"], ["interview_turns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_interview_operation_session_created",
        "interview_operation_metrics",
        ["session_id", "created_at"],
    )
    op.create_index(
        "idx_interview_operation_user_type_created",
        "interview_operation_metrics",
        ["user_id", "operation_type", "created_at"],
    )
    op.create_index(
        "idx_interview_operation_success_created",
        "interview_operation_metrics",
        ["success", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_interview_operation_success_created", table_name="interview_operation_metrics")
    op.drop_index("idx_interview_operation_user_type_created", table_name="interview_operation_metrics")
    op.drop_index("idx_interview_operation_session_created", table_name="interview_operation_metrics")
    op.drop_table("interview_operation_metrics")
