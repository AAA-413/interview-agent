"""
LLM Provider 类型定义
"""

from typing import Any, Dict, List, Protocol


class LLMProvider(Protocol):
    """LLM Provider 协议"""

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        调用 LLM 进行对话

        Args:
            messages: 消息列表，每个消息包含 role 和 content
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            响应字典，包含：
            - content: 生成的内容
            - usage: Token 使用情况
        """
        ...
