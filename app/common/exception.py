from app.common.error_code import ErrorCode, get_error_message


class BusinessException(Exception):
    def __init__(self, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, message: str = ""):
        self.error_code = error_code
        # 如果没有提供自定义消息，使用友好的默认消息
        self.message = message or get_error_message(error_code, error_code.name)
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
