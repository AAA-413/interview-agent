"""add coverage_state_json to interview_topics

PR3：Topic Coverage / TopicState / Adaptive Interview。

只新增一列 ``interview_topics.coverage_state_json``（NULL 表示老 topic，
读取时按 initial_state(question_type) 处理，不需要 backfill），不建新表。

Revision ID: 009_topic_coverage_state
Revises: 008_scope_kb_hash_user
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "009_topic_coverage_state"
down_revision: Union[str, None] = "008_scope_kb_hash_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interview_topics", sa.Column("coverage_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_topics", "coverage_state_json")
