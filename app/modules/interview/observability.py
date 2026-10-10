"""PR6：面试引擎的**运维可观测性**层（Operation Registry + Session Diagnostics）。

定位
----
只做两件事：

```text
1. Operation Type Registry —— 消除散落的 operation_type magic string
2. Session Diagnostics      —— 把已有的 metric / evaluation 聚合成只读诊断视图
```

它**不是**新的智能能力，也不属于 correctness path：

```text
- 不重算 score
- 不重跑 evaluator / retrieval
- 不重新生成 report
- 不修改 session / topic / turn
- 不写任何 metric（只有读）
```

Privacy
-------
diagnostics 只返回**聚合元数据**。绝不返回：

```text
Candidate Answer
Resume 原文 / Resume Evidence quote
KB chunk content / Knowledge Evidence content
Prompt / System Prompt / LLM raw response
API Key / DB 地址 / Redis 地址
```

实现上还有一层结构性保证：读 turn 时只 `SELECT evaluation_json + 「是否已作答」布尔表达式`，
**从不把 answer 文本加载进内存**（见 ``list_turn_evaluation_payloads``）。
"""

from __future__ import annotations

import json
import logging
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class InterviewOperationType(str, Enum):
    """面试主链上**真实存在**的 operation metric 类型。

    取值必须与 `interview_operation_metrics.operation_type` 里已落库的历史字符串
    **逐字一致** —— 这是历史数据契约，不允许 rename，也不需要 migration。

    说明：session 的 ``generation_stages``（规划阶段进度）复用了 ``JD_PARSE`` /
    ``TOPIC_PLAN`` / ``MAIN_QUESTION_GENERATE`` 这几个**同名**字面量，但那是另一个
    概念（前端进度展示），不属于 metric operation registry，本 PR 不动它。
    """

    JD_PARSE = "JD_PARSE"
    TOPIC_PLAN = "TOPIC_PLAN"
    MAIN_QUESTION_GENERATE = "MAIN_QUESTION_GENERATE"

    ANSWER_KNOWLEDGE_RETRIEVE = "ANSWER_KNOWLEDGE_RETRIEVE"
    ANSWER_EVALUATE = "ANSWER_EVALUATE"
    ANSWER_EVALUATE_LLM = "ANSWER_EVALUATE_LLM"

    FOLLOW_UP_REALIZE = "FOLLOW_UP_REALIZE"
    TOPIC_TRANSITION_REALIZE = "TOPIC_TRANSITION_REALIZE"

    COACH_HINT_GENERATE = "COACH_HINT_GENERATE"
    REPORT_GENERATE = "REPORT_GENERATE"


def normalize_operation_type(operation_type: InterviewOperationType | str) -> str:
    """把 Enum / str 统一成落库字符串（backward compatible）。"""
    if isinstance(operation_type, InterviewOperationType):
        return operation_type.value
    return str(operation_type)


def _enum_value(value) -> str:
    """Enum / str 统一成字符串（``SessionStatus.INTERVIEWING`` → ``INTERVIEWING``）。"""
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# evaluation health：只识别已知取值，未知一律忽略（不报错）
# ---------------------------------------------------------------------------

#: `DynamicTurnEvaluationDTO.evaluation_method` 的已知取值
KNOWN_EVALUATION_METHODS: frozenset[str] = frozenset({"HYBRID_LLM", "RULE_ONLY", "HEURISTIC_FALLBACK"})

KNOWN_GROUNDING_STATUSES: tuple[str, ...] = (
    "READY",
    "NO_HIT",
    "NO_SOURCE",
    "ERROR",
    "DISABLED",
    "NOT_APPLICABLE",
)


class OperationMetricSummaryDTO(BaseModel):
    """按 operation_type 聚合的 metric 摘要。"""

    operation_type: str

    count: int = 0
    success_count: int = 0
    failure_count: int = 0

    avg_latency_ms: float = 0.0
    max_latency_ms: int = 0

    #: 非空 error_type → 出现次数（key 升序，deterministic）
    error_types: dict[str, int] = Field(default_factory=dict)


class EvaluationHealthSummaryDTO(BaseModel):
    """当前 session 的评分健康度（只读聚合，从 ``turn.evaluation_json`` 安全解析）。"""

    answered_turns: int = 0

    hybrid_llm_count: int = 0
    rule_only_count: int = 0
    heuristic_fallback_count: int = 0
    #: 无法识别的 evaluation_method（旧 / 未来 schema）—— 不报错，只计数
    unknown_evaluation_method_count: int = 0

    grounded_ready_count: int = 0
    #: 只有 ``status=READY`` 且 ``assessment.validated=true`` 才算（**不是** READY 即 validated）
    grounded_validated_count: int = 0

    grounding_no_hit_count: int = 0
    grounding_no_source_count: int = 0
    grounding_error_count: int = 0
    grounding_disabled_count: int = 0
    grounding_not_applicable_count: int = 0


class DynamicSessionDiagnosticsDTO(BaseModel):
    """一次面试 session 的只读诊断视图（聚合 metadata，不含任何用户文本）。"""

    session_id: str
    session_status: str

    operation_metrics: list[OperationMetricSummaryDTO] = Field(default_factory=list)

    evaluation_health: EvaluationHealthSummaryDTO = Field(default_factory=EvaluationHealthSummaryDTO)

    #: ``evaluation_method == HEURISTIC_FALLBACK`` 的已作答轮次数量
    fallback_count: int = 0

    #: ``success=False`` 的 metric 条数
    failed_operation_count: int = 0
    total_operation_count: int = 0


def summarize_operation_metrics(metrics: list) -> list[OperationMetricSummaryDTO]:
    """把 metric 实体聚合成 deterministic 摘要（operation_type 升序、error_type key 升序）。"""
    buckets: dict[str, dict] = {}
    for metric in metrics:
        operation = str(getattr(metric, "operation_type", "") or "")
        if not operation:
            continue
        bucket = buckets.setdefault(
            operation,
            {"count": 0, "success": 0, "failure": 0, "latency_total": 0, "latency_max": 0, "errors": {}},
        )
        bucket["count"] += 1
        if bool(getattr(metric, "success", True)):
            bucket["success"] += 1
        else:
            bucket["failure"] += 1
        latency = int(getattr(metric, "latency_ms", 0) or 0)
        bucket["latency_total"] += latency
        bucket["latency_max"] = max(bucket["latency_max"], latency)
        error_type = getattr(metric, "error_type", None)
        if error_type:
            bucket["errors"][str(error_type)] = bucket["errors"].get(str(error_type), 0) + 1

    summaries: list[OperationMetricSummaryDTO] = []
    for operation in sorted(buckets):
        bucket = buckets[operation]
        count = bucket["count"]
        summaries.append(
            OperationMetricSummaryDTO(
                operation_type=operation,
                count=count,
                success_count=bucket["success"],
                failure_count=bucket["failure"],
                # 无数据时 0，不产生 NaN
                avg_latency_ms=round(bucket["latency_total"] / count, 2) if count else 0.0,
                max_latency_ms=bucket["latency_max"],
                error_types={key: bucket["errors"][key] for key in sorted(bucket["errors"])},
            )
        )
    return summaries


def _parse_evaluation_payload(raw: str | None) -> dict:
    """安全解析 ``evaluation_json``：NULL / 坏 JSON / 非 dict 一律当空。

    Diagnostics 面对历史数据必须**永不 500**：
    旧 PR2 schema、PR3/PR4/PR5 schema、`{"foo": "bar"}`、被截断的 JSON 都只是
    「解析不出已知字段」，不影响其它聚合。
    """
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def summarize_evaluation_health(payloads: list[tuple[str | None, bool]]) -> EvaluationHealthSummaryDTO:
    """聚合 ``(evaluation_json, answered)`` 行。"""
    summary = EvaluationHealthSummaryDTO()
    for raw, answered in payloads:
        if answered:
            summary.answered_turns += 1

        payload = _parse_evaluation_payload(raw)

        method = payload.get("evaluation_method")
        if method == "HYBRID_LLM":
            summary.hybrid_llm_count += 1
        elif method == "RULE_ONLY":
            summary.rule_only_count += 1
        elif method == "HEURISTIC_FALLBACK":
            summary.heuristic_fallback_count += 1
        elif method is not None:
            summary.unknown_evaluation_method_count += 1

        grounding = payload.get("knowledge_grounding")
        if not isinstance(grounding, dict):
            continue
        status = grounding.get("status")
        if status == "READY":
            summary.grounded_ready_count += 1
            assessment = grounding.get("assessment")
            if isinstance(assessment, dict) and assessment.get("validated") is True:
                summary.grounded_validated_count += 1
        elif status == "NO_HIT":
            summary.grounding_no_hit_count += 1
        elif status == "NO_SOURCE":
            summary.grounding_no_source_count += 1
        elif status == "ERROR":
            summary.grounding_error_count += 1
        elif status == "DISABLED":
            summary.grounding_disabled_count += 1
        elif status == "NOT_APPLICABLE":
            summary.grounding_not_applicable_count += 1
        # 未知 status → 忽略（§98）
    return summary


class InterviewDiagnosticsService:
    """只读 diagnostics 聚合入口。"""

    async def get_session_diagnostics(self, db, session_id: str, user_id: int) -> DynamicSessionDiagnosticsDTO:
        """owner-scoped 聚合：先验证 session 归属，再读 metric / turn。

        查询次数固定为 3（session / metrics / turns），不做 per-turn 或 per-metric 查询。
        """
        # 延迟导入：observability 被 persistence_service 引用，模块级互引会成环
        from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service

        # 1) session + owner check（IDOR 防护：别人的 session 一律按「不存在」处理）
        session = await dynamic_interview_persistence_service.find_session_or_throw(db, session_id, user_id)

        # 2) metrics：一次 query
        metrics = await dynamic_interview_persistence_service.list_operation_metrics(db, session.id)

        # 3) turns：一次 query，且**只取 evaluation_json + 是否已作答**（不加载 answer 文本）
        payloads = await dynamic_interview_persistence_service.list_turn_evaluation_payloads(db, session.id)

        operation_metrics = summarize_operation_metrics(metrics)
        evaluation_health = summarize_evaluation_health(payloads)

        return DynamicSessionDiagnosticsDTO(
            session_id=str(getattr(session, "session_id", session_id)),
            session_status=_enum_value(getattr(session, "status", "")),
            operation_metrics=operation_metrics,
            evaluation_health=evaluation_health,
            fallback_count=evaluation_health.heuristic_fallback_count,
            failed_operation_count=sum(item.failure_count for item in operation_metrics),
            total_operation_count=sum(item.count for item in operation_metrics),
        )


interview_diagnostics_service = InterviewDiagnosticsService()
