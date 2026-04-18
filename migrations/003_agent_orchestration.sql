"""
创建 Agent 编排相关表

Revision ID: 003_agent_orchestration
Revises: 002_knowledge_base
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def upgrade():
    # 创建 agent_executions 表
    op.create_table(
        'agent_executions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(64), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('user_input', sa.Text(), nullable=False),
        sa.Column('user_intent', sa.String(100), nullable=True),
        sa.Column('kb_ids', JSONB, nullable=True),
        sa.Column('execution_path', sa.Enum('simple', 'standard', 'complex', name='agentexecutionpath'), nullable=True),
        sa.Column('task_plan', JSONB, nullable=True),
        sa.Column('final_answer', sa.Text(), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('quality_passed', sa.Boolean(), nullable=True),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('execution_time_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.Enum('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL', name='agentexecutionstatus'), nullable=False, server_default='PENDING'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 创建索引
    op.create_index('idx_agent_exec_session_id', 'agent_executions', ['session_id'], unique=True)
    op.create_index('idx_agent_exec_user_id', 'agent_executions', ['user_id'])
    op.create_index('idx_agent_exec_status', 'agent_executions', ['status'])
    op.create_index('idx_agent_exec_created_at', 'agent_executions', ['created_at'])

    # 创建 agent_execution_steps 表
    op.create_table(
        'agent_execution_steps',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('execution_id', sa.BigInteger(), nullable=False),
        sa.Column('step_number', sa.Integer(), nullable=False),
        sa.Column('agent_name', sa.String(100), nullable=False),
        sa.Column('agent_type', sa.String(100), nullable=True),
        sa.Column('input_data', JSONB, nullable=True),
        sa.Column('output_data', JSONB, nullable=True),
        sa.Column('result_preview', sa.Text(), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('execution_time_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['execution_id'], ['agent_executions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 创建索引
    op.create_index('idx_agent_step_execution_id', 'agent_execution_steps', ['execution_id'])
    op.create_index('idx_agent_step_step_number', 'agent_execution_steps', ['execution_id', 'step_number'])

    # 创建 agent_cost_logs 表
    op.create_table(
        'agent_cost_logs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('execution_id', sa.BigInteger(), nullable=False),
        sa.Column('agent_name', sa.String(100), nullable=False),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('estimated_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['execution_id'], ['agent_executions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 创建索引
    op.create_index('idx_agent_cost_execution_id', 'agent_cost_logs', ['execution_id'])
    op.create_index('idx_agent_cost_agent_name', 'agent_cost_logs', ['agent_name'])

    # 创建 agent_performance 表
    op.create_table(
        'agent_performance',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('agent_type', sa.String(50), nullable=False),
        sa.Column('task_category', sa.String(50), nullable=True),
        sa.Column('total_executions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_execution_time_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_quality_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_tokens_per_task', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_cost', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # 创建索引
    op.create_index('idx_agent_perf_agent_type', 'agent_performance', ['agent_type'])
    op.create_index('idx_agent_perf_date', 'agent_performance', ['date'])
    op.create_index('idx_agent_perf_unique', 'agent_performance', ['agent_type', 'task_category', 'date'], unique=True)


def downgrade():
    op.drop_index('idx_agent_perf_unique', table_name='agent_performance')
    op.drop_index('idx_agent_perf_date', table_name='agent_performance')
    op.drop_index('idx_agent_perf_agent_type', table_name='agent_performance')
    op.drop_table('agent_performance')

    op.drop_index('idx_agent_cost_agent_name', table_name='agent_cost_logs')
    op.drop_index('idx_agent_cost_execution_id', table_name='agent_cost_logs')
    op.drop_table('agent_cost_logs')

    op.drop_index('idx_agent_step_step_number', table_name='agent_execution_steps')
    op.drop_index('idx_agent_step_execution_id', table_name='agent_execution_steps')
    op.drop_table('agent_execution_steps')

    op.drop_index('idx_agent_exec_created_at', table_name='agent_executions')
    op.drop_index('idx_agent_exec_status', table_name='agent_executions')
    op.drop_index('idx_agent_exec_user_id', table_name='agent_executions')
    op.drop_index('idx_agent_exec_session_id', table_name='agent_executions')
    op.drop_table('agent_executions')

    op.execute('DROP TYPE agentexecutionstatus')
    op.execute('DROP TYPE agentexecutionpath')
