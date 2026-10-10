"""PR6：Config Check / Config Validation 契约测试。

覆盖三件事：

```text
1. embedding key 缺失在 strict / 非 strict 下的 severity
2. Settings 的字段约束与 cross-field 校验（错误配置必须在 parse 阶段失败）
3. config issue 的任何对外形式都不得泄漏 secret
```

测试全部显式传值 / 显式 monkeypatch，不依赖开发机 `.env`（CI 与本地结果必须一致）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.common.config_check import (
    SECRET_MASK,
    ConfigCheckReportDTO,
    ConfigIssueDTO,
    build_config_check_report,
    build_public_config_health,
    collect_secret_values,
    redact_secrets,
)
from app.config import AiSettings, InterviewSettings, Settings

FAKE_ZHIPU_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef"


def _issue_keys(report: ConfigCheckReportDTO) -> dict[str, str]:
    return {issue.key: issue.severity for issue in report.issues}


@pytest.fixture
def strict_off(monkeypatch):
    """把全局 settings 收敛成「只关心 embedding key」的确定状态（不查端口、不读 .env）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "strict_config", False, raising=False)
    monkeypatch.setattr(settings.ai, "embedding_provider", "zhipu", raising=False)
    monkeypatch.setattr(settings.ai, "zhipu_api_key", "", raising=False)
    monkeypatch.setattr(settings.ai, "bailian_api_key", "", raising=False)
    monkeypatch.setattr(settings.ai, "embedding_api_key", "", raising=False)
    return settings


# ---------------------------------------------------------------------------
# embedding key severity（§68 / §27）
# ---------------------------------------------------------------------------


def test_zhipu_key_missing_is_warn_when_not_strict(strict_off):
    report = build_config_check_report(strict_off, check_ports=False)
    assert _issue_keys(report)["AI_ZHIPU_API_KEY"] == "WARN"


def test_zhipu_key_missing_is_error_when_strict(strict_off, monkeypatch):
    monkeypatch.setattr(strict_off, "strict_config", True, raising=False)
    report = build_config_check_report(strict_off, check_ports=False)
    assert _issue_keys(report)["AI_ZHIPU_API_KEY"] == "ERROR"
    assert report.has_errors is True
    assert report.status == "ERROR"


def test_dashscope_key_missing_is_warn_when_not_strict(strict_off, monkeypatch):
    monkeypatch.setattr(strict_off.ai, "embedding_provider", "dashscope", raising=False)
    report = build_config_check_report(strict_off, check_ports=False)
    assert _issue_keys(report)["AI_EMBEDDING_API_KEY"] == "WARN"


def test_dashscope_key_missing_is_error_when_strict(strict_off, monkeypatch):
    monkeypatch.setattr(strict_off, "strict_config", True, raising=False)
    monkeypatch.setattr(strict_off.ai, "embedding_provider", "dashscope", raising=False)
    report = build_config_check_report(strict_off, check_ports=False)
    assert _issue_keys(report)["AI_EMBEDDING_API_KEY"] == "ERROR"


def test_valid_zhipu_config_has_no_embedding_issue(strict_off, monkeypatch):
    monkeypatch.setattr(strict_off.ai, "zhipu_api_key", FAKE_ZHIPU_KEY, raising=False)
    report = build_config_check_report(strict_off, check_ports=False)
    assert "AI_ZHIPU_API_KEY" not in _issue_keys(report)


def test_config_check_does_not_call_external_apis(monkeypatch):
    """config check 只检查配置形态，不做实时 API 调用（否则启动依赖外网）。"""
    import httpx

    def _boom(*_args, **_kwargs):  # pragma: no cover - 只用于「不应被调用」
        raise AssertionError("config check 不得发起网络请求")

    monkeypatch.setattr(httpx, "Client", _boom)
    report = build_config_check_report(Settings(), check_ports=False)
    assert report.status in {"OK", "WARN", "ERROR"}


# ---------------------------------------------------------------------------
# Settings 校验（§69）
# ---------------------------------------------------------------------------


def test_embedding_provider_typo_is_rejected():
    with pytest.raises(ValidationError):
        AiSettings(embedding_provider="zhhipu")


@pytest.mark.parametrize("provider", ["zhipu", "dashscope"])
def test_embedding_provider_accepts_known_values(provider):
    assert AiSettings(embedding_provider=provider).embedding_provider == provider


@pytest.mark.parametrize(
    "kwargs",
    [
        {"knowledge_grounding_min_score": -0.1},
        {"knowledge_grounding_min_score": 1.1},
        {"knowledge_grounding_top_k": 0},
        {"knowledge_grounding_candidate_k": 0},
        {"knowledge_grounding_timeout_seconds": 0},
        {"answer_evaluator_timeout_seconds": 0},
        {"question_realizer_timeout_seconds": 0},
        {"knowledge_grounding_candidate_k": 2, "knowledge_grounding_top_k": 4},
    ],
)
def test_interview_settings_rejects_invalid_values(kwargs):
    with pytest.raises(ValidationError):
        InterviewSettings(**kwargs)


def test_candidate_k_equal_top_k_is_allowed():
    assert (
        InterviewSettings(knowledge_grounding_candidate_k=4, knowledge_grounding_top_k=4).knowledge_grounding_top_k == 4
    )


def test_resume_canonical_timeout_must_be_positive():
    from app.config import ResumeSettings

    with pytest.raises(ValidationError):
        ResumeSettings(canonical_extractor_timeout_seconds=0)


def test_default_settings_are_valid():
    assert InterviewSettings().knowledge_grounding_candidate_k >= InterviewSettings().knowledge_grounding_top_k


# ---------------------------------------------------------------------------
# Secret 不得外泄（§32 / §37）
# ---------------------------------------------------------------------------


def test_public_health_hides_issues_in_production():
    report = ConfigCheckReportDTO(
        status="WARN",
        strict=False,
        issues=[ConfigIssueDTO(severity="WARN", key="X", message="PostgreSQL 不可连接：db.internal:5432")],
    )
    public = build_public_config_health(report, debug=False, secrets=())
    payload = public.model_dump()
    assert payload == {"status": "WARN", "strict": False, "issue_count": 1, "issues": None}
    assert "db.internal" not in str(payload)


def test_public_health_exposes_sanitized_issues_in_debug():
    report = ConfigCheckReportDTO(
        status="WARN",
        strict=False,
        issues=[ConfigIssueDTO(severity="WARN", key="AI_ZHIPU_API_KEY", message=f"key={FAKE_ZHIPU_KEY} 未配置")],
    )
    public = build_public_config_health(report, debug=True, secrets=(FAKE_ZHIPU_KEY,))
    payload = public.model_dump()
    assert payload["issues"][0]["key"] == "AI_ZHIPU_API_KEY"
    assert FAKE_ZHIPU_KEY not in str(payload)
    assert SECRET_MASK in payload["issues"][0]["message"]


def test_redact_secrets_masks_all_occurrences():
    text = f"first={FAKE_ZHIPU_KEY} second={FAKE_ZHIPU_KEY}"
    redacted = redact_secrets(text, (FAKE_ZHIPU_KEY,))
    assert FAKE_ZHIPU_KEY not in redacted
    assert redacted.count(SECRET_MASK) == 2


def test_collect_secret_values_skips_short_and_empty():
    from app.config import settings

    values = collect_secret_values(settings)
    assert all(len(value) >= 4 for value in values)
    assert all(value.strip() for value in values)


def test_real_config_report_never_leaks_configured_secrets():
    """端到端：真实 settings 生成的 report（含 debug 详情）不得出现任何已配置密钥。"""
    from app.config import settings

    report = build_config_check_report(settings, check_ports=False)
    public = build_public_config_health(report, debug=True, secrets=collect_secret_values(settings))
    serialized = str(public.model_dump())
    for secret in collect_secret_values(settings):
        assert secret not in serialized
