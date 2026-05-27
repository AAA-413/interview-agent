import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_BAILIAN_API_KEY", "dummy-key")

from fastapi.testclient import TestClient

from app.common.config_check import build_config_check_report
from app.common.result import Result
from app.config import CorsSettings
from app.main import app

client = TestClient(app)


def test_health_endpoint_contract():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "AI Interview Platform"}


def test_config_health_endpoint_contract():
    response = client.get("/api/health/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"OK", "WARN", "ERROR"}
    assert isinstance(payload["issues"], list)


def test_training_routes_are_registered():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/training/calibration" in paths
    assert "/api/training/plan" in paths


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
