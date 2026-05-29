from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.config import settings
from app.models.base import Base


def import_models() -> None:
    """Register ORM models with SQLAlchemy metadata for Alembic autogenerate."""
    from app.modules.agent_orchestration.models import (  # noqa: F401
        AgentCostLogEntity,
        AgentExecutionEntity,
        AgentExecutionStepEntity,
        AgentPerformanceEntity,
    )
    from app.modules.auth.models import UserEntity  # noqa: F401
    from app.modules.interview.models import (  # noqa: F401
        InterviewAnswerEntity,
        InterviewOperationMetricEntity,
        InterviewSessionEntity,
        InterviewTopicEntity,
        InterviewTurnEntity,
    )
    from app.modules.knowledge_base.models import KnowledgeBaseEntity, KnowledgeChunkEntity, RagChatEntity  # noqa: F401
    from app.modules.knowledge_graph.models import KnowledgeGraphEntity, KnowledgeTriple  # noqa: F401
    from app.modules.organization.models import OrganizationEntity, OrganizationMemberEntity  # noqa: F401
    from app.modules.resume.models import ResumeAnalysisEntity, ResumeEntity  # noqa: F401
    from app.modules.training.models import TrainingTaskProgressEntity  # noqa: F401


import_models()

config = context.config
config.set_main_option("sqlalchemy.url", settings.database.dsn)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
