"""
工具注册表：即插即用的工具系统
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class AgentTool:
    """Agent 工具定义"""

    name: str
    description: str
    parameters: Dict[str, Any]

    def to_schema(self) -> Dict[str, Any]:
        """转换为 LLM 工具 schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgentToolRegistry:
    """Agent 工具注册表"""

    def __init__(self):
        self.tools: Dict[str, AgentTool] = {}
        self.handlers: Dict[str, Callable] = {}

    def register(self, tool: AgentTool, handler: Callable):
        """
        注册工具和处理函数

        Args:
            tool: 工具定义
            handler: 处理函数
        """
        self.tools[tool.name] = tool
        self.handlers[tool.name] = handler
        logger.info(f"✅ 注册工具: {tool.name}")

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取所有工具的 schema（用于 LLM）"""
        return [tool.to_schema() for tool in self.tools.values()]

    async def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """
        执行工具

        Args:
            tool_name: 工具名称
            **kwargs: 工具参数

        Returns:
            工具执行结果
        """
        if tool_name not in self.handlers:
            raise ValueError(f"未知工具: {tool_name}")

        handler = self.handlers[tool_name]
        logger.info(f"🔧 执行工具: {tool_name}")

        try:
            result = await handler(**kwargs)
            logger.info(f"✅ 工具执行成功: {tool_name}")
            return result
        except Exception as e:
            logger.error(f"❌ 工具执行失败: {tool_name}, 错误: {e}")
            raise


# 预定义工具
BUILTIN_TOOLS = [
    AgentTool(
        name="knowledge_search",
        description="从知识库检索相关信息",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "kb_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "知识库ID列表",
                },
                "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
            },
            "required": ["query"],
        },
    ),
    AgentTool(
        name="task_create",
        description="创建新任务",
        parameters={
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务描述"},
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "依赖的任务ID",
                },
            },
            "required": ["subject", "description"],
        },
    ),
    AgentTool(
        name="task_update",
        description="更新任务状态",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "任务ID"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                    "description": "任务状态",
                },
            },
            "required": ["task_id", "status"],
        },
    ),
    AgentTool(
        name="code_execute",
        description="执行代码片段",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "要执行的代码"},
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "bash"],
                    "description": "编程语言",
                },
            },
            "required": ["code", "language"],
        },
    ),
]
