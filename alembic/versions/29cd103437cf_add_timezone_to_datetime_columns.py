"""add timezone to datetime columns

Revision ID: 29cd103437cf
Revises: 002_add_profile_json
Create Date: 2026-05-07 16:29:39.159415

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '29cd103437cf'
down_revision: Union[str, None] = '002_add_profile_json'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables and columns to convert from TIMESTAMP to TIMESTAMPTZ
TABLES_COLUMNS = [
    # knowledge_bases
    ("knowledge_bases", ["created_at", "updated_at", "last_indexed_at"]),
    # knowledge_chunks
    ("knowledge_chunks", ["created_at"]),
    # rag_chats
    ("rag_chats", ["created_at"]),
    # interview_sessions
    ("interview_sessions", ["created_at", "completed_at"]),
    # interview_answers
    ("interview_answers", ["answered_at"]),
    # agent_executions
    ("agent_executions", ["created_at", "updated_at"]),
    # agent_execution_steps
    ("agent_execution_steps", ["created_at"]),
    # agent_cost_logs
    ("agent_cost_logs", ["created_at"]),
    # agent_performance
    ("agent_performance", ["date", "created_at", "updated_at"]),
    # users
    ("users", ["created_at", "updated_at", "last_login"]),
]


def upgrade() -> None:
    for table, columns in TABLES_COLUMNS:
        for col in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMPTZ "
                f"USING {col} AT TIME ZONE 'UTC'"
            )


def downgrade() -> None:
    for table, columns in TABLES_COLUMNS:
        for col in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TIMESTAMP "
                f"USING {col} AT TIME ZONE 'UTC'"
            )
