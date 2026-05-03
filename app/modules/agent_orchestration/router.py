"""
Agent 编排路由
"""

import logging
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ai.llm_provider import llm_registry
from app.database import get_db
from app.modules.agent_orchestration import (
    AgentChain,
    AgentFactory,
    CostController,
    DecisionTree,
    DynamicContext,
)
from app.modules.agent_orchestration.models import AgentExecutionStatus
from app.modules.agent_orchestration.persistence_service import AgentPersistenceService
from app.modules.agent_orchestration.tool_registry import AgentToolRegistry
from app.modules.knowledge_base.rag_service import KnowledgeBaseRagService
from app.common.mcp import MCPService
from app.modules.agent_orchestration.agents.knowledge_builder_agent import (
    KnowledgeBuilderAgent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ==================== 请求/响应模型 ====================


class AgentChatRequest(BaseModel):
    """Agent 聊天请求"""

    message: str = Field(..., description="用户消息", min_length=1, max_length=10000)
    kb_ids: Optional[list[int]] = Field(default=None, description="知识库ID列表")
    max_step: int = Field(default=10, description="最大执行步数", ge=1, le=20)
    model: str = Field(default="qwen-plus", description="使用的模型")
    budget_limit: Optional[float] = Field(default=None, description="预算限制（美元）")


class AgentChatResponse(BaseModel):
    """Agent 聊天响应"""

    session_id: str = Field(..., description="会话ID")
    answer: str = Field(..., description="回答")
    execution_path: str = Field(..., description="执行路径")
    total_steps: int = Field(..., description="总步数")
    quality_score: Optional[float] = Field(default=None, description="质量分数")
    total_tokens: int = Field(..., description="总Token数")
    total_cost: float = Field(..., description="总成本")
    execution_time_ms: int = Field(..., description="执行时间（毫秒）")


class AgentExecutionDetail(BaseModel):
    """执行详情"""

    session_id: str
    user_input: str
    execution_path: Optional[str]
    final_answer: Optional[str]
    quality_score: Optional[float]
    total_steps: int
    total_tokens: int
    total_cost: float
    execution_time_ms: int
    status: str
    created_at: str


# ==================== 依赖注入 ====================


async def get_knowledge_service() -> KnowledgeBaseRagService:
    """获取知识库服务"""
    return KnowledgeBaseRagService()


async def get_tool_registry() -> AgentToolRegistry:
    """获取工具注册表"""
    registry = AgentToolRegistry()
    # TODO: 注册工具
    return registry


# ==================== 路由处理 ====================


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    knowledge_service: KnowledgeBaseRagService = Depends(get_knowledge_service),
    tool_registry: AgentToolRegistry = Depends(get_tool_registry),
):
    """
    Agent 聊天接口

    执行流程：
    1. 创建执行记录
    2. 决策树评估路径
    3. 创建责任链
    4. 执行责任链
    5. 保存结果
    """
    persistence = AgentPersistenceService(db)

    try:
        # 1. 创建执行记录
        execution = await persistence.create_execution(
            user_input=request.message,
            kb_ids=request.kb_ids,
        )

        # 2. 创建上下文
        context = DynamicContext(
            user_input=request.message,
            max_step=request.max_step,
        )
        context.kb_ids = request.kb_ids or []
        context.execution_id = execution.id
        context.session_id = execution.session_id
        context.set_value("model", request.model)

        # 3. 决策树评估
        decision_tree = DecisionTree(knowledge_service=knowledge_service)
        path = await decision_tree.decide(
            user_input=request.message,
            kb_ids=request.kb_ids or [],
        )

        logger.info(f"🎯 选择执行路径: {path.name}")

        # 更新执行路径
        await persistence.update_execution_path(
            execution_id=execution.id,
            path=path,
        )

        # 4. 创建成本控制器
        cost_controller = CostController(budget_limit=request.budget_limit)

        # 5. 创建责任链
        from app.common.ai.llm_adapter import LLMProviderAdapter
        chat_model = llm_registry.default
        llm_provider = LLMProviderAdapter(chat_model)
        factory = AgentFactory(
            llm_provider=llm_provider,
            knowledge_service=knowledge_service,
            cost_controller=cost_controller,
            tool_registry=tool_registry,
        )
        chain = factory.create_chain(path)

        # 6. 执行责任链
        logger.info("🚀 开始执行责任链")
        final_answer = await chain.execute(context)

        # 7. 保存执行步骤
        for i, record in enumerate(context.execution_history):
            await persistence.add_execution_step(
                execution_id=execution.id,
                step_number=i + 1,
                agent_name=record.get("agent", "unknown"),
                result_preview=record.get("result", "")[:500],
                tokens_used=0,  # TODO: 从 cost_controller 获取
                execution_time_ms=0,
            )

        # 8. 保存成本日志
        cost_summary = cost_controller.get_summary()
        for agent_name, usage in cost_summary.get("agent_breakdown", {}).items():
            await persistence.add_cost_log(
                execution_id=execution.id,
                agent_name=agent_name,
                model=request.model,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                estimated_cost=0.0,  # TODO: 计算成本
            )

        # 9. 更新执行成本
        await persistence.update_execution_cost(
            execution_id=execution.id,
            total_tokens=cost_summary["total_tokens"],
            total_cost=cost_summary.get("total_cost", 0.0),
        )

        # 10. 完成执行记录
        quality_result = context.get_value("quality_result", {})
        await persistence.complete_execution(
            execution_id=execution.id,
            context=context,
            final_answer=final_answer,
            quality_score=quality_result.get("score"),
            quality_passed=quality_result.get("passed"),
            status=AgentExecutionStatus.SUCCESS,
        )

        # 11. 返回响应
        return AgentChatResponse(
            session_id=execution.session_id,
            answer=final_answer,
            execution_path=path.name,
            total_steps=context.step_count,
            quality_score=quality_result.get("score"),
            total_tokens=cost_summary["total_tokens"],
            total_cost=cost_summary.get("total_cost", 0.0),
            execution_time_ms=context.execution_time_ms,
        )

    except Exception as e:
        logger.error(f"❌ Agent 执行失败: {e}", exc_info=True)

        # 更新执行状态为失败
        if context.execution_id:
            await persistence.complete_execution(
                execution_id=context.execution_id,
                context=context,
                final_answer="",
                status=AgentExecutionStatus.FAILED,
                error_message=str(e),
            )

        raise HTTPException(status_code=500, detail=f"Agent 执行失败: {str(e)}")


@router.get("/executions/{session_id}", response_model=AgentExecutionDetail)
async def get_execution(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取执行详情"""
    persistence = AgentPersistenceService(db)
    execution = await persistence.get_execution_by_session(session_id)

    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")

    return AgentExecutionDetail(
        session_id=execution.session_id,
        user_input=execution.user_input,
        execution_path=execution.execution_path.value if execution.execution_path else None,
        final_answer=execution.final_answer,
        quality_score=execution.quality_score,
        total_steps=execution.total_steps,
        total_tokens=execution.total_tokens,
        total_cost=execution.total_cost,
        execution_time_ms=execution.execution_time_ms,
        status=execution.status.value,
        created_at=execution.created_at.isoformat(),
    )


@router.get("/executions", response_model=list[AgentExecutionDetail])
async def list_executions(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出执行记录"""
    persistence = AgentPersistenceService(db)
    executions = await persistence.list_executions(limit=limit, offset=offset)

    return [
        AgentExecutionDetail(
            session_id=execution.session_id,
            user_input=execution.user_input,
            execution_path=execution.execution_path.value if execution.execution_path else None,
            final_answer=execution.final_answer,
            quality_score=execution.quality_score,
            total_steps=execution.total_steps,
            total_tokens=execution.total_tokens,
            total_cost=execution.total_cost,
            execution_time_ms=execution.execution_time_ms,
            status=execution.status.value,
            created_at=execution.created_at.isoformat(),
        )
        for execution in executions
    ]


# ==================== 智能知识库构建 ====================


class KnowledgeBuilderRequest(BaseModel):
    """智能知识库构建请求"""

    message: str = Field(
        ..., description="用户输入（如：帮我下载 Python 官方文档）", min_length=1
    )
    kb_id: Optional[int] = Field(default=None, description="目标知识库ID（可选）")


class KnowledgeBuilderResponse(BaseModel):
    """智能知识库构建响应"""

    success: bool = Field(..., description="是否成功")
    kb_id: int = Field(..., description="知识库ID")
    kb_name: str = Field(..., description="知识库名称")
    downloaded_files: int = Field(..., description="下载的文件数")
    chunks_count: int = Field(..., description="添加的知识片段数")
    message: str = Field(..., description="执行消息")
    intent: Dict = Field(..., description="识别的意图")


@router.post("/knowledge-builder", response_model=KnowledgeBuilderResponse)
async def build_knowledge_base(
    request: KnowledgeBuilderRequest,
    knowledge_service: KnowledgeBaseRagService = Depends(get_knowledge_service),
):
    """
    智能知识库构建接口

    功能：
    1. 用户输入提示词（如："帮我下载 Python 官方文档"）
    2. Agent 自动识别意图
    3. 调用 MCP 服务下载资料
    4. 自动添加到知识库

    示例：
    ```
    POST /api/agent/knowledge-builder
    {
        "message": "帮我下载 FastAPI 官方文档和教程",
        "kb_id": null  // 不指定则创建新知识库
    }
    ```
    """
    logger.info(f"🤖 智能知识库构建: {request.message}")

    try:
        # 初始化 MCP 服务
        from app.modules.knowledge_base.fetch_service import DocumentFetcher

        document_fetcher = DocumentFetcher()
        mcp_service = MCPService(document_fetcher=document_fetcher)

        # 创建 KnowledgeBuilderAgent
        from app.common.ai.llm_adapter import LLMProviderAdapter
        chat_model = llm_registry.default
        llm_provider = LLMProviderAdapter(chat_model)
        agent = KnowledgeBuilderAgent(
            llm_provider=llm_provider,
            mcp_service=mcp_service,
            knowledge_service=knowledge_service,
        )

        # 执行智能构建
        result = await agent.execute(
            user_input=request.message,
            kb_id=request.kb_id,
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=result.message)

        # 返回响应
        return KnowledgeBuilderResponse(
            success=True,
            kb_id=result.data["knowledge_base"]["kb_id"],
            kb_name=result.data["knowledge_base"]["kb_name"],
            downloaded_files=len(result.data["downloaded_files"]),
            chunks_count=result.data["knowledge_base"]["chunks_count"],
            message=result.message,
            intent=result.data["intent"],
        )

    except Exception as e:
        logger.error(f"❌ 智能知识库构建失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"构建失败: {str(e)}")
