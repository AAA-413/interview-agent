from langchain_openai import ChatOpenAI
import time
import logging
from openai import APITimeoutError, RateLimitError

from app.config import settings
from app.common.exception import LLMTimeoutException, LLMRateLimitException

logger = logging.getLogger(__name__)


class LlmProviderRegistry:
    def __init__(self):
        self._providers: dict[str, ChatOpenAI] = {}
        self._init_default_providers()

    def _init_default_providers(self) -> None:
        ai = settings.ai
        self._providers["dashscope"] = ChatOpenAI(
            base_url=ai.base_url,
            api_key=ai.bailian_api_key,
            model=ai.model,
            temperature=ai.temperature,
            max_tokens=4096,
            request_timeout=60,  # 从 180 秒改为 60 秒
            max_retries=2,       # 添加自动重试 2 次
        )
        logger.info("LLM Provider 初始化: model=%s, timeout=60s, max_retries=2", ai.model)

    def get_chat_model(self, provider: str | None = None) -> ChatOpenAI:
        key = provider or "dashscope"
        if key in self._providers:
            model = self._providers[key]
            # 直接返回模型，不包装（避免 Pydantic 限制）
            return model
        raise ValueError(f"未找到 LLM Provider: {key}")

    def _wrap_with_monitoring(self, model: ChatOpenAI, provider: str) -> ChatOpenAI:
        """包装模型调用，添加监控日志和异常处理"""
        original_ainvoke = model.ainvoke

        async def monitored_ainvoke(messages, **kwargs):
            start = time.time()
            try:
                result = await original_ainvoke(messages, **kwargs)
                duration = time.time() - start

                # 记录 Token 消耗
                if hasattr(result, 'response_metadata'):
                    usage = result.response_metadata.get('token_usage', {})
                    logger.info(
                        "LLM调用成功: provider=%s, model=%s, duration=%.2fs, tokens=%s",
                        provider, model.model_name, duration, usage
                    )
                else:
                    logger.info(
                        "LLM调用成功: provider=%s, model=%s, duration=%.2fs",
                        provider, model.model_name, duration
                    )
                return result
            except APITimeoutError as e:
                duration = time.time() - start
                logger.error(
                    "LLM调用超时: provider=%s, model=%s, duration=%.2fs, error=%s",
                    provider, model.model_name, duration, str(e)
                )
                raise LLMTimeoutException(f"AI 服务响应超时（{duration:.1f}秒），请稍后重试")
            except RateLimitError as e:
                duration = time.time() - start
                logger.error(
                    "LLM调用频率限制: provider=%s, model=%s, duration=%.2fs, error=%s",
                    provider, model.model_name, duration, str(e)
                )
                raise LLMRateLimitException("AI 服务调用频繁，请稍后再试（约 1 分钟）")
            except Exception as e:
                duration = time.time() - start
                logger.error(
                    "LLM调用失败: provider=%s, model=%s, duration=%.2fs, error=%s",
                    provider, model.model_name, duration, str(e)
                )
                raise

        model.ainvoke = monitored_ainvoke
        return model

    def register(self, name: str, chat_model: ChatOpenAI) -> None:
        self._providers[name] = chat_model

    @property
    def default(self) -> ChatOpenAI:
        return self.get_chat_model("dashscope")


llm_registry = LlmProviderRegistry()
