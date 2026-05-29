"""add dynamic interview mvp tables

Revision ID: 006_dynamic_interview_mvp
Revises: 005_scope_resume_hash_user
Create Date: 2026-05-28

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "006_dynamic_interview_mvp"
down_revision: Union[str, None] = "005_scope_resume_hash_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for status in ("PLANNING", "INTERVIEWING", "ABANDONED", "FAILED"):
        op.execute(f"ALTER TYPE sessionstatus ADD VALUE IF NOT EXISTS '{status}'")

    op.add_column("interview_sessions", sa.Column("engine_type", sa.String(length=20), nullable=True))
    op.add_column("interview_sessions", sa.Column("interview_mode", sa.String(length=20), nullable=True))
    op.add_column("interview_sessions", sa.Column("target_role", sa.String(length=120), nullable=True))
    op.add_column("interview_sessions", sa.Column("target_company", sa.String(length=120), nullable=True))
    op.add_column("interview_sessions", sa.Column("level", sa.String(length=40), nullable=True))
    op.add_column("interview_sessions", sa.Column("jd_text", sa.Text(), nullable=True))
    op.add_column("interview_sessions", sa.Column("current_topic_id", sa.BigInteger(), nullable=True))
    op.add_column("interview_sessions", sa.Column("project_score", sa.Integer(), nullable=True))
    op.add_column("interview_sessions", sa.Column("knowledge_score", sa.Integer(), nullable=True))
    op.add_column("interview_sessions", sa.Column("system_design_score", sa.Integer(), nullable=True))
    op.add_column("interview_sessions", sa.Column("plan_summary_json", sa.Text(), nullable=True))
    op.add_column("interview_sessions", sa.Column("final_report_json", sa.Text(), nullable=True))
    op.execute("UPDATE interview_sessions SET engine_type = 'STATIC' WHERE engine_type IS NULL")
    op.alter_column("interview_sessions", "engine_type", nullable=False)
    op.create_index(
        "idx_interview_session_user_mode_created",
        "interview_sessions",
        ["user_id", "interview_mode", "created_at"],
    )
    op.create_index(
        "idx_interview_session_engine_status_created",
        "interview_sessions",
        ["engine_type", "status", "created_at"],
    )

    op.create_table(
        "interview_topics",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("resume_id", sa.BigInteger(), nullable=True),
        sa.Column("topic_key", sa.String(length=120), nullable=False),
        sa.Column("topic_title", sa.String(length=200), nullable=False),
        sa.Column("skill_key", sa.String(length=80), nullable=False),
        sa.Column("question_type", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("evidence_snippet", sa.Text(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("main_question", sa.Text(), nullable=False),
        sa.Column("topic_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("best_score", sa.Integer(), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("followup_goals_json", sa.Text(), nullable=True),
        sa.Column("exit_criteria_json", sa.Text(), nullable=True),
        sa.Column("rubric_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "topic_order", name="uk_interview_topic_session_order"),
    )
    op.create_index("idx_interview_topic_session_order", "interview_topics", ["session_id", "topic_order"])
    op.create_index("idx_interview_topic_user_created", "interview_topics", ["user_id", "created_at"])
    op.create_index("idx_interview_topic_user_topic_created", "interview_topics", ["user_id", "topic_key", "created_at"])
    op.create_index("idx_interview_topic_user_type_created", "interview_topics", ["user_id", "question_type", "created_at"])
    op.create_index("idx_interview_topic_user_skill_created", "interview_topics", ["user_id", "skill_key", "created_at"])
    op.create_index("idx_interview_topic_evidence_hash", "interview_topics", ["user_id", "evidence_hash"])

    op.create_table(
        "interview_turns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("turn_type", sa.String(length=30), nullable=False),
        sa.Column("turn_order", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("ability_score", sa.Integer(), nullable=True),
        sa.Column("decision_action", sa.String(length=30), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("evaluation_json", sa.Text(), nullable=True),
        sa.Column("signals_json", sa.Text(), nullable=True),
        sa.Column("decision_json", sa.Text(), nullable=True),
        sa.Column("coach_hint_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["interview_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["interview_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", "turn_order", name="uk_interview_turn_topic_order"),
    )
    op.create_index("idx_interview_turn_session_created", "interview_turns", ["session_id", "created_at"])
    op.create_index("idx_interview_turn_topic_order", "interview_turns", ["topic_id", "turn_order"])
    op.create_index("idx_interview_turn_user_created", "interview_turns", ["user_id", "created_at"])
    op.create_index("idx_interview_turn_user_type_created", "interview_turns", ["user_id", "turn_type", "created_at"])
    op.create_index("idx_interview_turn_decision_action", "interview_turns", ["user_id", "decision_action", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_interview_turn_decision_action", table_name="interview_turns")
    op.drop_index("idx_interview_turn_user_type_created", table_name="interview_turns")
    op.drop_index("idx_interview_turn_user_created", table_name="interview_turns")
    op.drop_index("idx_interview_turn_topic_order", table_name="interview_turns")
    op.drop_index("idx_interview_turn_session_created", table_name="interview_turns")
    op.drop_table("interview_turns")

    op.drop_index("idx_interview_topic_evidence_hash", table_name="interview_topics")
    op.drop_index("idx_interview_topic_user_skill_created", table_name="interview_topics")
    op.drop_index("idx_interview_topic_user_type_created", table_name="interview_topics")
    op.drop_index("idx_interview_topic_user_topic_created", table_name="interview_topics")
    op.drop_index("idx_interview_topic_user_created", table_name="interview_topics")
    op.drop_index("idx_interview_topic_session_order", table_name="interview_topics")
    op.drop_table("interview_topics")

    op.drop_index("idx_interview_session_engine_status_created", table_name="interview_sessions")
    op.drop_index("idx_interview_session_user_mode_created", table_name="interview_sessions")
    op.drop_column("interview_sessions", "final_report_json")
    op.drop_column("interview_sessions", "plan_summary_json")
    op.drop_column("interview_sessions", "system_design_score")
    op.drop_column("interview_sessions", "knowledge_score")
    op.drop_column("interview_sessions", "project_score")
    op.drop_column("interview_sessions", "current_topic_id")
    op.drop_column("interview_sessions", "jd_text")
    op.drop_column("interview_sessions", "level")
    op.drop_column("interview_sessions", "target_company")
    op.drop_column("interview_sessions", "target_role")
    op.drop_column("interview_sessions", "interview_mode")
    op.drop_column("interview_sessions", "engine_type")
