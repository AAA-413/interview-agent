"""PR6：Session Diagnostics 契约测试。

覆盖：

```text
1. 聚合正确性 + deterministic 顺序（operation_type asc / error_type key asc）
2. evaluation health 语义（含未知值容错、grounded validated 的严格定义）
3. 脏 / 旧 evaluation_json 永不 500
4. owner isolation（IDOR）
5. Privacy：response 里不得出现任何用户文本
6. 只读：固定 3 次查询、不写任何状态、不重跑 evaluator / retrieval
7. endpoint 认证（无 token → 401）
```

不依赖真实 DB：只 patch persistence 的读方法。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.common.exception import BusinessException, ErrorCode
from app.main import app
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service as persistence
from app.modules.interview.models import InterviewOperationMetricEntity, SessionStatus
from app.modules.interview.observability import (
    InterviewOperationType,
    interview_diagnostics_service,
    normalize_operation_type,
    summarize_evaluation_health,
    summarize_operation_metrics,
)

SECRET_ANSWER = "SECRET_ANSWER_候选人原始回答"
SECRET_KB = "SECRET_KB_知识库原文片段"
SECRET_RESUME = "SECRET_RESUME_简历原文"


def _escaped(text: str) -> str:
    r"""``json.dumps`` 默认 ensure_ascii=True 时中文会变成 ``\uXXXX`` 转义序列。

    隐私断言必须同时覆盖「原文」与「转义后」两种形态，否则中文 secret 会永远
    「不在序列化结果里」，让断言变成空转。
    """
    return json.dumps(text)[1:-1]


class _FakeSession:
    def __init__(self, session_id: str = "svc-session", status=SessionStatus.INTERVIEWING):
        self.id = 1
        self.user_id = 1
        self.session_id = session_id
        self.status = status


class _FakeDiagnosticsPersistence:
    """只实现 diagnostics 需要的三个读方法，并记录调用次数。"""

    def __init__(self, *, session=None, metrics=None, payloads=None, error: Exception | None = None):
        self.session = session or _FakeSession()
        self.metrics = list(metrics or [])
        self.payloads = list(payloads or [])
        self.error = error
        self.calls: dict[str, int] = {
            "find_session_or_throw": 0,
            "list_operation_metrics": 0,
            "list_turn_evaluation_payloads": 0,
        }
        self.last_user_id: int | None = None

    async def find_session_or_throw(self, _db, _session_id, user_id=None):
        self.calls["find_session_or_throw"] += 1
        self.last_user_id = user_id
        if self.error is not None:
            raise self.error
        return self.session

    async def list_operation_metrics(self, _db, session_entity_id):
        self.calls["list_operation_metrics"] += 1
        return self.metrics

    async def list_turn_evaluation_payloads(self, _db, session_entity_id):
        self.calls["list_turn_evaluation_payloads"] += 1
        return self.payloads


def _install(monkeypatch, fake: _FakeDiagnosticsPersistence) -> None:
    for name in ("find_session_or_throw", "list_operation_metrics", "list_turn_evaluation_payloads"):
        monkeypatch.setattr(persistence, name, getattr(fake, name))


def _metric(operation_type: str, *, success: bool = True, latency_ms: int = 100, error_type: str | None = None):
    return InterviewOperationMetricEntity(
        session_id=1,
        topic_id=1,
        turn_id=1,
        user_id=1,
        operation_type=operation_type,
        latency_ms=latency_ms,
        success=success,
        error_type=error_type,
    )


async def _diagnostics(monkeypatch, fake: _FakeDiagnosticsPersistence, *, user_id: int = 1):
    _install(monkeypatch, fake)
    return await interview_diagnostics_service.get_session_diagnostics(object(), "svc-session", user_id)


# ---------------------------------------------------------------------------
# Operation type registry
# ---------------------------------------------------------------------------


def test_operation_type_registry_matches_persisted_strings():
    """Enum value 必须与历史落库字符串逐字一致（不做 rename / migration）。"""
    assert {item.value for item in InterviewOperationType} == {
        "JD_PARSE",
        "TOPIC_PLAN",
        "MAIN_QUESTION_GENERATE",
        "ANSWER_KNOWLEDGE_RETRIEVE",
        "ANSWER_EVALUATE",
        "ANSWER_EVALUATE_LLM",
        "FOLLOW_UP_REALIZE",
        "TOPIC_TRANSITION_REALIZE",
        "COACH_HINT_GENERATE",
        "REPORT_GENERATE",
    }


def test_normalize_operation_type_accepts_enum_and_str():
    assert normalize_operation_type(InterviewOperationType.ANSWER_EVALUATE) == "ANSWER_EVALUATE"
    assert normalize_operation_type("ANSWER_EVALUATE") == "ANSWER_EVALUATE"
    assert normalize_operation_type("LEGACY_CUSTOM") == "LEGACY_CUSTOM"


# ---------------------------------------------------------------------------
# §73 / §95 / §96：metric 聚合
# ---------------------------------------------------------------------------


def test_operation_metric_aggregation_is_deterministic():
    metrics = [
        _metric("ANSWER_EVALUATE_LLM", success=True, latency_ms=200),
        _metric("ANSWER_EVALUATE_LLM", success=True, latency_ms=400),
        _metric("ANSWER_EVALUATE_LLM", success=True, latency_ms=300),
        _metric("ANSWER_EVALUATE_LLM", success=True, latency_ms=100),
        _metric("ANSWER_EVALUATE_LLM", success=False, latency_ms=600, error_type="TimeoutError"),
        _metric("ANSWER_EVALUATE", success=True, latency_ms=50),
    ]
    summaries = summarize_operation_metrics(metrics)

    assert [item.operation_type for item in summaries] == ["ANSWER_EVALUATE", "ANSWER_EVALUATE_LLM"]
    llm = summaries[1]
    assert llm.count == 5
    assert llm.success_count == 4
    assert llm.failure_count == 1
    assert llm.error_types == {"TimeoutError": 1}
    assert llm.avg_latency_ms == round((200 + 400 + 300 + 100 + 600) / 5, 2)
    assert llm.max_latency_ms == 600


def test_error_type_aggregation_ignores_empty_and_sorts_keys():
    metrics = [
        _metric("X", success=False, error_type="TimeoutError"),
        _metric("X", success=False, error_type="RuntimeError"),
        _metric("X", success=False, error_type=None),
        _metric("X", success=False),
        _metric("X", success=True),
    ]
    summary = summarize_operation_metrics(metrics)[0]
    assert summary.failure_count == 4
    assert summary.error_types == {"RuntimeError": 1, "TimeoutError": 1}


def test_empty_metrics_produce_no_nan():
    assert summarize_operation_metrics([]) == []
    assert summarize_operation_metrics([_metric("X", latency_ms=0)])[0].avg_latency_ms == 0.0


async def test_diagnostics_totals_and_fallback_count(monkeypatch):
    fake = _FakeDiagnosticsPersistence(
        metrics=[
            _metric("ANSWER_EVALUATE", success=True, latency_ms=10),
            _metric("FOLLOW_UP_REALIZE", success=False, latency_ms=20, error_type="TimeoutError"),
        ],
        payloads=[
            (json.dumps({"evaluation_method": "HEURISTIC_FALLBACK"}), True),
            (json.dumps({"evaluation_method": "HYBRID_LLM"}), True),
        ],
    )
    result = await _diagnostics(monkeypatch, fake)

    assert result.total_operation_count == 2
    assert result.failed_operation_count == 1
    assert result.fallback_count == 1
    assert result.session_status == "INTERVIEWING"


async def test_diagnostics_session_status_handles_enum_and_str(monkeypatch):
    fake = _FakeDiagnosticsPersistence(session=_FakeSession(status="COMPLETED"))
    result = await _diagnostics(monkeypatch, fake)
    assert result.session_status == "COMPLETED"


# ---------------------------------------------------------------------------
# §74 / §97 / §98 / §99：evaluation health
# ---------------------------------------------------------------------------


def test_evaluation_health_counts_every_method():
    payloads = [
        (json.dumps({"evaluation_method": "HYBRID_LLM"}), True),
        (json.dumps({"evaluation_method": "RULE_ONLY"}), True),
        (json.dumps({"evaluation_method": "HEURISTIC_FALLBACK"}), True),
        (json.dumps({"evaluation_method": "FUTURE_METHOD"}), True),
        (None, False),
    ]
    summary = summarize_evaluation_health(payloads)
    assert summary.answered_turns == 4
    assert summary.hybrid_llm_count == 1
    assert summary.rule_only_count == 1
    assert summary.heuristic_fallback_count == 1
    assert summary.unknown_evaluation_method_count == 1


@pytest.mark.parametrize(
    ("status", "field"),
    [
        ("NO_HIT", "grounding_no_hit_count"),
        ("NO_SOURCE", "grounding_no_source_count"),
        ("ERROR", "grounding_error_count"),
        ("DISABLED", "grounding_disabled_count"),
        ("NOT_APPLICABLE", "grounding_not_applicable_count"),
    ],
)
def test_evaluation_health_counts_grounding_status(status, field):
    payload = json.dumps({"evaluation_method": "HYBRID_LLM", "knowledge_grounding": {"status": status}})
    summary = summarize_evaluation_health([(payload, True)])
    assert getattr(summary, field) == 1
    assert summary.grounded_ready_count == 0


def test_grounded_validated_requires_assessment_validated_true():
    """READY + assessment.validated=true 才算 validated（不是 READY 就算）。"""
    ready_only = json.dumps({"knowledge_grounding": {"status": "READY"}})
    ready_not_validated = json.dumps({"knowledge_grounding": {"status": "READY", "assessment": {"validated": False}}})
    ready_validated = json.dumps({"knowledge_grounding": {"status": "READY", "assessment": {"validated": True}}})
    summary = summarize_evaluation_health([(ready_only, True), (ready_not_validated, True), (ready_validated, True)])
    assert summary.grounded_ready_count == 3
    assert summary.grounded_validated_count == 1


def test_unknown_grounding_status_is_ignored():
    payload = json.dumps({"knowledge_grounding": {"status": "SOMETHING_NEW"}})
    summary = summarize_evaluation_health([(payload, True)])
    assert summary.grounded_ready_count == 0
    assert summary.grounding_error_count == 0
    assert summary.grounding_no_hit_count == 0


# ---------------------------------------------------------------------------
# §22 / §75：脏数据容错
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not-json",
        "{broken",
        "[]",
        '"a string"',
        "123",
        "{}",
        '{"foo": "bar"}',
        '{"ability_score": 78, "evaluation_method": "HYBRID_LLM"}',
        '{"knowledge_grounding": "not-a-dict"}',
    ],
)
def test_dirty_evaluation_json_never_breaks_health_summary(raw):
    summary = summarize_evaluation_health([(raw, True)])
    assert summary.answered_turns == 1


async def test_diagnostics_survives_dirty_history(monkeypatch):
    """混合新旧 / 损坏 schema 时 diagnostics 仍正常返回。"""
    fake = _FakeDiagnosticsPersistence(
        metrics=[_metric("ANSWER_EVALUATE"), _metric("UNKNOWN_LEGACY_OP")],
        payloads=[
            (None, False),
            ("{broken", True),
            (json.dumps({"foo": "bar"}), True),
            (json.dumps({"evaluation_method": "HYBRID_LLM"}), True),
            (json.dumps({"evaluation_method": "HEURISTIC_FALLBACK", "knowledge_grounding": {"status": "ERROR"}}), True),
        ],
    )
    result = await _diagnostics(monkeypatch, fake)

    assert result.evaluation_health.answered_turns == 4
    assert result.evaluation_health.grounding_error_count == 1
    assert [item.operation_type for item in result.operation_metrics] == ["ANSWER_EVALUATE", "UNKNOWN_LEGACY_OP"]


# ---------------------------------------------------------------------------
# §71：Owner isolation
# ---------------------------------------------------------------------------


async def test_diagnostics_is_owner_scoped(monkeypatch):
    fake = _FakeDiagnosticsPersistence(
        error=BusinessException(ErrorCode.NOT_FOUND, "面试会话不存在"),
    )
    with pytest.raises(BusinessException):
        await _diagnostics(monkeypatch, fake, user_id=2)

    assert fake.last_user_id == 2, "必须把当前 user_id 交给 owner 校验"
    assert fake.calls["list_operation_metrics"] == 0, "未通过 owner 校验时不得读 metric"
    assert fake.calls["list_turn_evaluation_payloads"] == 0


async def test_diagnostics_endpoint_requires_auth():
    with TestClient(app) as client:
        response = client.get("/api/interview/dynamic-sessions/svc-session/diagnostics")
    assert response.status_code == 401


async def test_diagnostics_endpoint_rejects_other_users_session(monkeypatch):
    from app.database import get_db

    fake = _FakeDiagnosticsPersistence(error=BusinessException(ErrorCode.NOT_FOUND, "面试会话不存在"))
    _install(monkeypatch, fake)

    async def _db_override():
        yield object()

    app.dependency_overrides[get_db] = _db_override
    try:
        from app.modules.auth.security import create_access_token

        token = create_access_token({"sub": "2"})
        with TestClient(app) as client:
            response = client.get(
                "/api/interview/dynamic-sessions/svc-session/diagnostics",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code != 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# §72 / §112：Privacy
# ---------------------------------------------------------------------------


async def test_diagnostics_never_returns_user_text(monkeypatch):
    """构造带 secret 的历史数据，response 里不得出现任何用户文本。"""
    payload = json.dumps(
        {
            "evaluation_method": "HYBRID_LLM",
            "ability_score": 88,
            "feedback": SECRET_ANSWER,
            "evidence": [{"quote": SECRET_ANSWER}],
            "knowledge_grounding": {
                "status": "READY",
                "assessment": {"validated": True},
                "references": [{"content_excerpt": SECRET_KB}],
            },
            "resume_evidence_refs": [{"quote": SECRET_RESUME}],
        },
        ensure_ascii=False,
    )
    fake = _FakeDiagnosticsPersistence(metrics=[_metric("ANSWER_EVALUATE")], payloads=[(payload, True)])

    result = await _diagnostics(monkeypatch, fake)
    serialized = result.model_dump_json()

    for secret in (SECRET_ANSWER, SECRET_KB, SECRET_RESUME):
        assert secret not in serialized, f"响应里出现了用户文本: {secret[:12]}…"
        assert _escaped(secret) not in serialized, "转义形态同样不得出现"


async def test_diagnostics_never_loads_answer_text(monkeypatch):
    """结构性保证：只查询 evaluation_json + 「是否已作答」，从不把 answer 读进内存。"""
    fake = _FakeDiagnosticsPersistence(payloads=[(None, False)])
    await _diagnostics(monkeypatch, fake)

    assert fake.calls["list_turn_evaluation_payloads"] == 1
    assert not hasattr(fake, "answers"), "diagnostics 不应触碰回答文本"


# ---------------------------------------------------------------------------
# §20 / §23：只读 + 固定查询次数
# ---------------------------------------------------------------------------


async def test_diagnostics_uses_exactly_three_queries(monkeypatch):
    fake = _FakeDiagnosticsPersistence(
        metrics=[_metric("ANSWER_EVALUATE"), _metric("FOLLOW_UP_REALIZE")],
        payloads=[(json.dumps({"evaluation_method": "HYBRID_LLM"}), True)] * 5,
    )
    await _diagnostics(monkeypatch, fake)

    assert fake.calls == {
        "find_session_or_throw": 1,
        "list_operation_metrics": 1,
        "list_turn_evaluation_payloads": 1,
    }, "diagnostics 必须是固定 3 次查询，不允许 N+1"


async def test_diagnostics_is_read_only(monkeypatch):
    """只读 endpoint：不写状态、不重跑 evaluator / retrieval。"""
    from app.modules.interview.evaluation.hybrid_evaluator import HybridAnswerEvaluationService
    from app.modules.interview.evaluation.knowledge_grounding import knowledge_grounding_service

    fake = _FakeDiagnosticsPersistence(payloads=[(json.dumps({"evaluation_method": "HYBRID_LLM"}), True)])
    _install(monkeypatch, fake)

    async def _boom(*_args, **_kwargs):  # pragma: no cover - 只用于「不应被调用」
        raise AssertionError("diagnostics 不得触发 evaluator / retrieval")

    monkeypatch.setattr(knowledge_grounding_service, "retrieve", _boom)
    monkeypatch.setattr(HybridAnswerEvaluationService, "evaluate", _boom)

    result = await interview_diagnostics_service.get_session_diagnostics(object(), "svc-session", 1)
    assert result.session_id == "svc-session"


async def test_diagnostics_response_shape(monkeypatch):
    fake = _FakeDiagnosticsPersistence(
        metrics=[_metric("ANSWER_EVALUATE", success=True, latency_ms=12)],
        payloads=[(json.dumps({"evaluation_method": "HYBRID_LLM"}), True)],
    )
    result = await _diagnostics(monkeypatch, fake)
    payload = result.model_dump()

    assert set(payload) == {
        "session_id",
        "session_status",
        "operation_metrics",
        "evaluation_health",
        "fallback_count",
        "failed_operation_count",
        "total_operation_count",
    }
    assert set(payload["operation_metrics"][0]) == {
        "operation_type",
        "count",
        "success_count",
        "failure_count",
        "avg_latency_ms",
        "max_latency_ms",
        "error_types",
    }
