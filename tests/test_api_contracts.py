import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_BAILIAN_API_KEY", "dummy-key")

from fastapi.testclient import TestClient

from app.common.result import Result
from app.config import CorsSettings
from app.main import app

client = TestClient(app)


def test_health_endpoint_contract():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "UP", "service": "AI Interview Platform"}


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
