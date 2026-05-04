"""添加 profile_json 列支持简历结构化画像提取

Revision ID: 002_add_profile_json
Revises: 001_add_user_id
Create Date: 2026-05-04

"""
from alembic import op
import sqlalchemy as sa

revision = "002_add_profile_json"
down_revision = "001_add_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resume_analyses", sa.Column("profile_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resume_analyses", "profile_json")
