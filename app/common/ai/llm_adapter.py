"""
LLM Provider 适配器 - 将 LangChain ChatOpenAI 适配为 SmartDecisionTree 所需的接口
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class LLMProviderAdapter:
    """LLM Provider 适配器"""

    def __init__(self, langchain_model):
        """
        Args:
            langchain_model: LangChain ChatOpenAI 实例
        """
        self.langchain_model = langchain_model
        self.model_name = langchain_model.model_name

    async def chat(
        self, messages: List[Dict[str, str]], **kwargs
    ) -> Dict[str, Any]:
        """
        适配 chat 接口

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            **kwargs: 额外参数（temperature, max_tokens 等）

        Returns:
            {
                "content": "响应内容",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150
                }
            }
        """
        try:
            # 转换消息格式为 LangChain 格式
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

            lc_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                else:  # user
                    lc_messages.append(HumanMessage(content=content))

            # 调用 LangChain
            response = await self.langchain_model.ainvoke(lc_messages, **kwargs)

            # 提取 token 使用信息
            usage = {}
            if hasattr(response, "response_metadata"):
                token_usage = response.response_metadata.get("token_usage", {})
                usage = {
                    "prompt_tokens": token_usage.get("prompt_tokens", 0),
                    "completion_tokens": token_usage.get("completion_tokens", 0),
                    "total_tokens": token_usage.get("total_tokens", 0),
                }

            return {
                "content": response.content,
                "usage": usage,
            }

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise
