import logging
from typing import TypeVar

from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.config import settings

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

STRICT_JSON_INSTRUCTION = """
请仅返回可被 JSON 解析器直接解析的 JSON 对象，并严格满足字段结构要求：
1) 不要输出 Markdown 代码块（如 ```json）。
2) 不要输出任何解释文字、前后缀、注释。
3) 所有字符串内引号必须正确转义。
"""


class StructuredOutputInvoker:
    def __init__(self):
        self.max_attempts = settings.ai.structured_max_attempts
        self.include_last_error = settings.ai.structured_include_last_error
        self.use_repair_prompt = settings.ai.structured_retry_use_repair_prompt

    async def invoke(
        self,
        chat_model: ChatOpenAI,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        error_code: ErrorCode = ErrorCode.AI_SERVICE_ERROR,
        error_prefix: str = "",
        log_context: str = "",
    ) -> T:
        parser = PydanticOutputParser(pydantic_object=output_model)
        format_instructions = parser.get_format_instructions()
        full_system = f"{system_prompt}\n\n{format_instructions}"

        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            attempt_system = full_system if attempt == 1 else self._build_retry_prompt(full_system, last_error)
            try:
                messages = [
                    ("system", attempt_system),
                    ("human", user_prompt),
                ]
                response = await chat_model.ainvoke(messages)
                content = response.content if response.content else ""
                return parser.parse(content)
            except Exception as e:
                last_error = e
                if attempt < self.max_attempts:
                    logger.warning(
                        "%s结构化解析失败，准备重试: attempt=%d/%d, error=%s",
                        log_context, attempt, self.max_attempts, str(e),
                    )
                else:
                    logger.error(
                        "%s结构化解析失败，已达最大重试次数: attempts=%d, error=%s",
                        log_context, self.max_attempts, str(e),
                    )

        raise BusinessException(error_code, f"{error_prefix}{last_error}")

    def _build_retry_prompt(self, original_system: str, last_error: Exception | None) -> str:
        if not self.use_repair_prompt:
            return original_system

        parts = [original_system, "\n\n", STRICT_JSON_INSTRUCTION, "\n上次输出解析失败，请仅返回合法 JSON。"]

        if self.include_last_error and last_error:
            msg = str(last_error).replace("\n", " ").strip()[:200]
            parts.append(f"\n上次失败原因：{msg}")

        return "".join(parts)


structured_output_invoker = StructuredOutputInvoker()
