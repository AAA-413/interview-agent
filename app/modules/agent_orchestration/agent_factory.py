"""
Agent 工厂：统一 Agent 创建入口

职责：
1. 创建各种类型的 Agent（Planning、Execution、Quality、Summary）
2. 管理 Agent 依赖注入
3. 提供 Agent 注册和查询
"""

import logging
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from app.common.ai.llm_provider import LLMProvider
    from app.modules.knowledge_base.rag_service import KnowledgeService

    from .agents.execution_agent import ExecutionAgent
    from .agents.planning_agent import PlanningAgent
    from .agents.quality_agent import QualityAgent
    from .agents.summary_agent import SummaryAgent
    from .cost_controller import CostController
    from .tool_registry import AgentToolRegistry

logger = logging.getLogger(__name__)


class AgentFactory:
    """Agent 工厂：统一 Agent 创建入口"""

    def __init__(
        self,
        llm_provider: "LLMProvider",
        knowledge_service: Optional["KnowledgeService"] = None,
        cost_controller: Optional["CostController"] = None,
        tool_registry: Optional["AgentToolRegistry"] = None,
    ):
        self.llm_provider = llm_provider
        self.knowledge_service = knowledge_service
        self.cost_controller = cost_controller
        self.tool_registry = tool_registry

        # Agent 缓存
        self._agent_cache: Dict[str, object] = {}

    def create_planning_agent(self) -> "PlanningAgent":
        """创建规划 Agent"""
        if "planning" in self._agent_cache:
            return self._agent_cache["planning"]

        from .agents.planning_agent import PlanningAgent

        agent = PlanningAgent(
            llm_provider=self.llm_provider,
            knowledge_service=self.knowledge_service,
        )
        self._agent_cache["planning"] = agent
        logger.info("✅ 创建 PlanningAgent")
        return agent

    def create_execution_agent(self, agent_type: str) -> "ExecutionAgent":
        """
        创建执行 Agent

        Args:
            agent_type: Agent 类型
                - knowledge_search: 知识检索
                - code_analysis: 代码分析
                - data_processing: 数据处理
                - design: 设计
                - question_answering: 问答

        Returns:
            ExecutionAgent 实例
        """
        cache_key = f"execution_{agent_type}"
        if cache_key in self._agent_cache:
            return self._agent_cache[cache_key]

        from .agents.execution_agent import ExecutionAgentFactory

        agent = ExecutionAgentFactory.create_agent(
            agent_type=agent_type,
            llm_provider=self.llm_provider,
            knowledge_service=self.knowledge_service,
        )
        self._agent_cache[cache_key] = agent
        logger.info(f"✅ 创建 ExecutionAgent: {agent_type}")
        return agent

    def create_quality_agent(self) -> "QualityAgent":
        """创建质检 Agent"""
        if "quality" in self._agent_cache:
            return self._agent_cache["quality"]

        from .agents.quality_agent import QualityAgent

        agent = QualityAgent(llm_provider=self.llm_provider)
        self._agent_cache["quality"] = agent
        logger.info("✅ 创建 QualityAgent")
        return agent

    def create_summary_agent(self) -> "SummaryAgent":
        """创建总结 Agent"""
        if "summary" in self._agent_cache:
            return self._agent_cache["summary"]

        from .agents.summary_agent import SummaryAgent

        agent = SummaryAgent(llm_provider=self.llm_provider)
        self._agent_cache["summary"] = agent
        logger.info("✅ 创建 SummaryAgent")
        return agent

    def clear_cache(self):
        """清空 Agent 缓存"""
        self._agent_cache.clear()
        logger.info("🗑️ 清空 Agent 缓存")
