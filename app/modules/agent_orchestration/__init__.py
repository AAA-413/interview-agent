"""
Agent 编排模块

提供智能 Agent 编排能力：
- 决策树：根据任务复杂度选择执行路径
- 责任链：串联多个 Agent 协同工作
- 工具注册：即插即用的工具系统
- 成本控制：Token 预算管理
- 核心 Agent：规划、执行、质检、总结
"""

from .base_agent import BaseAgent, AgentContext, DynamicContext
from .agent_chain import AgentChain
from .decision_tree import DecisionTree, ExecutionPath
from .agent_factory import AgentFactory
from .tool_registry import AgentToolRegistry, AgentTool
from .cost_controller import CostController
from .orchestrator import AgentOrchestrator
from .agents import (
    PlanningAgent,
    ExecutionAgent,
    ExecutionAgentFactory,
    QualityAgent,
    SummaryAgent,
)

__all__ = [
    "BaseAgent",
    "AgentContext",
    "DynamicContext",
    "AgentChain",
    "DecisionTree",
    "ExecutionPath",
    "AgentFactory",
    "AgentToolRegistry",
    "AgentTool",
    "CostController",
    "AgentOrchestrator",
    "PlanningAgent",
    "ExecutionAgent",
    "ExecutionAgentFactory",
    "QualityAgent",
    "SummaryAgent",
]
