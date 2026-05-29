"""scope resume file hash uniqueness by user

Revision ID: 005_scope_resume_hash_user
Revises: 004_add_training_task_progress
Create Date: 2026-05-28

"""

from typing import Sequence, Union

from alembic import op

revision: str = "005_scope_resume_hash_user"
down_revision: Union[str, None] = "004_add_training_task_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_resume_hash")
    op.execute("ALTER TABLE resumes DROP CONSTRAINT IF EXISTS resumes_file_hash_key")
    op.create_index("idx_resume_user_file_hash", "resumes", ["user_id", "file_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_resume_user_file_hash", table_name="resumes")
    op.create_index("idx_resume_hash", "resumes", ["file_hash"], unique=True)
