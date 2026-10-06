"""PR3：Topic Coverage / TopicState / Adaptive Interview 测试（不调真实 LLM）。

覆盖验收用例 A-O：

- A. Canonical targets（三种题型 + Planner exit criteria 一致性）
- B. LLM coverage 校验（quote 校验 / unknown / duplicate / missing / 跨题型）
- C. Score 与 coverage 失败域隔离（PR3 §12 核心）
- D. Coverage 单调性
- E. Evidence 累积（去重 / 上限 / source_turn_ids）
- F. Heuristic fallback 最多 PARTIAL；RULE_ONLY 不更新
- G. next_target 优先级
- H. Adaptive STRICT
- I. Adaptive COACH
- J. Intent / fallback question 对齐
- K. Context（coverage 进入 context + fingerprint）
- L. Persistence（roundtrip / NULL / bad JSON / 同事务保存）
- O. EVALUATOR_VERSION
"""

from __future__ import annotations

import pytest

from app.modules.interview import evaluation as evaluation_module
from app.modules.interview.context.builder import InterviewContextBuilder
from app.modules.interview.dynamic_service import (
    CoachInterviewPolicy,
    InterviewPlanService,
    StrictInterviewPolicy,
    _TopicCandidate,
)
from app.modules.interview.evaluation.hybrid_evaluator import HybridAnswerEvaluationService
from app.modules.interview.evaluation.models import (
    EVALUATOR_VERSION,
    LLMCoverageAssessment,
    LLMDimensionAssessment,
    LLMEvaluationResult,
)
from app.modules.interview.models import TurnType
from app.modules.interview.schemas import (
    COVERAGE_STATUS_COVERED,
    COVERAGE_STATUS_NOT_COVERED,
    COVERAGE_STATUS_PARTIAL,
    DynamicTopicDTO,
    DynamicTurnDTO,
    DynamicTurnEvaluationDTO,
    EvaluationCoverageAssessmentDTO,
    TopicCoverageStateDTO,
)
from app.modules.interview.topic_state.models import (
    COVERAGE_TARGETS_BY_QUESTION_TYPE,
    build_coverage_state,
    coverage_ratio,
    initial_coverage_points,
    is_complete,
    merge_coverage_status,
    select_next_target,
    target_intent,
)
from app.modules.interview.topic_state.tracker import TopicCoverageTracker, topic_coverage_tracker

STRONG_ANSWER = (
    "这个异步任务队列是我负责设计和落地的。生产端用 XADD 写入 Redis Streams，"
    "消费端用 Consumer Group + XREADGROUP 多实例并行消费；每个任务带唯一 message_id 做幂等，"
    "超时任务用 XPENDING 捞出来重新投递，重试超过 3 次进死信。"
    "上线后 P99 从 800ms 降到 300ms，失败率从 2% 降到 0.3%。"
    "当时也对比过 Kafka，但团队只有两个人维护，运维成本不划算，所以放弃了。"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _topic(question_type: str = "PROJECT") -> DynamicTopicDTO:
    return DynamicTopicDTO(
        id=1,
        topic_key="async_task_pipeline",
        topic_title="异步任务流水线",
        skill_key="python",
        question_type=question_type,
        source_type="resume",
        evidence_snippet="实现异步任务队列（Redis Streams + Consumer Group）。",
        main_question="请讲清楚 Redis Streams 异步任务队列的设计。",
        topic_order=1,
        max_turns=3,
    )


def _turn(turn_order: int, answer: str, *, turn_type: str = TurnType.MAIN.value, score: int = 62) -> DynamicTurnDTO:
    return DynamicTurnDTO(
        id=turn_order,
        topic_id=1,
        turn_type=turn_type,
        turn_order=turn_order,
        question=f"问题 {turn_order}",
        answer=answer,
        ability_score=score,
    )


def _coverage(question_type: str = "PROJECT", **statuses: str) -> TopicCoverageStateDTO:
    points = initial_coverage_points(question_type)
    for key, status in statuses.items():
        points[key] = points[key].model_copy(update={"status": status})
    return build_coverage_state(points, question_type)


def _all_covered(question_type: str = "PROJECT") -> TopicCoverageStateDTO:
    return _coverage(question_type, **{key: COVERAGE_STATUS_COVERED for key in initial_coverage_points(question_type)})


def _evaluation(
    score: int = 75,
    *,
    method: str = "HYBRID_LLM",
    coverage: list[EvaluationCoverageAssessmentDTO] | None = None,
    gaps: list[str] | None = None,
) -> DynamicTurnEvaluationDTO:
    return DynamicTurnEvaluationDTO(
        ability_score=score,
        feedback="回答有基础。",
        signals={"strengths": [], "gaps": gaps or [], "risks": []},
        dimension_scores={},
        evaluation_method=method,
        confidence=0.8 if method == "HYBRID_LLM" else 0.35,
        coverage_assessments=coverage or [],
    )


def _assessment(key: str, status: str, quotes: list[str] | None = None) -> EvaluationCoverageAssessmentDTO:
    return EvaluationCoverageAssessmentDTO(target_key=key, status=status, evidence_quotes=quotes or [])


def _llm_result(
    dimensions: dict[str, int],
    evidence: dict[str, list[str]],
    coverage: list[LLMCoverageAssessment] | None = None,
) -> LLMEvaluationResult:
    return LLMEvaluationResult(
        dimensions=[
            LLMDimensionAssessment(
                dimension=dimension,
                score=score,
                assessment=f"{dimension} assessment",
                evidence_quotes=evidence.get(dimension, []),
            )
            for dimension, score in dimensions.items()
        ],
        coverage=coverage or [],
    )


class _StubInvoker:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def invoke(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _PassthroughSingleFlight:
    def __init__(self):
        self.keys: list[str] = []

    async def __call__(self, key, fn, **kwargs):
        self.keys.append(key)
        return await fn()


class _StubRegistry:
    def get_chat_model(self, provider=None):
        return f"model-for-{provider}"


def _service(monkeypatch, payload) -> tuple[HybridAnswerEvaluationService, _StubInvoker]:
    from app.modules.interview.dynamic_service import DynamicAnswerEvaluationService

    service = HybridAnswerEvaluationService(heuristic_evaluator=DynamicAnswerEvaluationService())
    invoker = _StubInvoker(payload)
    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "structured_output_invoker", invoker)
    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "single_flight", _PassthroughSingleFlight())
    monkeypatch.setattr("app.common.ai.llm_provider.llm_registry", _StubRegistry())
    return service, invoker


def _snapshot(question_type: str = "PROJECT"):
    from app.modules.interview.evaluation.models import EvaluationSnapshot

    topic = _topic(question_type)
    return EvaluationSnapshot(
        session_entity_id=1,
        session_id="session-pr3",
        user_id=1,
        session_status="INTERVIEWING",
        interview_mode="STRICT",
        llm_provider="dashscope",
        topic=topic,
        turn=DynamicTurnDTO(id=7, topic_id=1, turn_type="MAIN", turn_order=1, question=topic.main_question),
        previous_turns=[],
    )


# ---------------------------------------------------------------------------
# A. Canonical targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question_type,expected_keys",
    [
        ("PROJECT", ["PROJECT_GOAL", "PROJECT_OWNERSHIP", "PROJECT_RESULT_VALIDATION", "PROJECT_TRADEOFF_OR_FAILURE"]),
        ("KNOWLEDGE", ["KNOWLEDGE_DEFINITION", "KNOWLEDGE_MECHANISM", "KNOWLEDGE_SCENARIO", "KNOWLEDGE_BOUNDARY"]),
        ("SYSTEM_DESIGN", ["SYSTEM_COMPONENTS", "SYSTEM_DATA_FLOW", "SYSTEM_RELIABILITY", "SYSTEM_TRADEOFF"]),
    ],
)
def test_canonical_target_keys_per_question_type(question_type, expected_keys):
    targets = COVERAGE_TARGETS_BY_QUESTION_TYPE[question_type]
    assert [t.key for t in targets] == expected_keys
    assert [t.priority for t in targets] == [1, 2, 3, 4], "priority 顺序即定义顺序"
    assert all(t.label and t.description and t.intent for t in targets)


def test_target_intent_mapping_is_canonical():
    assert target_intent("PROJECT", "PROJECT_RESULT_VALIDATION") == "VERIFY_METRIC"
    assert target_intent("PROJECT", "PROJECT_OWNERSHIP") == "VERIFY_OWNERSHIP"
    assert target_intent("PROJECT", "PROJECT_GOAL") == "VERIFY_IMPLEMENTATION"
    assert target_intent("PROJECT", "PROJECT_TRADEOFF_OR_FAILURE") == "VERIFY_TRADEOFF"
    assert target_intent("KNOWLEDGE", "KNOWLEDGE_BOUNDARY") == "VERIFY_BOUNDARY"
    assert target_intent("SYSTEM_DESIGN", "SYSTEM_RELIABILITY") == "VERIFY_FAILURE"
    assert target_intent("SYSTEM_DESIGN", "SYSTEM_TRADEOFF") == "VERIFY_TRADEOFF"


def test_planner_exit_criteria_matches_canonical_labels():
    """Planner 的 exit criteria 必须与 canonical label 完全一致（单一来源）。"""
    from app.modules.interview.topic_registry import TopicDef

    for question_type in ("PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"):
        topic_def = TopicDef(
            topic_key="async_task_pipeline",
            label="异步任务流水线",
            pack="default",
            skill_key="python",
            description="实现异步任务队列",
        )
        candidate = _TopicCandidate(
            topic=topic_def,
            question_type=question_type,
            evidence="",
            source_type="mixed",
            weight=1.0,
        )
        criteria = InterviewPlanService._exit_criteria(candidate)
        expected = [t.label for t in COVERAGE_TARGETS_BY_QUESTION_TYPE[question_type]]
        assert criteria == expected, f"{question_type} 的 exit criteria 与 canonical labels 不一致"


# ---------------------------------------------------------------------------
# B. LLM coverage validation
# ---------------------------------------------------------------------------


def _full_llm_coverage(question_type: str, answer: str, **overrides) -> list[LLMCoverageAssessment]:
    """构造「每个 target 一条真实 quote」的 coverage 输出。"""
    from app.modules.interview.topic_state.models import coverage_targets_for

    sentence = answer.split("。")[0] + "。"
    result: list[LLMCoverageAssessment] = []
    for definition in coverage_targets_for(question_type):
        status = overrides.get(definition.key, "NOT_COVERED")
        result.append(
            LLMCoverageAssessment(
                target_key=definition.key,
                status=status,
                evidence_quotes=[sentence] if status in ("PARTIAL", "COVERED") else [],
            )
        )
    return result


async def test_coverage_valid_quote_is_kept(monkeypatch):
    quote = "这个异步任务队列是我负责设计和落地的"
    coverage = [
        LLMCoverageAssessment(target_key="PROJECT_OWNERSHIP", status="COVERED", evidence_quotes=[quote]),
        *[
            LLMCoverageAssessment(target_key=key, status="NOT_COVERED")
            for key in ("PROJECT_GOAL", "PROJECT_RESULT_VALIDATION", "PROJECT_TRADEOFF_OR_FAILURE")
        ],
    ]
    evidence = {
        "authenticity": [quote],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result({"authenticity": 80, "technical_depth": 80, "communication_structure": 78}, evidence, coverage)
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    kept = {item.target_key: item for item in outcome.evaluation.coverage_assessments}
    assert kept["PROJECT_OWNERSHIP"].status == "COVERED"
    assert kept["PROJECT_OWNERSHIP"].evidence_quotes == [quote]


async def test_coverage_fake_quote_degrades_positive_status(monkeypatch):
    """COVERED + 编造 quote → 保守降级 NOT_COVERED。"""
    fake = "我们用了 Kafka 做消息总线以保证顺序性"
    coverage = [
        LLMCoverageAssessment(target_key="PROJECT_OWNERSHIP", status="COVERED", evidence_quotes=[fake]),
        *[
            LLMCoverageAssessment(target_key=key, status="NOT_COVERED")
            for key in ("PROJECT_GOAL", "PROJECT_RESULT_VALIDATION", "PROJECT_TRADEOFF_OR_FAILURE")
        ],
    ]
    evidence = {
        "authenticity": ["这个异步任务队列是我负责设计和落地的"],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result({"authenticity": 80, "technical_depth": 80, "communication_structure": 78}, evidence, coverage)
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    kept = {item.target_key: item for item in outcome.evaluation.coverage_assessments}
    assert kept["PROJECT_OWNERSHIP"].status == COVERAGE_STATUS_NOT_COVERED, "编造 quote 不得保住 COVERED"
    assert kept["PROJECT_OWNERSHIP"].evidence_quotes == []


async def test_coverage_unknown_key_is_dropped_without_breaking_score(monkeypatch):
    coverage = [
        LLMCoverageAssessment(target_key="KNOWLEDGE_BOUNDARY", status="COVERED", evidence_quotes=["随便什么"]),
        LLMCoverageAssessment(target_key="SYSTEM_RELIABILITY", status="COVERED", evidence_quotes=["随便什么"]),
        LLMCoverageAssessment(target_key="MADE_UP_TARGET", status="COVERED", evidence_quotes=["随便什么"]),
    ]
    evidence = {
        "authenticity": ["这个异步任务队列是我负责设计和落地的"],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result({"authenticity": 80, "technical_depth": 80, "communication_structure": 78}, evidence, coverage)
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot("PROJECT"), STRONG_ANSWER)

    keys = {item.target_key for item in outcome.evaluation.coverage_assessments}
    assert keys == set(initial_coverage_points("PROJECT")), "unknown key 必须被丢弃，canonical 集合保持完整"


async def test_coverage_duplicate_key_takes_first(monkeypatch):
    quote = "这个异步任务队列是我负责设计和落地的"
    coverage = [
        LLMCoverageAssessment(target_key="PROJECT_OWNERSHIP", status="COVERED", evidence_quotes=[quote]),
        LLMCoverageAssessment(target_key="PROJECT_OWNERSHIP", status="NOT_COVERED"),
    ]
    evidence = {
        "authenticity": [quote],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result({"authenticity": 80, "technical_depth": 80, "communication_structure": 78}, evidence, coverage)
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    ownership = [item for item in outcome.evaluation.coverage_assessments if item.target_key == "PROJECT_OWNERSHIP"]
    assert len(ownership) == 1, "duplicate 只保留一条"
    assert ownership[0].status == "COVERED", "取第一条"


async def test_coverage_missing_key_is_not_covered(monkeypatch):
    """LLM 完全没输出 coverage → 每个 canonical target 都是 NOT_COVERED。"""
    evidence = {
        "authenticity": ["这个异步任务队列是我负责设计和落地的"],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result({"authenticity": 80, "technical_depth": 80, "communication_structure": 78}, evidence, [])
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    assert {item.target_key: item.status for item in outcome.evaluation.coverage_assessments} == {
        key: COVERAGE_STATUS_NOT_COVERED for key in initial_coverage_points("PROJECT")
    }


# ---------------------------------------------------------------------------
# C. Score / coverage failure isolation（PR3 §12）
# ---------------------------------------------------------------------------


async def test_malformed_coverage_never_breaks_score(monkeypatch):
    """dimension 全部合法 + coverage 恶意构造 → score 仍为 HYBRID_LLM。"""
    bad_coverage = [
        LLMCoverageAssessment(target_key="PROJECT_OWNERSHIP", status="COVERED", evidence_quotes=["编造的话"]),
        LLMCoverageAssessment(target_key="NOT_A_TARGET", status="WEIRD_STATUS", evidence_quotes=[]),
    ]
    evidence = {
        "authenticity": ["这个异步任务队列是我负责设计和落地的"],
        "technical_depth": ["生产端用 XADD 写入 Redis Streams"],
        "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
    }
    llm = _llm_result(
        {"authenticity": 82, "technical_depth": 84, "communication_structure": 80}, evidence, bad_coverage
    )
    service, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    # score 不受 coverage 污染
    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    assert outcome.evaluation.ability_score >= 80
    assert outcome.evaluation.confidence >= 0.8
    # coverage 被保守处理
    statuses = {item.target_key: item.status for item in outcome.evaluation.coverage_assessments}
    assert statuses["PROJECT_OWNERSHIP"] == COVERAGE_STATUS_NOT_COVERED, "编造 quote → 降级"


# ---------------------------------------------------------------------------
# D. Coverage monotonic
# ---------------------------------------------------------------------------


def test_merge_coverage_status_is_monotonic():
    assert merge_coverage_status("NOT_COVERED", "PARTIAL") == "PARTIAL"
    assert merge_coverage_status("NOT_COVERED", "COVERED") == "COVERED"
    assert merge_coverage_status("PARTIAL", "COVERED") == "COVERED"
    # 禁止降级
    assert merge_coverage_status("COVERED", "PARTIAL") == "COVERED"
    assert merge_coverage_status("COVERED", "NOT_COVERED") == "COVERED"
    assert merge_coverage_status("PARTIAL", "NOT_COVERED") == "PARTIAL"


async def test_tracker_update_never_downgrades():
    tracker = TopicCoverageTracker()
    topic = _topic()
    covered = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(
            coverage=[_assessment("PROJECT_OWNERSHIP", "COVERED", ["这个异步任务队列是我负责设计和落地的"])]
        ),
    )
    assert covered.points["PROJECT_OWNERSHIP"].status == "COVERED"

    # 下一轮 LLM 说 NOT_COVERED —— 不允许降级
    after = tracker.update(
        topic=topic,
        current_state=covered,
        turn_id=2,
        answer="这轮没讲职责。",
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "NOT_COVERED")]),
    )
    assert after.points["PROJECT_OWNERSHIP"].status == "COVERED"


# ---------------------------------------------------------------------------
# E. Evidence accumulation
# ---------------------------------------------------------------------------


async def test_evidence_accumulation_dedup_and_cap():
    tracker = TopicCoverageTracker()
    topic = _topic()
    quote_a = "这个异步任务队列是我负责设计和落地的"
    quote_b = "生产端用 XADD 写入 Redis Streams"
    quote_c = "超时任务用 XPENDING 捞出来重新投递"
    quote_d = "上线后 P99 从 800ms 降到 300ms"

    state = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "COVERED", [quote_a, quote_a, quote_b])]),
    )
    # 重复 quote 只保存一次
    assert state.points["PROJECT_OWNERSHIP"].evidence_quotes == [quote_a, quote_b]
    assert state.points["PROJECT_OWNERSHIP"].source_turn_ids == [1]

    state = tracker.update(
        topic=topic,
        current_state=state,
        turn_id=2,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "COVERED", [quote_a, quote_c, quote_d])]),
    )
    point = state.points["PROJECT_OWNERSHIP"]
    # 最多 3 条 unique quote；quote_a 不重复保存
    assert point.evidence_quotes == [quote_a, quote_b, quote_c]
    assert point.source_turn_ids == [1, 2]


def test_coverage_ratio_formula():
    points = initial_coverage_points("PROJECT")
    points["PROJECT_GOAL"].status = "COVERED"
    points["PROJECT_OWNERSHIP"].status = "COVERED"
    points["PROJECT_RESULT_VALIDATION"].status = "PARTIAL"
    points["PROJECT_TRADEOFF_OR_FAILURE"].status = "NOT_COVERED"
    assert coverage_ratio(points) == 0.625  # (1 + 1 + 0.5 + 0) / 4


def test_complete_is_strict_all_covered():
    points = initial_coverage_points("PROJECT")
    for key in list(points)[:-1]:
        points[key].status = "COVERED"
    assert coverage_ratio(points) == 0.75
    assert is_complete(points) is False, "ratio 高也不允许冒充 complete"
    points[list(points)[-1]].status = "COVERED"
    assert is_complete(points) is True


# ---------------------------------------------------------------------------
# F. Heuristic fallback coverage
# ---------------------------------------------------------------------------


async def test_heuristic_fallback_coverage_caps_at_partial():
    tracker = TopicCoverageTracker()
    topic = _topic()

    state = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer="我负责设计并主导落地，指标提升明显，也做了取舍和异常兜底。",
        evaluation=_evaluation(method="HEURISTIC_FALLBACK"),
    )
    statuses = {key: point.status for key, point in state.points.items()}
    assert all(status in (COVERAGE_STATUS_NOT_COVERED, COVERAGE_STATUS_PARTIAL) for status in statuses.values())
    assert COVERAGE_STATUS_PARTIAL in statuses.values(), "关键词命中应至少推到 PARTIAL"
    assert COVERAGE_STATUS_COVERED not in statuses.values(), "heuristic fallback 绝不允许 COVERED"


async def test_heuristic_fallback_cannot_upgrade_partial_to_covered():
    tracker = TopicCoverageTracker()
    topic = _topic()
    partial_state = _coverage("PROJECT", PROJECT_OWNERSHIP=COVERAGE_STATUS_PARTIAL)

    state = tracker.update(
        topic=topic,
        current_state=partial_state,
        turn_id=2,
        answer="我负责设计并主导落地。",
        evaluation=_evaluation(method="HEURISTIC_FALLBACK"),
    )
    assert state.points["PROJECT_OWNERSHIP"].status == COVERAGE_STATUS_PARTIAL, "fallback 最多 PARTIAL"


async def test_rule_only_empty_answer_does_not_update_coverage():
    tracker = TopicCoverageTracker()
    topic = _topic()
    prior = _coverage("PROJECT", PROJECT_GOAL=COVERAGE_STATUS_PARTIAL)

    state = tracker.update(
        topic=topic,
        current_state=prior,
        turn_id=3,
        answer="",
        evaluation=_evaluation(method="RULE_ONLY"),
    )
    assert state.points["PROJECT_GOAL"].status == COVERAGE_STATUS_PARTIAL, "RULE_ONLY 不更新 coverage"
    assert state.points["PROJECT_OWNERSHIP"].status == COVERAGE_STATUS_NOT_COVERED


# ---------------------------------------------------------------------------
# G. next_target
# ---------------------------------------------------------------------------


def test_next_target_priority():
    # 全 NOT → 第一个 NOT_COVERED（canonical priority 1）
    state = _coverage("PROJECT")
    assert state.next_target_key == "PROJECT_GOAL"

    # GOAL COVERED → 优先第一个 NOT（OWNERSHIP），而不是 PARTIAL
    state = _coverage(
        "PROJECT",
        PROJECT_GOAL=COVERAGE_STATUS_COVERED,
        PROJECT_RESULT_VALIDATION=COVERAGE_STATUS_PARTIAL,
    )
    assert state.next_target_key == "PROJECT_OWNERSHIP"

    # 没有 NOT → 第一个 PARTIAL
    state = _coverage(
        "PROJECT",
        PROJECT_GOAL=COVERAGE_STATUS_COVERED,
        PROJECT_OWNERSHIP=COVERAGE_STATUS_COVERED,
        PROJECT_RESULT_VALIDATION=COVERAGE_STATUS_PARTIAL,
        PROJECT_TRADEOFF_OR_FAILURE=COVERAGE_STATUS_COVERED,
    )
    assert state.next_target_key == "PROJECT_RESULT_VALIDATION"

    # 全部 COVERED → None
    assert _all_covered().next_target_key is None
    assert _all_covered().next_target_label is None


def test_select_next_target_matches_state():
    points = initial_coverage_points("KNOWLEDGE")
    points["KNOWLEDGE_DEFINITION"].status = "COVERED"
    target = select_next_target(points, "KNOWLEDGE")
    assert target is not None and target.key == "KNOWLEDGE_MECHANISM"


# ---------------------------------------------------------------------------
# H. Adaptive STRICT
# ---------------------------------------------------------------------------


def _strict_decide(topic, evaluation, answered, *, has_next_topic=True, coverage):
    state = topic_coverage_tracker.build_state(topic=topic, answered_turns=answered, coverage=coverage)
    return StrictInterviewPolicy().decide(
        topic=topic,
        turn=_turn(1, "回答", score=evaluation.ability_score),
        evaluation=evaluation,
        answered_turns_after_current=answered,
        has_next_topic=has_next_topic,
        topic_state=state,
    )


def test_strict_early_exit_on_complete_coverage_and_good_score():
    """MAIN 88 分 + coverage complete → NEXT_TOPIC，0 次追问。"""
    topic = _topic()
    decision = _strict_decide(topic, _evaluation(88), [_turn(1, STRONG_ANSWER, score=88)], coverage=_all_covered())
    assert decision.action == "NEXT_TOPIC"
    assert decision.follow_up_intent is None


def test_strict_early_exit_end_when_no_next_topic():
    topic = _topic()
    decision = _strict_decide(
        topic, _evaluation(88), [_turn(1, STRONG_ANSWER, score=88)], has_next_topic=False, coverage=_all_covered()
    )
    assert decision.action == "END"


def test_strict_follows_up_when_coverage_incomplete():
    """MAIN 90 分但 coverage 未完整 → 仍然 FOLLOW_UP，target 指向未覆盖 criterion。"""
    topic = _topic()
    coverage = _coverage(
        "PROJECT",
        PROJECT_GOAL=COVERAGE_STATUS_COVERED,
        PROJECT_OWNERSHIP=COVERAGE_STATUS_COVERED,
        PROJECT_TRADEOFF_OR_FAILURE=COVERAGE_STATUS_COVERED,
    )
    decision = _strict_decide(topic, _evaluation(90), [_turn(1, STRONG_ANSWER, score=90)], coverage=coverage)
    assert decision.action == "FOLLOW_UP"
    assert decision.target_coverage_key == "PROJECT_RESULT_VALIDATION"
    assert decision.follow_up_intent == "VERIFY_METRIC"


def test_strict_follows_up_when_complete_but_low_score():
    """coverage complete + 55 分 → 质量不足，继续 FOLLOW_UP（gap 驱动 intent）。"""
    topic = _topic()
    decision = _strict_decide(
        topic, _evaluation(55, gaps=["缺少结果指标"]), [_turn(1, "回答", score=55)], coverage=_all_covered()
    )
    assert decision.action == "FOLLOW_UP"
    assert decision.target_coverage_key is None, "coverage 已完整，没有 target"
    assert decision.follow_up_intent


def test_strict_hard_stops_at_max_turns():
    """达到 max_turns → 无论 coverage / score 都 NEXT_TOPIC。"""
    topic = _topic()  # max_turns = 3
    answered = [
        _turn(1, "回答 1", score=40),
        _turn(2, "回答 2", score=45, turn_type=TurnType.FOLLOW_UP.value),
        _turn(3, "回答 3", score=50, turn_type=TurnType.FOLLOW_UP.value),
    ]
    decision = _strict_decide(
        topic,
        _evaluation(50),
        answered,
        coverage=_coverage("PROJECT"),  # 全部 NOT_COVERED
    )
    assert decision.action == "NEXT_TOPIC"


# ---------------------------------------------------------------------------
# I. Adaptive COACH
# ---------------------------------------------------------------------------


def _coach_decide(topic, evaluation, answered, *, turn_type=TurnType.MAIN.value, has_next_topic=True, coverage=None):
    state = topic_coverage_tracker.build_state(
        topic=topic, answered_turns=answered, coverage=coverage or topic_coverage_tracker.initial_state("PROJECT")
    )
    return CoachInterviewPolicy().decide(
        topic=topic,
        turn=_turn(1, "回答", turn_type=turn_type, score=evaluation.ability_score),
        evaluation=evaluation,
        answered_turns_after_current=answered,
        has_next_topic=has_next_topic,
        coach_hint={"message": "hint"},
        topic_state=state,
    )


def test_coach_main_high_score_and_complete_moves_on():
    topic = _topic()
    decision = _coach_decide(topic, _evaluation(90), [_turn(1, STRONG_ANSWER, score=90)], coverage=_all_covered())
    assert decision.action == "NEXT_TOPIC"


def test_coach_main_high_score_but_incomplete_retries():
    """90 分但 RESULT_VALIDATION 未覆盖 → 仍然要重答补齐。"""
    topic = _topic()
    coverage = _coverage(
        "PROJECT",
        PROJECT_GOAL=COVERAGE_STATUS_COVERED,
        PROJECT_OWNERSHIP=COVERAGE_STATUS_COVERED,
        PROJECT_TRADEOFF_OR_FAILURE=COVERAGE_STATUS_COVERED,
    )
    decision = _coach_decide(topic, _evaluation(90), [_turn(1, STRONG_ANSWER, score=90)], coverage=coverage)
    assert decision.action == "COACH_RETRY"
    assert decision.target_coverage_key == "PROJECT_RESULT_VALIDATION"
    assert decision.next_question == topic.main_question


def test_coach_retry_complete_with_75_moves_on():
    topic = _topic()
    answered = [_turn(1, "初版", score=60), _turn(2, "重答", score=78, turn_type=TurnType.COACH_RETRY.value)]
    decision = _coach_decide(
        topic,
        _evaluation(78),
        answered,
        turn_type=TurnType.COACH_RETRY.value,
        coverage=_all_covered(),
    )
    assert decision.action == "NEXT_TOPIC"


def test_coach_retry_complete_with_improvement_10_moves_on():
    """78 分不够 75 门槛但提升 >= 10 → 过关。"""
    topic = _topic()
    answered = [_turn(1, "初版", score=68), _turn(2, "重答", score=78, turn_type=TurnType.COACH_RETRY.value)]
    decision = _coach_decide(
        topic,
        _evaluation(78),
        answered,
        turn_type=TurnType.COACH_RETRY.value,
        coverage=_all_covered(),
    )
    assert decision.action == "NEXT_TOPIC"


def test_coach_retry_incomplete_keeps_retrying():
    topic = _topic()
    answered = [_turn(1, "初版", score=60), _turn(2, "重答", score=78, turn_type=TurnType.COACH_RETRY.value)]
    decision = _coach_decide(
        topic,
        _evaluation(78),
        answered,
        turn_type=TurnType.COACH_RETRY.value,
        coverage=_coverage("PROJECT"),  # 全 NOT_COVERED
    )
    assert decision.action == "COACH_RETRY"


def test_coach_hard_stops_at_max_turns():
    topic = _topic()  # max_turns = 3
    answered = [
        _turn(1, "初版", score=50),
        _turn(2, "重答 1", score=55, turn_type=TurnType.COACH_RETRY.value),
        _turn(3, "重答 2", score=58, turn_type=TurnType.COACH_RETRY.value),
    ]
    decision = _coach_decide(
        topic,
        _evaluation(58),
        answered,
        turn_type=TurnType.COACH_RETRY.value,
        coverage=_coverage("PROJECT"),
    )
    assert decision.action == "NEXT_TOPIC", "max_turns 是 hard limit"


# ---------------------------------------------------------------------------
# J. Intent / fallback question 对齐
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent,keywords",
    [
        ("VERIFY_METRIC", ("指标", "baseline")),
        ("VERIFY_BOUNDARY", ("边界",)),
        ("VERIFY_FAILURE", ("失败",)),
        ("VERIFY_TRADEOFF", ("取舍",)),
        ("VERIFY_OWNERSHIP", ("你", "亲手")),
        ("VERIFY_IMPLEMENTATION", ("闭环",)),
    ],
)
def test_fallback_question_aligns_with_intent(intent, keywords):
    question = StrictInterviewPolicy._followup_question(
        _topic(), _evaluation(60), followup_number=1, follow_up_intent=intent, target_gap="随便"
    )
    assert question, f"{intent} 必须有对应模板"
    assert any(k in question for k in keywords), f"{intent} 的 fallback 必须围绕该意图：{question}"


def test_fallback_without_intent_keeps_legacy_template():
    """没有 intent 的调用（旧路径）仍按题型生成，不抛异常。"""
    question = StrictInterviewPolicy._followup_question(_topic("PROJECT"), _evaluation(60), followup_number=1)
    assert question
    assert "最小闭环" in question or "指标" in question


def test_metric_fallback_not_implementation_chain():
    """Policy=VERIFY_METRIC + Realizer 超时 → fallback 仍问指标，不回实现链路。"""
    question = StrictInterviewPolicy._followup_question(
        _topic("PROJECT"), _evaluation(60), followup_number=2, follow_up_intent="VERIFY_METRIC"
    )
    assert "指标" in question
    assert "最小闭环" not in question and "请求或任务进来" not in question


# ---------------------------------------------------------------------------
# K. Context（coverage 进入 context + fingerprint）
# ---------------------------------------------------------------------------


def test_context_reflects_coverage_state():
    builder = InterviewContextBuilder()
    coverage = _coverage(
        "PROJECT",
        PROJECT_GOAL=COVERAGE_STATUS_COVERED,
        PROJECT_OWNERSHIP=COVERAGE_STATUS_PARTIAL,
    )
    context = builder.build(
        session_id="s",
        interview_mode="STRICT",
        topic=_topic(),
        current_question="Q",
        current_answer="A",
        answered_turns=[],
        evaluation=None,
        coverage_state=coverage,
        target_coverage_key="PROJECT_RESULT_VALIDATION",
    )
    assert context.covered_points == ["能说清项目目标"]
    assert context.partial_points == ["能说明个人贡献"]
    # unresolved = PARTIAL + NOT_COVERED
    assert set(context.unresolved_gaps) == {"能说明个人贡献", "能给出结果或验证方式", "能补充一个技术取舍或异常处理"}
    assert context.target_coverage_key == "PROJECT_RESULT_VALIDATION"
    assert context.target_coverage_label == "能给出结果或验证方式"


def test_coverage_state_changes_singleflight_fingerprint():
    """不同 coverage state 不得共享 SingleFlight result。"""
    builder = InterviewContextBuilder()
    base = dict(
        session_id="s",
        interview_mode="STRICT",
        topic=_topic(),
        current_question="Q",
        current_answer="A",
        answered_turns=[],
        evaluation=None,
    )
    ctx_partial = builder.build(coverage_state=_coverage("PROJECT", PROJECT_GOAL=COVERAGE_STATUS_PARTIAL), **base)
    ctx_covered = builder.build(coverage_state=_coverage("PROJECT", PROJECT_GOAL=COVERAGE_STATUS_COVERED), **base)
    assert ctx_partial.fingerprint_parts() != ctx_covered.fingerprint_parts()

    ctx_targeted = builder.build(coverage_state=_coverage("PROJECT"), target_coverage_key="PROJECT_OWNERSHIP", **base)
    ctx_untargeted = builder.build(coverage_state=_coverage("PROJECT"), **base)
    assert ctx_targeted.fingerprint_parts() != ctx_untargeted.fingerprint_parts(), "target 也必须进指纹"


def test_context_without_coverage_keeps_legacy_behaviour():
    """没有 coverage 的调用方（PR1/PR2 路径）行为不变。"""
    builder = InterviewContextBuilder()
    context = builder.build(
        session_id="s",
        interview_mode="STRICT",
        topic=_topic(),
        current_question="Q",
        current_answer="A",
        answered_turns=[],
        evaluation=_evaluation(70),
    )
    assert context.partial_points == []
    assert context.target_coverage_key is None
    assert context.covered_points == [], "无 coverage 且无 strengths 时 covered 为空"


# ---------------------------------------------------------------------------
# L. Persistence（roundtrip / NULL / bad JSON）
# ---------------------------------------------------------------------------


def test_coverage_state_roundtrip():
    tracker = TopicCoverageTracker()
    state = _coverage("PROJECT", PROJECT_GOAL=COVERAGE_STATUS_COVERED, PROJECT_OWNERSHIP=COVERAGE_STATUS_PARTIAL)
    dumped = tracker.dump_state(state)
    parsed = tracker.parse_state(dumped, "PROJECT")
    assert parsed.points["PROJECT_GOAL"].status == "COVERED"
    assert parsed.points["PROJECT_OWNERSHIP"].status == "PARTIAL"
    assert parsed.coverage_ratio == state.coverage_ratio
    assert parsed.next_target_key == state.next_target_key


def test_parse_state_null_returns_initial():
    parsed = TopicCoverageTracker.parse_state(None, "SYSTEM_DESIGN")
    assert parsed.coverage_ratio == 0.0
    assert set(parsed.points) == set(initial_coverage_points("SYSTEM_DESIGN"))


def test_parse_state_bad_json_returns_initial():
    for bad in ("not json {", '""', "[1,2,3]", '{"version": "weird", "points": "not-a-dict"}'):
        parsed = TopicCoverageTracker.parse_state(bad, "PROJECT")
        assert parsed.coverage_ratio == 0.0
        assert all(point.status == COVERAGE_STATUS_NOT_COVERED for point in parsed.points.values())


def test_parse_state_missing_targets_is_normalized():
    """持久化数据缺 target（题型定义升级过）→ 自动补齐成完整 canonical 形态。"""
    partial = TopicCoverageStateDTO(
        points={"PROJECT_GOAL": _coverage("PROJECT").points["PROJECT_GOAL"].model_copy(update={"status": "COVERED"})}
    )
    parsed = TopicCoverageTracker.parse_state(partial.model_dump_json(), "PROJECT")
    assert set(parsed.points) == set(initial_coverage_points("PROJECT"))
    assert parsed.points["PROJECT_GOAL"].status == "COVERED"
    assert parsed.next_target_key == "PROJECT_OWNERSHIP"


# ---------------------------------------------------------------------------
# O. Evaluator version
# ---------------------------------------------------------------------------


def test_evaluator_version_is_current():
    """版本号必须随 evaluator 语义变更 bump（PR5 → v4）。"""
    assert EVALUATOR_VERSION == "hybrid-evaluator-v4"


# ---------------------------------------------------------------------------
# P0-1：coverage structural malformed 与 dimensions 严格校验的失败域隔离
# ---------------------------------------------------------------------------


def _raw_valid_dimensions() -> list[dict]:
    quote = "这个异步任务队列是我负责设计和落地的"
    return [
        {"dimension": "authenticity", "score": 80, "assessment": "职责清晰", "evidence_quotes": [quote], "gaps": []},
        {
            "dimension": "technical_depth",
            "score": 82,
            "assessment": "实现具体",
            "evidence_quotes": ["生产端用 XADD 写入 Redis Streams"],
            "gaps": [],
        },
        {
            "dimension": "communication_structure",
            "score": 78,
            "assessment": "结构清楚",
            "evidence_quotes": ["超时任务用 XPENDING 捞出来重新投递"],
            "gaps": [],
        },
    ]


def test_raw_coverage_string_does_not_break_parse():
    """Case 1：coverage 是字符串 → LLMEvaluationResult 仍可解析，dimensions 保留。"""
    raw = {"dimensions": _raw_valid_dimensions(), "risks": [], "coverage": "broken"}
    parsed = LLMEvaluationResult.model_validate(raw)
    assert len(parsed.dimensions) == 3
    assert parsed.coverage == []


def test_raw_coverage_malformed_items_do_not_break_parse():
    """Case 2：coverage 里混入垃圾元素 / 坏 schema → 保守忽略，dimensions 保留。"""
    raw = {
        "dimensions": _raw_valid_dimensions(),
        "risks": [],
        "coverage": [
            "garbage",
            {"target_key": "PROJECT_GOAL", "status": {"bad": True}, "evidence_quotes": "bad"},
            123,
        ],
    }
    parsed = LLMEvaluationResult.model_validate(raw)
    assert len(parsed.dimensions) == 3
    assert parsed.coverage == []


def test_raw_coverage_mixed_valid_and_invalid_keeps_valid_only():
    raw = {
        "dimensions": _raw_valid_dimensions(),
        "risks": [],
        "coverage": [
            {
                "target_key": "PROJECT_OWNERSHIP",
                "status": "COVERED",
                "evidence_quotes": ["这个异步任务队列是我负责设计和落地的"],
            },
            {"target_key": "PROJECT_GOAL", "status": "COVERED", "evidence_quotes": "bad-type"},
            "junk",
        ],
    }
    parsed = LLMEvaluationResult.model_validate(raw)
    assert [item.target_key for item in parsed.coverage] == ["PROJECT_OWNERSHIP"]


def test_dimensions_remain_strict_under_malformed_coverage():
    """dimensions 仍严格：缺 dimension 仍会抛错，不受 coverage permissive 影响。"""
    raw = {
        "dimensions": [{"score": 80, "assessment": "a"}],  # 缺 dimension 字段
        "risks": [],
        "coverage": "broken",
    }
    with pytest.raises(Exception):
        LLMEvaluationResult.model_validate(raw)


async def test_evaluator_keeps_hybrid_score_on_raw_malformed_coverage(monkeypatch):
    """raw malformed coverage → evaluator 仍 HYBRID_LLM，不回 HEURISTIC_FALLBACK。"""
    raw = {"dimensions": _raw_valid_dimensions(), "risks": [], "coverage": "broken"}
    parsed = LLMEvaluationResult.model_validate(raw)
    service, _ = _service(monkeypatch, parsed)

    outcome = await service.evaluate(_snapshot(), STRONG_ANSWER)

    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    assert outcome.evaluation.ability_score >= 78, "score 使用正常 semantic 加权结果"


# ---------------------------------------------------------------------------
# P0-2：target-specific fallback（canonical target 与 intent 不是 1:1）
# ---------------------------------------------------------------------------


def _fallback(question_type: str, target_key: str, intent: str) -> str:
    return StrictInterviewPolicy._followup_question(
        _topic(question_type),
        _evaluation(60),
        followup_number=1,
        follow_up_intent=intent,
        target_coverage_key=target_key,
    )


def test_fallback_project_goal_asks_about_goal_not_minimal_chain():
    question = _fallback("PROJECT", "PROJECT_GOAL", "VERIFY_IMPLEMENTATION")
    assert "要解决什么问题" in question or "目标" in question
    assert "最小闭环" not in question, "PROJECT_GOAL 不能退回技术最小链路"


def test_fallback_knowledge_definition_asks_definition_not_mechanism():
    question = _fallback("KNOWLEDGE", "KNOWLEDGE_DEFINITION", "VERIFY_IMPLEMENTATION")
    assert "是什么" in question and "界定" in question
    assert "机制" not in question, "KNOWLEDGE_DEFINITION 不能问核心机制"


def test_fallback_knowledge_mechanism_asks_mechanism():
    question = _fallback("KNOWLEDGE", "KNOWLEDGE_MECHANISM", "VERIFY_IMPLEMENTATION")
    assert "机制" in question or "流程" in question


def test_fallback_knowledge_scenario_asks_scenario_not_mechanism():
    question = _fallback("KNOWLEDGE", "KNOWLEDGE_SCENARIO", "VERIFY_IMPLEMENTATION")
    assert "场景" in question and "什么时候" in question
    assert "核心机制" not in question, "KNOWLEDGE_SCENARIO 不能问核心机制"


def test_fallback_system_data_flow_asks_flow():
    question = _fallback("SYSTEM_DESIGN", "SYSTEM_DATA_FLOW", "VERIFY_IMPLEMENTATION")
    assert "请求" in question or "数据" in question


def test_fallback_system_components_asks_modules():
    question = _fallback("SYSTEM_DESIGN", "SYSTEM_COMPONENTS", "VERIFY_IMPLEMENTATION")
    assert "模块" in question or "组件" in question


def test_fallback_project_result_validation_still_uses_metric_intent():
    """PROJECT_RESULT_VALIDATION 没有专属 target 模板 → 复用 VERIFY_METRIC。"""
    question = _fallback("PROJECT", "PROJECT_RESULT_VALIDATION", "VERIFY_METRIC")
    assert "指标" in question and "baseline" in question


# ---------------------------------------------------------------------------
# P1：coverage evidence / source_turn_ids provenance
# ---------------------------------------------------------------------------


async def test_provenance_not_covered_turn_does_not_add_turn_id():
    """turn1 COVERED + valid quote；turn2 NOT_COVERED → source_turn_ids 仍 [1]，quote 不变。"""
    tracker = TopicCoverageTracker()
    topic = _topic()
    quote = "这个异步任务队列是我负责设计和落地的"
    s1 = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "COVERED", [quote])]),
    )
    assert s1.points["PROJECT_OWNERSHIP"].source_turn_ids == [1]

    s2 = tracker.update(
        topic=topic,
        current_state=s1,
        turn_id=2,
        answer="这轮完全没讲职责，只讲了别的。",
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "NOT_COVERED")]),
    )
    point = s2.points["PROJECT_OWNERSHIP"]
    assert point.status == "COVERED", "状态仍 COVERED（单调）"
    assert point.source_turn_ids == [1], "无贡献轮次不得记 source_turn_id"
    assert point.evidence_quotes == [quote], "无贡献轮次不得追加 quote"


async def test_provenance_not_covered_with_quote_is_ignored():
    """NOT_COVERED + 附带 quote → quote 与 source_turn_id 都不保存。"""
    tracker = TopicCoverageTracker()
    topic = _topic()
    state = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(
            coverage=[_assessment("PROJECT_OWNERSHIP", "NOT_COVERED", ["这个异步任务队列是我负责设计和落地的"])]
        ),
    )
    point = state.points["PROJECT_OWNERSHIP"]
    assert point.status == "NOT_COVERED"
    assert point.evidence_quotes == []
    assert point.source_turn_ids == []


async def test_provenance_covered_then_partial_with_new_quote_accumulates():
    """COVERED 已成立，下一轮 PARTIAL + 新 quote → 允许新 quote/turn_id 累积，状态仍 COVERED。"""
    tracker = TopicCoverageTracker()
    topic = _topic()
    q1 = "这个异步任务队列是我负责设计和落地的"
    q2 = "生产端用 XADD 写入 Redis Streams"
    s1 = tracker.update(
        topic=topic,
        current_state=tracker.initial_state("PROJECT"),
        turn_id=1,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "COVERED", [q1])]),
    )
    s2 = tracker.update(
        topic=topic,
        current_state=s1,
        turn_id=2,
        answer=STRONG_ANSWER,
        evaluation=_evaluation(coverage=[_assessment("PROJECT_OWNERSHIP", "PARTIAL", [q2])]),
    )
    point = s2.points["PROJECT_OWNERSHIP"]
    assert point.status == "COVERED"
    assert point.source_turn_ids == [1, 2]
    assert point.evidence_quotes == [q1, q2]


# ---------------------------------------------------------------------------
# P1 semantic cleanup：KNOWLEDGE coverage 不得混入 correctness 词
# ---------------------------------------------------------------------------


def test_knowledge_coverage_definitions_avoid_correctness_wording():
    """coverage 只判断「谈到没有」，不判断对错 —— 禁止把「正确/准确/错误」作为覆盖判定词。

    「不判断正误」这类显式否定是允许的（正是解耦信号），
    所以 banned 只锁定「把正确性当判定要求」的正向词，不含否定句式。
    """
    banned = ("正确", "准确", "错误", "对不对")
    for target in COVERAGE_TARGETS_BY_QUESTION_TYPE["KNOWLEDGE"]:
        assert not any(word in target.description for word in banned), f"{target.key} description 混入 correctness 词"
        assert not any(word in target.label for word in banned), f"{target.key} label 混入 correctness 词"


def test_knowledge_definition_label_renamed():
    from app.modules.interview.topic_state.models import coverage_target_map

    definition = coverage_target_map("KNOWLEDGE")["KNOWLEDGE_DEFINITION"]
    assert definition.label == "能给出概念定义"
    assert "正误" in definition.description and "只判断是否覆盖" in definition.description
