from enum import IntEnum


class ErrorCode(IntEnum):
    SUCCESS = 0
    BAD_REQUEST = 400
    NOT_FOUND = 404
    RATE_LIMIT_EXCEEDED = 429
    INTERNAL_ERROR = 500

    # AI 服务相关错误 (1xxx)
    AI_SERVICE_ERROR = 1001
    LLM_TIMEOUT = 1002
    LLM_RATE_LIMIT = 1003
    EMBEDDING_FAILED = 1004
    STT_STREAM_ERROR = 1005  # 流式 STT (WebSocket) 处理异常

    # 简历相关错误 (2xxx)
    RESUME_NOT_FOUND = 2001
    RESUME_PARSE_FAILED = 2002
    RESUME_UPLOAD_FAILED = 2003
    RESUME_ANALYSIS_FAILED = 2004
    RESUME_FILE_TOO_LARGE = 2005
    RESUME_FORMAT_UNSUPPORTED = 2006

    # 面试相关错误 (3xxx)
    INTERVIEW_SESSION_NOT_FOUND = 3001
    INTERVIEW_QUESTION_NOT_FOUND = 3002
    INTERVIEW_QUESTION_GENERATION_FAILED = 3003
    INTERVIEW_EVALUATION_FAILED = 3004
    INTERVIEW_NOT_COMPLETED = 3005
    INTERVIEW_ALREADY_COMPLETED = 3006
    INTERVIEW_REPORT_GENERATING = 3007
    INTERVIEW_REPORT_GENERATION_FAILED = 3008

    # 知识库相关错误 (4xxx)
    KNOWLEDGE_BASE_QUERY_FAILED = 4001
    KNOWLEDGE_BASE_NOT_FOUND = 4002
    KNOWLEDGE_BASE_UPLOAD_FAILED = 4003
    KNOWLEDGE_BASE_EMPTY = 4004
    KNOWLEDGE_BASE_INDEX_FAILED = 4005
    KNOWLEDGE_BASE_FETCH_FAILED = 4006


# 错误码对应的用户友好提示
ERROR_MESSAGES = {
    ErrorCode.LLM_TIMEOUT: "AI 服务响应超时，请稍后重试",
    ErrorCode.LLM_RATE_LIMIT: "AI 服务调用频繁，请稍后再试",
    ErrorCode.EMBEDDING_FAILED: "文档向量化失败，请检查文档格式或稍后重试",
    ErrorCode.KNOWLEDGE_BASE_EMPTY: "知识库为空，请先上传文档",
    ErrorCode.KNOWLEDGE_BASE_INDEX_FAILED: "知识库索引失败，请重新上传或联系管理员",
    ErrorCode.KNOWLEDGE_BASE_FETCH_FAILED: "文档抓取失败，请检查 URL 是否有效",
    ErrorCode.RESUME_NOT_FOUND: "简历不存在或已被删除",
    ErrorCode.RESUME_FILE_TOO_LARGE: "简历文件过大（最大 10MB），请压缩后重试",
    ErrorCode.RESUME_FORMAT_UNSUPPORTED: "不支持的文件格式，请上传 PDF、DOC 或 DOCX 文件",
    ErrorCode.RESUME_PARSE_FAILED: "简历解析失败，请检查文件内容或更换格式",
    ErrorCode.INTERVIEW_SESSION_NOT_FOUND: "面试会话不存在或已被删除",
    ErrorCode.INTERVIEW_REPORT_GENERATING: "面试报告生成中，请稍后刷新页面查看",
    ErrorCode.INTERVIEW_NOT_COMPLETED: "面试尚未完成，请先完成所有题目",
    ErrorCode.INTERVIEW_ALREADY_COMPLETED: "该面试已完成，无法继续答题",
    ErrorCode.INTERVIEW_REPORT_GENERATION_FAILED: "面试报告生成失败，请稍后重试",
    ErrorCode.KNOWLEDGE_BASE_NOT_FOUND: "知识库不存在或已被删除",
}


def get_error_message(error_code: ErrorCode, default_message: str = "") -> str:
    """获取错误码对应的用户友好提示"""
    return ERROR_MESSAGES.get(error_code, default_message or "操作失败，请稍后重试")
