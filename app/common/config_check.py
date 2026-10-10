import logging
import socket
from typing import Literal

from pydantic import BaseModel, Field

from app.config import Settings

ConfigSeverity = Literal["ERROR", "WARN", "INFO"]


class ConfigIssueDTO(BaseModel):
    severity: ConfigSeverity
    key: str
    message: str


class ConfigCheckReportDTO(BaseModel):
    status: Literal["OK", "WARN", "ERROR"]
    strict: bool = False
    issues: list[ConfigIssueDTO] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "ERROR" for issue in self.issues)


class PublicConfigIssueDTO(BaseModel):
    """对外暴露的 issue（已 redact）。"""

    severity: ConfigSeverity
    key: str
    message: str


class PublicConfigHealthDTO(BaseModel):
    """``/api/health/config`` 的对外形状。

    PR6 起这个 endpoint **需要认证**，并且 production（``debug=False``）只返回聚合
    计数 —— config report 里包含 `PostgreSQL host:port` / `Redis host:port` /
    「哪些内部配置缺失」这类信息，没有理由匿名暴露给公网。
    """

    status: Literal["OK", "WARN", "ERROR"]
    strict: bool
    issue_count: int
    #: debug=False 时为 None；debug=True 时是已脱敏的 issue 列表
    issues: list[PublicConfigIssueDTO] | None = None


#: 敏感值被替换成的占位符
SECRET_MASK = "***"


def collect_secret_values(settings: Settings) -> tuple[str, ...]:
    """收集所有「有可能出现在 issue.message 里」的敏感值，用于兜底 redact。

    只用于**删除**敏感值，不用于输出。长度 < 4 的短串跳过，避免把普通词误伤。
    """
    candidates = [
        settings.ai.bailian_api_key,
        settings.ai.zhipu_api_key,
        settings.ai.embedding_api_key,
        settings.database.password,
        settings.redis.password,
        settings.storage.access_key,
        settings.storage.secret_key,
    ]
    return tuple(value for value in candidates if value and len(value) >= 4)


def redact_secrets(text: str, secrets: tuple[str, ...]) -> str:
    """兜底：万一 message 里拼进了密钥，也要先抹掉再对外返回。"""
    redacted = text
    for secret in secrets:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, SECRET_MASK)
    return redacted


def build_public_config_health(
    report: ConfigCheckReportDTO,
    *,
    debug: bool,
    secrets: tuple[str, ...] = (),
) -> PublicConfigHealthDTO:
    """把内部 config report 收敛成可对外返回的最小信息。

    - ``debug=False``（production）→ 只有 status / strict / issue_count
    - ``debug=True`` → 额外返回已脱敏的 ``severity / key / message``
    """
    issues: list[PublicConfigIssueDTO] | None = None
    if debug:
        issues = [
            PublicConfigIssueDTO(
                severity=issue.severity,
                key=issue.key,
                message=redact_secrets(issue.message, secrets),
            )
            for issue in report.issues
        ]
    return PublicConfigHealthDTO(
        status=report.status,
        strict=report.strict,
        issue_count=len(report.issues),
        issues=issues,
    )


def build_config_check_report(settings: Settings, check_ports: bool = True) -> ConfigCheckReportDTO:
    issues: list[ConfigIssueDTO] = []

    if check_ports:
        if not _port_open(settings.database.host, settings.database.port):
            issues.append(
                ConfigIssueDTO(
                    severity="ERROR" if settings.strict_config else "WARN",
                    key="POSTGRES_HOST/POSTGRES_PORT",
                    message=f"PostgreSQL 不可连接：{settings.database.host}:{settings.database.port}",
                )
            )

        if not _port_open(settings.redis.host, settings.redis.port):
            issues.append(
                ConfigIssueDTO(
                    severity="ERROR" if settings.strict_config else "WARN",
                    key="REDIS_HOST/REDIS_PORT",
                    message=f"Redis 不可连接：{settings.redis.host}:{settings.redis.port}",
                )
            )

    if _looks_missing(settings.ai.bailian_api_key):
        issues.append(
            ConfigIssueDTO(
                severity="ERROR" if settings.strict_config else "WARN",
                key="AI_BAILIAN_API_KEY",
                message="AI API Key 未配置或仍为占位值，出题、评估、诊断增强能力会不可用。",
            )
        )

    if settings.ai.embedding_provider == "zhipu" and _looks_missing(settings.ai.zhipu_api_key):
        issues.append(
            ConfigIssueDTO(
                # strict 下 embedding key 缺失是**启动级**错误：provider=zhipu 却没有 key，
                # 向量化会直接失败（strict 模式下更是 fail closed），必须尽早暴露。
                severity="ERROR" if settings.strict_config else "WARN",
                key="AI_ZHIPU_API_KEY",
                message="Embedding Provider 为 zhipu，但智谱 Key 未配置，知识库索引会降级或失败。",
            )
        )

    if settings.ai.embedding_provider == "dashscope" and _looks_missing(
        settings.ai.embedding_api_key or settings.ai.bailian_api_key
    ):
        issues.append(
            ConfigIssueDTO(
                severity="ERROR" if settings.strict_config else "WARN",
                key="AI_EMBEDDING_API_KEY",
                message="Embedding Key 未配置，知识库向量化会降级或失败。",
            )
        )

    required_frontend_origins = {"http://localhost:5176", "http://127.0.0.1:5176"}
    missing_frontend_origins = required_frontend_origins.difference(settings.cors.origins_list)
    if missing_frontend_origins:
        issues.append(
            ConfigIssueDTO(
                severity="WARN",
                key="CORS_ALLOWED_ORIGINS",
                message=f"CORS 未包含 ./start.sh 默认前端地址：{', '.join(sorted(missing_frontend_origins))}。",
            )
        )

    if _looks_missing(settings.storage.access_key) or _looks_missing(settings.storage.secret_key):
        issues.append(
            ConfigIssueDTO(
                severity="WARN",
                key="APP_STORAGE_ACCESS_KEY/APP_STORAGE_SECRET_KEY",
                message="对象存储凭证未配置，文件上传和导出链路可能不可用。",
            )
        )

    status: Literal["OK", "WARN", "ERROR"] = "OK"
    if any(issue.severity == "ERROR" for issue in issues):
        status = "ERROR"
    elif issues:
        status = "WARN"

    return ConfigCheckReportDTO(status=status, strict=settings.strict_config, issues=issues)


def log_config_check_report(report: ConfigCheckReportDTO, logger: logging.Logger) -> None:
    if report.status == "OK":
        logger.info("配置检查通过")
        return

    for issue in report.issues:
        log = logger.error if issue.severity == "ERROR" else logger.warning
        log("配置检查%s: %s - %s", issue.severity, issue.key, issue.message)


def _looks_missing(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return normalized in {"", "your_api_key", "your_dashscope_api_key", "your_zhipu_api_key", "dummy-key"}


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
