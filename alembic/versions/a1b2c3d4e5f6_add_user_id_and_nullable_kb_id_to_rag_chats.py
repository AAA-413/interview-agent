"""add user_id and nullable kb_id to rag_chats

Revision ID: a1b2c3d4e5f6
Revises: 29cd103437cf
Create Date: 2026-05-10 11:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '29cd103437cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. knowledge_base_id 改为可空
    op.alter_column('rag_chats', 'knowledge_base_id', nullable=True)

    # 2. 新增 user_id 列
    op.add_column('rag_chats', sa.Column('user_id', sa.BigInteger(), nullable=True))

    # 3. 新增索引
    op.create_index('idx_rag_chat_user_session', 'rag_chats', ['user_id', 'session_id'])


def downgrade() -> None:
    op.drop_index('idx_rag_chat_user_session', table_name='rag_chats')
    op.drop_column('rag_chats', 'user_id')
    op.alter_column('rag_chats', 'knowledge_base_id', nullable=False)
