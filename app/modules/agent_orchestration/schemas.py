"""Agent 编排模块 - 统一消息协议"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    """Agent 间统一消息协议

    所有 ExecutionAgent 的 execute() 方法必须返回此类型，
    消除各 Agent 返回结构不一致的问题。
    """

    task_id: str
    agent_type: str
    status: str  # "success" | "failed"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        frozen = False
