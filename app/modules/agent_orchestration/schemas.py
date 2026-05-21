"""Agent 编排模块 - 统一消息协议"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AgentMessage(BaseModel):
    """Agent 间统一消息协议

    所有 ExecutionAgent 的 execute() 方法必须返回此类型，
    消除各 Agent 返回结构不一致的问题。
    """

    model_config = ConfigDict(frozen=False)

    task_id: str
    agent_type: str
    status: str  # "success" | "failed"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
