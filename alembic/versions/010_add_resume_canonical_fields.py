"""add canonical resume fields to resumes and resume_evidence_refs_json to interview_topics

PR4：Resume Canonical Schema / Resume Evidence Pipeline。

- ``resumes`` 增加 5 列，保存**当前最新** canonical artifact（derived artifact，
  生命周期绑定 resume_text，与 resume_analyses 的评分历史不同，因此不放 profile_json）：
  canonical_profile_json / canonical_schema_version / canonical_source_hash /
  canonical_extract_error / canonical_extracted_at
- ``interview_topics`` 增加 ``resume_evidence_refs_json``，把「这场面试引用了哪几条
  简历事实」永久固定下来；即使 resume canonical 之后被重新抽取，旧 session 仍保持
  原来的 evidence provenance。

全部 nullable，旧数据无需 backfill。

Revision ID: 010_resume_canonical_fields
Revises: 009_topic_coverage_state
Create Date: 2026-09-29

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "010_resume_canonical_fields"
down_revision: Union[str, None] = "009_topic_coverage_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("resumes", sa.Column("canonical_profile_json", sa.Text(), nullable=True))
    op.add_column("resumes", sa.Column("canonical_schema_version", sa.String(64), nullable=True))
    op.add_column("resumes", sa.Column("canonical_source_hash", sa.String(64), nullable=True))
    op.add_column("resumes", sa.Column("canonical_extract_error", sa.String(500), nullable=True))
    op.add_column("resumes", sa.Column("canonical_extracted_at", sa.DateTime(), nullable=True))
    op.add_column("interview_topics", sa.Column("resume_evidence_refs_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_topics", "resume_evidence_refs_json")
    op.drop_column("resumes", "canonical_extracted_at")
    op.drop_column("resumes", "canonical_extract_error")
    op.drop_column("resumes", "canonical_source_hash")
    op.drop_column("resumes", "canonical_schema_version")
    op.drop_column("resumes", "canonical_profile_json")
