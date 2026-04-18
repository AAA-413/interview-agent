"""
Agent 编排持久化服务
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent_orchestration.base_agent import DynamicContext
from app.modules.agent_orchestration.models import (
    AgentCostLogEntity,
    AgentExecutionEntity,
    AgentExecutionPath,
    AgentExecutionStatus,
    AgentExecutionStepEntity,
)


class AgentPersistenceService:
    """Agent 执行持久化服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_execution(
        self,
        user_input: str,
        user_id: Optional[int] = None,
        kb_ids: Optional[list[int]] = None,
    ) -> AgentExecutionEntity:
        """创建执行记录"""
        execution = AgentExecutionEntity(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            user_input=user_input,
            kb_ids=kb_ids,
            status=AgentExecutionStatus.PENDING,
        )
        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def update_execution_path(
        self,
        execution_id: int,
        path: AgentExecutionPath,
        task_plan: Optional[dict] = None,
    ) -> None:
        """更新执行路径"""
        stmt = select(AgentExecutionEntity).where(AgentExecutionEntity.id == execution_id)
        result = await self.db.execute(stmt)
        execution = result.scalar_one_or_none()

        if execution:
            execution.execution_path = path
            execution.task_plan = task_plan
            execution.status = AgentExecutionStatus.RUNNING
            await self.db.commit()

    async def add_execution_step(
        self,
        execution_id: int,
        step_number: int,
        agent_name: str,
        agent_type: Optional[str] = None,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None,
        result_preview: Optional[str] = None,
        tokens_used: int = 0,
        execution_time_ms: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> AgentExecutionStepEntity:
        """添加执行步骤"""
        step = AgentExecutionStepEntity(
            execution_id=execution_id,
            step_number=step_number,
            agent_name=agent_name,
            agent_type=agent_type,
            input_data=input_data,
            output_data=output_data,
            result_preview=result_preview,
            tokens_used=tokens_used,
            execution_time_ms=execution_time_ms,
            status=status,
            error_message=error_message,
        )
        self.db.add(step)
        await self.db.commit()
        await self.db.refresh(step)
        return step

    async def add_cost_log(
        self,
        execution_id: int,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost: float,
    ) -> AgentCostLogEntity:
        """添加成本日志"""
        cost_log = AgentCostLogEntity(
            execution_id=execution_id,
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=estimated_cost,
        )
        self.db.add(cost_log)
        await self.db.commit()
        await self.db.refresh(cost_log)
        return cost_log

    async def complete_execution(
        self,
        execution_id: int,
        context: DynamicContext,
        final_answer: str,
        quality_score: Optional[float] = None,
        quality_passed: Optional[bool] = None,
        status: AgentExecutionStatus = AgentExecutionStatus.SUCCESS,
        error_message: Optional[str] = None,
    ) -> None:
        """完成执行记录"""
        stmt = select(AgentExecutionEntity).where(AgentExecutionEntity.id == execution_id)
        result = await self.db.execute(stmt)
        execution = result.scalar_one_or_none()

        if execution:
            # 计算执行时间
            execution_time_ms = 0
            if context.start_time:
                execution_time_ms = int((datetime.now() - context.start_time).total_seconds() * 1000)

            # 更新执行记录
            execution.final_answer = final_answer
            execution.quality_score = quality_score
            execution.quality_passed = quality_passed
            execution.total_steps = context.step_count
            execution.retry_count = context.retry_count
            execution.execution_time_ms = execution_time_ms
            execution.status = status
            execution.error_message = error_message

            await self.db.commit()

    async def update_execution_cost(
        self,
        execution_id: int,
        total_tokens: int,
        total_cost: float,
    ) -> None:
        """更新执行成本"""
        stmt = select(AgentExecutionEntity).where(AgentExecutionEntity.id == execution_id)
        result = await self.db.execute(stmt)
        execution = result.scalar_one_or_none()

        if execution:
            execution.total_tokens = total_tokens
            execution.total_cost = total_cost
            await self.db.commit()

    async def get_execution(self, execution_id: int) -> Optional[AgentExecutionEntity]:
        """获取执行记录"""
        stmt = select(AgentExecutionEntity).where(AgentExecutionEntity.id == execution_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_execution_by_session(self, session_id: str) -> Optional[AgentExecutionEntity]:
        """根据 session_id 获取执行记录"""
        stmt = select(AgentExecutionEntity).where(AgentExecutionEntity.session_id == session_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_executions(
        self,
        user_id: Optional[int] = None,
        status: Optional[AgentExecutionStatus] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AgentExecutionEntity]:
        """列出执行记录"""
        stmt = select(AgentExecutionEntity)

        if user_id is not None:
            stmt = stmt.where(AgentExecutionEntity.user_id == user_id)
        if status is not None:
            stmt = stmt.where(AgentExecutionEntity.status == status)

        stmt = stmt.order_by(AgentExecutionEntity.created_at.desc()).limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())
