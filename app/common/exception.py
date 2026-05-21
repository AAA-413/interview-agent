from app.common.error_code import ErrorCode, get_error_message

# 错误码到 HTTP 状态码的映射
_ERROR_CODE_TO_HTTP_STATUS: dict[int, int] = {
    400: 400,  # BAD_REQUEST
    401: 401,  # UNAUTHORIZED
    403: 403,  # FORBIDDEN
    404: 404,  # NOT_FOUND
    429: 429,  # RATE_LIMIT_EXCEEDED
    ErrorCode.RESUME_NOT_FOUND: 404,
    ErrorCode.INTERVIEW_SESSION_NOT_FOUND: 404,
    ErrorCode.INTERVIEW_QUESTION_NOT_FOUND: 404,
    ErrorCode.KNOWLEDGE_BASE_NOT_FOUND: 404,
}


class BusinessException(Exception):
    def __init__(self, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, message: str = ""):
        self.error_code = error_code
        # 如果没有提供自定义消息，使用友好的默认消息
        self.message = message or get_error_message(error_code, error_code.name)
        # 根据错误码推断 HTTP 状态码
        self.status_code = _ERROR_CODE_TO_HTTP_STATUS.get(error_code, 500)
        super().__init__(self.message)


class RateLimitExceededException(BusinessException):
    def __init__(self, message: str = ""):
        super().__init__(ErrorCode.RATE_LIMIT_EXCEEDED, message or "请求过于频繁，请稍后再试")


class LLMTimeoutException(BusinessException):
    """LLM 调用超时异常"""

    def __init__(self, message: str = ""):
        super().__init__(ErrorCode.LLM_TIMEOUT, message)


class LLMRateLimitException(BusinessException):
    """LLM 调用频率限制异常"""

    def __init__(self, message: str = ""):
        super().__init__(ErrorCode.LLM_RATE_LIMIT, message)


class EmbeddingFailedException(BusinessException):
    """向量化失败异常"""

    def __init__(self, message: str = ""):
        super().__init__(ErrorCode.EMBEDDING_FAILED, message)
