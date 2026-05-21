"""
Agent 编排模块的数据库模型
"""

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AgentExecutionStatus(str, enum.Enum):
    """执行状态"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"  # 部分完成


class AgentExecutionPath(str, enum.Enum):
    """执行路径"""

    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


class AgentExecutionEntity(Base):
    """Agent 执行记录表"""

    __tablename__ = "agent_executions"
    __table_args__ = (
        Index("idx_agent_exec_session_id", "session_id"),
        Index("idx_agent_exec_user_id", "user_id"),
        Index("idx_agent_exec_status", "status"),
        Index("idx_agent_exec_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)

    # 输入
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    user_intent: Mapped[str | None] = mapped_column(String(100))
    kb_ids: Mapped[list | None] = mapped_column(JSONB)  # 知识库ID列表

    # 执行路径
    execution_path: Mapped[AgentExecutionPath | None] = mapped_column(Enum(AgentExecutionPath))
    task_plan: Mapped[dict | None] = mapped_column(JSONB)  # 任务规划

    # 执行结果
    final_answer: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_passed: Mapped[bool | None] = mapped_column()

    # 元数据
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)

    # 状态
    status: Mapped[AgentExecutionStatus] = mapped_column(
        Enum(AgentExecutionStatus), default=AgentExecutionStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 关系
    steps: Mapped[list["AgentExecutionStepEntity"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", lazy="selectin"
    )
    cost_logs: Mapped[list["AgentCostLogEntity"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", lazy="selectin"
    )


class AgentExecutionStepEntity(Base):
    """Agent 执行步骤表"""

    __tablename__ = "agent_execution_steps"
    __table_args__ = (
        Index("idx_agent_step_execution_id", "execution_id"),
        Index("idx_agent_step_step_number", "execution_id", "step_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )

    # 步骤信息
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_type: Mapped[str | None] = mapped_column(String(100))

    # 输入输出
    input_data: Mapped[dict | None] = mapped_column(JSONB)
    output_data: Mapped[dict | None] = mapped_column(JSONB)
    result_preview: Mapped[str | None] = mapped_column(Text)

    # 元数据
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[str | None] = mapped_column(Text)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 关系
    execution: Mapped["AgentExecutionEntity"] = relationship(back_populates="steps")


class AgentCostLogEntity(Base):
    """Agent 成本日志表"""

    __tablename__ = "agent_cost_logs"
    __table_args__ = (
        Index("idx_agent_cost_execution_id", "execution_id"),
        Index("idx_agent_cost_agent_name", "agent_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )

    # 成本信息
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 关系
    execution: Mapped["AgentExecutionEntity"] = relationship(back_populates="cost_logs")


class AgentPerformanceEntity(Base):
    """Agent 性能统计表"""

    __tablename__ = "agent_performance"
    __table_args__ = (
        Index("idx_agent_perf_agent_type", "agent_type"),
        Index("idx_agent_perf_date", "date"),
        Index("idx_agent_perf_unique", "agent_type", "task_category", "date", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    task_category: Mapped[str | None] = mapped_column(String(50))

    # 性能指标
    total_executions: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_execution_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    avg_quality_score: Mapped[float] = mapped_column(Float, default=0.0)

    # 成本指标
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    avg_tokens_per_task: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)

    # 时间窗口
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
