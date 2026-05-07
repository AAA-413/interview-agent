"""
Agent 上下文和结果定义
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DynamicContext:
    """动态上下文：在责任链中传递状态"""

    user_input: str
    max_step: int = 10
    step: int = 0
    retry_count: int = 0
    is_completed: bool = False

    # 执行历史
    execution_history: List[Dict[str, Any]] = field(default_factory=list)

    # 当前任务
    current_task: str = ""

    # 动态数据存储
    _data: Dict[str, Any] = field(default_factory=dict)

    # 知识库
    kb_ids: List[int] = field(default_factory=list)

    # 任务规划
    task_plan: Optional[Dict[str, Any]] = None

    # 质检报告
    quality_report: Optional[Dict[str, Any]] = None

    # 执行时间
    start_time: datetime = field(default_factory=datetime.now)
    execution_time_ms: int = 0

    # 持久化相关
    execution_id: Optional[int] = None
    session_id: Optional[str] = None
    step_count: int = 0

    def set_value(self, key: str, value: Any):
        """设置动态数据"""
        self._data[key] = value

    def get_value(self, key: str, default: Any = None) -> Any:
        """获取动态数据"""
        return self._data.get(key, default)

    def add_execution_result(self, result: str):
        """添加执行结果到历史"""
        self.execution_history.append(result)

    def add_tool_result(self, tool_id: str, result: Any):
        """添加工具调用结果"""
        self.set_value(f"tool_result_{tool_id}", result)

    def calculate_execution_time(self):
        """计算执行时间"""
        self.execution_time_ms = int((datetime.now() - self.start_time).total_seconds() * 1000)

    def get_final_result(self) -> "Result":
        """获取最终结果"""
        self.calculate_execution_time()
        return Result(
            status="success" if self.is_completed else "partial",
            summary=self.execution_history[-1] if self.execution_history else "",
            steps=self.step,
            retry_count=self.retry_count,
            execution_time_ms=self.execution_time_ms,
        )


@dataclass
class Result:
    """执行结果"""

    status: str  # success/partial/failed
    summary: str
    steps: int = 0
    retry_count: int = 0
    execution_time_ms: int = 0
    artifacts: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    def dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "steps": self.steps,
            "retry_count": self.retry_count,
            "execution_time_ms": self.execution_time_ms,
            "artifacts": self.artifacts,
            "next_steps": self.next_steps,
        }


@dataclass
class AgentResult:
    """Agent 执行结果（用于新的 Agent 系统）"""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: Optional[str] = None

    def dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "message": self.message,
            "error": self.error,
        }
