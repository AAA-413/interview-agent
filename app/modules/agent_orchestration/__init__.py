"""
Agent 编排模块

提供智能 Agent 编排能力：
- 决策树：根据任务复杂度选择执行路径
- 责任链：串联多个 Agent 协同工作
- 工具注册：即插即用的工具系统
- 成本控制：Token 预算管理
- 核心 Agent：规划、执行、质检、总结
"""

from .agent_factory import AgentFactory
from .agents import (
    ExecutionAgent,
    ExecutionAgentFactory,
    PlanningAgent,
    QualityAgent,
    SummaryAgent,
)
from .base_agent import DynamicContext
from .cost_controller import CostController
from .decision_tree import DecisionTree, ExecutionPath
from .orchestrator import AgentOrchestrator
from .schemas import AgentMessage
from .tool_registry import AgentTool, AgentToolRegistry

__all__ = [
    "DynamicContext",
    "DecisionTree",
    "ExecutionPath",
    "AgentFactory",
    "AgentMessage",
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
