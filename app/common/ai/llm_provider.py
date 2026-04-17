from langchain_openai import ChatOpenAI

from app.config import settings


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
            request_timeout=180,
        )

    def get_chat_model(self, provider: str | None = None) -> ChatOpenAI:
        key = provider or "dashscope"
        if key in self._providers:
            return self._providers[key]
        raise ValueError(f"未找到 LLM Provider: {key}")

    def register(self, name: str, chat_model: ChatOpenAI) -> None:
        self._providers[name] = chat_model

    @property
    def default(self) -> ChatOpenAI:
        return self.get_chat_model("dashscope")


llm_registry = LlmProviderRegistry()
