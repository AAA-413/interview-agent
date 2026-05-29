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
                severity="WARN",
                key="AI_ZHIPU_API_KEY",
                message="Embedding Provider 为 zhipu，但智谱 Key 未配置，知识库索引会降级或失败。",
            )
        )

    if settings.ai.embedding_provider == "dashscope" and _looks_missing(
        settings.ai.embedding_api_key or settings.ai.bailian_api_key
    ):
        issues.append(
            ConfigIssueDTO(
                severity="WARN",
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
