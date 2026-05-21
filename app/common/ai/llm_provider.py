import asyncio
import logging
import time
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import APITimeoutError, RateLimitError

from app.common.exception import LLMRateLimitException, LLMTimeoutException
from app.config import settings

logger = logging.getLogger(__name__)

# 全局信号量：限制 LLM 并发调用数，防止触发 provider 限流
_LLM_SEMAPHORE = asyncio.Semaphore(10)


class MonitoredChatModel:
    """包装 ChatOpenAI，添加监控日志和异常处理（避免 Pydantic v2 属性限制）"""

    def __init__(self, model: ChatOpenAI, provider: str):
        self._model = model
        self._provider = provider

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    async def ainvoke(self, messages, **kwargs):
        start = time.time()
        try:
            async with _LLM_SEMAPHORE:
                result = await self._model.ainvoke(messages, **kwargs)
            duration = time.time() - start

            if hasattr(result, "response_metadata"):
                usage = result.response_metadata.get("token_usage", {})
                logger.info(
                    "LLM调用成功: provider=%s, model=%s, duration=%.2fs, tokens=%s",
                    self._provider,
                    self._model.model_name,
                    duration,
                    usage,
                )
            else:
                logger.info(
                    "LLM调用成功: provider=%s, model=%s, duration=%.2fs",
                    self._provider,
                    self._model.model_name,
                    duration,
                )
            return result
        except APITimeoutError as e:
            duration = time.time() - start
            logger.error(
                "LLM调用超时: provider=%s, model=%s, duration=%.2fs, error=%s",
                self._provider,
                self._model.model_name,
                duration,
                str(e),
            )
            raise LLMTimeoutException(f"AI 服务响应超时（{duration:.1f}秒），请稍后重试")
        except RateLimitError as e:
            duration = time.time() - start
            logger.error(
                "LLM调用频率限制: provider=%s, model=%s, duration=%.2fs, error=%s",
                self._provider,
                self._model.model_name,
                duration,
                str(e),
            )
            raise LLMRateLimitException("AI 服务调用频繁，请稍后再试（约 1 分钟）")
        except Exception as e:
            duration = time.time() - start
            logger.error(
                "LLM调用失败: provider=%s, model=%s, duration=%.2fs, error=%s",
                self._provider,
                self._model.model_name,
                duration,
                str(e),
            )
            raise

    async def agenerate(self, messages, **kwargs):
        start = time.time()
        try:
            async with _LLM_SEMAPHORE:
                result = await self._model.agenerate(messages, **kwargs)
            duration = time.time() - start
            logger.info(
                "LLM agenerate 成功: provider=%s, model=%s, duration=%.2fs",
                self._provider,
                self._model.model_name,
                duration,
            )
            return result
        except APITimeoutError:
            duration = time.time() - start
            raise LLMTimeoutException(f"AI 服务响应超时（{duration:.1f}秒），请稍后重试")
        except RateLimitError:
            duration = time.time() - start
            raise LLMRateLimitException("AI 服务调用频繁，请稍后再试（约 1 分钟）")
        except Exception:
            duration = time.time() - start
            logger.error(
                "LLM agenerate 失败: provider=%s, model=%s, duration=%.2fs",
                self._provider,
                self._model.model_name,
                duration,
            )
            raise

    async def astream(self, messages, **kwargs):
        """流式调用，带并发限制"""
        async with _LLM_SEMAPHORE:
            async for chunk in self._model.astream(messages, **kwargs):
                yield chunk

    def bind(self, **kwargs):
        return self._model.bind(**kwargs)

    def with_structured_output(self, schema, **kwargs):
        return self._model.with_structured_output(schema, **kwargs)

    @property
    def model_name(self):
        return self._model.model_name


class LangChainLLMAdapter:
    """适配器：将 LangChain ChatOpenAI 适配为 LLMProvider 协议"""

    def __init__(self, chat_model):
        self.llm = chat_model

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """实现 LLMProvider 协议的 chat 方法"""
        lc_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                lc_messages.append(HumanMessage(content=content))

        # 调用 LangChain
        response = await self.llm.ainvoke(lc_messages)

        # 转换返回格式
        result = {"content": response.content, "usage": {}}

        if hasattr(response, "response_metadata"):
            result["usage"] = response.response_metadata.get("token_usage", {})

        return result


class LlmProviderRegistry:
    def __init__(self):
        self._providers: dict[str, ChatOpenAI] = {}
        self._wrapped: dict[str, MonitoredChatModel] = {}
        self._init_default_providers()

    def _init_default_providers(self) -> None:
        ai = settings.ai
        self._providers["dashscope"] = ChatOpenAI(
            base_url=ai.base_url,
            api_key=ai.bailian_api_key,
            model=ai.model,
            temperature=ai.temperature,
            max_tokens=4096,
            request_timeout=300,
            max_retries=2,
        )
        logger.info("LLM Provider 初始化: model=%s, base_url=%s, timeout=300s, max_retries=2", ai.model, ai.base_url)

    def get_chat_model(self, provider: str | None = None) -> MonitoredChatModel:
        key = provider or "dashscope"
        if key not in self._providers:
            raise ValueError(f"未找到 LLM Provider: {key}")
        if key not in self._wrapped:
            self._wrapped[key] = MonitoredChatModel(self._providers[key], key)
        return self._wrapped[key]

    def register(self, name: str, chat_model: ChatOpenAI) -> None:
        self._providers[name] = chat_model

    @property
    def default(self) -> MonitoredChatModel:
        return self.get_chat_model("dashscope")

    def get_adapter(self, provider: str | None = None) -> LangChainLLMAdapter:
        """获取适配器实例，用于 Agent"""
        chat_model = self.get_chat_model(provider)
        return LangChainLLMAdapter(chat_model)


llm_registry = LlmProviderRegistry()
