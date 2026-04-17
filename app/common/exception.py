from app.common.error_code import ErrorCode


class BusinessException(Exception):
    def __init__(self, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, message: str = ""):
        self.error_code = error_code
        self.message = message or error_code.name
        super().__init__(self.message)


class RateLimitExceededException(BusinessException):
    def __init__(self, message: str = "请求过于频繁，请稍后再试"):
        super().__init__(ErrorCode.RATE_LIMIT_EXCEEDED, message)
