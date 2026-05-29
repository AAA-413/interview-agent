"""scope knowledge base file hash uniqueness by user

Revision ID: 008_scope_kb_hash_user
Revises: 007_dynamic_interview_metrics
Create Date: 2026-05-29

"""

from typing import Sequence, Union

from alembic import op

revision: str = "008_scope_kb_hash_user"
down_revision: Union[str, None] = "007_dynamic_interview_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_kb_file_hash")
    op.execute("ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_file_hash_key")
    op.create_index("idx_kb_user_file_hash", "knowledge_bases", ["user_id", "file_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_kb_user_file_hash", table_name="knowledge_bases")
    op.create_index("idx_kb_file_hash", "knowledge_bases", ["file_hash"], unique=True)
