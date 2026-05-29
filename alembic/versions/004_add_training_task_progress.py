"""add training task progress

Revision ID: 004_add_training_task_progress
Revises: 003_add_organizations
Create Date: 2026-05-28

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "004_add_training_task_progress"
down_revision: Union[str, None] = "003_add_organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

training_task_status = sa.Enum("TODO", "COMPLETED", name="trainingtaskstatus")


def upgrade() -> None:
    training_task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "training_task_progress",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("task_id", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("task_type", sa.String(length=60), nullable=True),
        sa.Column("source_session_id", sa.String(length=36), nullable=True),
        sa.Column("question_index", sa.Integer(), nullable=True),
        sa.Column("status", training_task_status, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "task_id", name="uk_training_task_progress_user_task"),
    )
    op.create_index(
        "idx_training_task_progress_user_updated",
        "training_task_progress",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_training_task_progress_user_updated", table_name="training_task_progress")
    op.drop_table("training_task_progress")
    training_task_status.drop(op.get_bind(), checkfirst=True)
