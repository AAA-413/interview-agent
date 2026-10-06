import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_BAILIAN_API_KEY", "dummy-key")

import pytest
from fastapi.testclient import TestClient

from app.common.config_check import build_config_check_report
from app.common.result import Result
from app.config import CorsSettings, settings
from app.main import app

client = TestClient(app)


def _auth_headers(user_id: int = 1) -> dict[str, str]:
    from app.modules.auth.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


def test_health_endpoint_contract():
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    # 不硬编码 app_name：.env 里改 APP_NAME 不应该让契约测试失败
    assert payload["status"] == "UP"
    assert payload["service"] == settings.app_name
    # liveness 只回答「进程活着」，不得泄漏 DB / Redis / provider / key 状态
    assert set(payload) == {"status", "service"}


def test_health_endpoint_is_public():
    assert client.get("/api/health").status_code == 200


def test_config_health_requires_auth():
    """PR6：config report 含 host:port 与缺失配置清单，不再匿名公开。"""
    response = client.get("/api/health/config")
    assert response.status_code == 401


def test_config_health_with_valid_user():
    response = client.get("/api/health/config", headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"OK", "WARN", "ERROR"}
    assert isinstance(payload["strict"], bool)
    assert isinstance(payload["issue_count"], int)
    if settings.debug:
        assert isinstance(payload["issues"], list)
    else:
        assert payload["issues"] is None, "production 模式不得返回 issue 详情"


def test_config_health_production_response_is_minimal(monkeypatch):
    """production（debug=False）只返回聚合计数，不返回 message / host / port。"""
    monkeypatch.setattr(settings, "debug", False, raising=False)
    app.state.config_report = None
    try:
        response = client.get("/api/health/config", headers=_auth_headers())
        assert response.status_code == 200
        assert set(response.json()) == {"status", "strict", "issue_count", "issues"}
        assert response.json()["issues"] is None
    finally:
        app.state.config_report = build_config_check_report(settings)


@pytest.mark.parametrize(
    "path",
    [
        "/api/healthXYZ",
        "/api/health/config",
        "/api/health/config/extra",
        "/api/auth/loginXYZ",
    ],
)
def test_public_paths_do_not_allow_prefix_bypass(path):
    """PR6：公开路径改成精确匹配，前缀不能绕过认证。"""
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_paths_remain_public(path):
    assert client.get(path).status_code == 200


def test_auth_endpoints_remain_public():
    """登录 / 注册不能被健康检查的收紧误伤（无 token 时应是参数校验失败而不是 401）。"""
    from app.database import get_db

    async def _db_override():
        yield object()

    app.dependency_overrides[get_db] = _db_override
    try:
        for path in ("/api/auth/login", "/api/auth/register"):
            response = client.post(path, json={})
            assert response.status_code == 422, f"{path} 应因参数缺失失败，而不是被认证拦住"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_options_preflight_is_not_blocked_by_auth():
    """CORS 预检继续放行（不受认证中间件影响）。"""
    response = client.options("/api/interview/dynamic-sessions", headers={"Origin": "http://localhost:5176"})
    assert response.status_code != 401


def test_training_routes_are_registered():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/training/calibration" in paths
    assert "/api/training/plan" in paths
    assert "/api/training/tasks/progress" in paths
    assert "/api/training/trends" in paths


def test_dynamic_interview_routes_are_registered():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/interview/jd/parse" in paths
    assert "/api/interview/dynamic-sessions" in paths
    assert "/api/interview/dynamic-sessions/{session_id}/turns/{turn_id}/answer" in paths
    assert "/api/interview/dynamic-sessions/{session_id}/report" in paths
    assert "/api/interview/dynamic-sessions/{session_id}/topics/{topic_id}/rag-insight" in paths
    assert "/api/interview/dynamic-sessions/{session_id}/topics/{topic_id}/retry" in paths


def test_protected_endpoint_requires_bearer_token():
    response = client.get("/api/resumes")

    assert response.status_code == 401
    assert response.json()["detail"] == "未提供认证凭证"


def test_result_helpers_keep_response_shape():
    success = Result.success({"id": 1})
    failure = Result.error("bad request", code=400)

    assert success.model_dump() == {"code": 0, "message": "success", "data": {"id": 1}}
    assert failure.model_dump() == {"code": 400, "message": "bad request", "data": None}


def test_cors_origin_parser_trims_empty_values():
    settings = CorsSettings(allowed_origins="http://localhost:5173, http://localhost:5174,")

    assert settings.origins_list == ["http://localhost:5173", "http://localhost:5174"]


def test_config_report_flags_missing_core_services():
    from app.config import Settings

    settings = Settings(strict_config=True)
    settings.ai.bailian_api_key = "dummy-key"
    settings.database.host = "127.0.0.1"
    settings.database.port = 1
    settings.redis.host = "127.0.0.1"
    settings.redis.port = 1

    report = build_config_check_report(settings, check_ports=True)

    assert report.status == "ERROR"
    assert report.has_errors
    assert any(issue.key == "AI_BAILIAN_API_KEY" for issue in report.issues)
