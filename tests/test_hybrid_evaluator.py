"""Hybrid Answer Evaluator 单元测试（不调用真实 LLM）。

覆盖：
- A. Rule Guard（empty / very short / generic / off-topic）
- B. Semantic scoring（三种 question_type 的 active dimension 与权重）
- C. Evidence validation（原文校验、丢弃编造 quote、高分证据不足 cap、0 证据 fallback）
- D. Confidence tiers（含 KNOWLEDGE cap）
- E. Provider 传递 + SingleFlight key
- F. Timeout / exception / 非法结构化输出 / dimension 缺失多余重复
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.common.single_flight import build_single_flight_key
from app.modules.interview import evaluation as evaluation_module
from app.modules.interview.dynamic_service import DynamicAnswerEvaluationService
from app.modules.interview.evaluation.hybrid_evaluator import (
    HybridAnswerEvaluationService,
    _normalize_for_evidence,
)
from app.modules.interview.evaluation.models import (
    EVALUATOR_VERSION,
    EvaluationSnapshot,
    LLMDimensionAssessment,
    LLMEvaluationResult,
    active_dimension_weights,
)
from app.modules.interview.schemas import DynamicTopicDTO, DynamicTurnDTO

STRONG_PROJECT_ANSWER = (
    "这个异步任务队列是我负责设计和落地的。生产端用 XADD 写入 Redis Streams，"
    "消费端用 Consumer Group + XREADGROUP 多实例并行消费；每个任务带唯一 message_id 做幂等，"
    "超时任务用 XPENDING 捞出来重新投递。P99 从 800ms 降到 300ms，失败率从 2% 降到 0.3%。"
)
GENERIC_ANSWER = "Redis 做缓存很好用，我们项目里很多地方都用了。缓存可以大幅提升性能，主要是把热点数据放在 Redis 里。"
OFF_TOPIC_ANSWER = "异步任务应该用多线程，Python 的 ThreadPoolExecutor 就能搞定。不需要引入 Redis 这么重的组件。"


class _StubInvoker:
    """替身 structured_output_invoker：记录 prompt / model，返回固定结构化结果。"""

    def __init__(self, payload: LLMEvaluationResult | Exception):
        self.payload = payload
        self.calls: list[dict] = []

    async def invoke(self, *, chat_model, system_prompt, user_prompt, output_model, **kwargs):
        self.calls.append(
            {
                "chat_model": chat_model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "output_model": output_model,
            }
        )
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
    def __init__(self):
        self.providers: list[str | None] = []

    def get_chat_model(self, provider=None):
        self.providers.append(provider)
        return f"model-for-{provider}"


def _topic(question_type: str = "PROJECT", topic_key: str = "async_task_pipeline") -> DynamicTopicDTO:
    return DynamicTopicDTO(
        id=1,
        topic_key=topic_key,
        topic_title="异步任务流水线",
        skill_key="python",
        question_type=question_type,
        source_type="resume",
        evidence_snippet="实现异步任务队列（Redis Streams + Consumer Group）。",
        main_question="请讲清楚 Redis Streams 异步任务队列的设计。",
        topic_order=1,
        followup_goals=["验证个人职责是否清晰", "验证指标或结果是否可证明"],
        exit_criteria=["能说清项目目标", "能说明个人贡献", "能给出结果或验证方式"],
        rubric={
            "authenticity": "个人职责是否可信",
            "technical_depth": "实现细节是否扎实",
            "communication_structure": "是否结构清晰",
        },
    )


def _snapshot(question_type: str = "PROJECT", previous_turns: list[DynamicTurnDTO] | None = None) -> EvaluationSnapshot:
    topic = _topic(question_type)
    return EvaluationSnapshot(
        session_entity_id=1,
        session_id="session-1",
        user_id=1,
        session_status="INTERVIEWING",
        interview_mode="STRICT",
        llm_provider="dashscope",
        topic=topic,
        turn=DynamicTurnDTO(id=7, topic_id=1, turn_type="MAIN", turn_order=1, question=topic.main_question),
        previous_turns=previous_turns or [],
    )


def _service(monkeypatch, payload) -> tuple[HybridAnswerEvaluationService, _StubInvoker, _PassthroughSingleFlight]:
    service = HybridAnswerEvaluationService(heuristic_evaluator=DynamicAnswerEvaluationService())
    invoker = _StubInvoker(payload)
    single_flight = _PassthroughSingleFlight()
    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "structured_output_invoker", invoker)
    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "single_flight", single_flight)
    return service, invoker, single_flight


def _assessments(dimensions: dict[str, int], evidence: dict[str, list[str]], question_type: str = "PROJECT"):
    return LLMEvaluationResult(
        dimensions=[
            LLMDimensionAssessment(
                dimension=dimension,
                score=score,
                assessment=f"{dimension} assessment",
                evidence_quotes=evidence.get(dimension, []),
                gaps=[f"{dimension} 缺少细节"] if score < 60 else [],
            )
            for dimension, score in dimensions.items()
        ]
    )


# ---------------- A. Rule Guard ----------------


async def test_empty_answer_is_rule_only_without_llm(monkeypatch):
    service, invoker, _ = _service(monkeypatch, LLMEvaluationResult())

    outcome = await service.evaluate(_snapshot(), "   ")

    assert invoker.calls == []
    assert outcome.llm_attempted is False
    assert outcome.evaluation.ability_score == 0
    assert outcome.evaluation.evaluation_method == "RULE_ONLY"
    assert outcome.evaluation.confidence == 1.0
    assert outcome.evaluation.guard_flags == ["EMPTY"]


async def test_very_short_answer_skips_semantic_and_caps(monkeypatch):
    service, invoker, _ = _service(monkeypatch, LLMEvaluationResult())

    outcome = await service.evaluate(_snapshot(), "用过 Redis")

    assert invoker.calls == [], "极短回答不应触发 LLM 调用"
    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert outcome.evaluation.ability_score <= 45
    assert "VERY_SHORT" in outcome.evaluation.guard_flags
    assert outcome.evaluation.confidence == 0.35


async def test_generic_answer_is_capped(monkeypatch):
    # 每个正向维度都必须有自己的原文证据（P0-3），否则整次语义结果会被拒绝
    quotes = {
        "authenticity": ["我们项目里很多地方都用了"],
        "technical_depth": ["主要是把热点数据放在 Redis 里"],
        "communication_structure": ["缓存可以大幅提升性能"],
    }
    llm = _assessments({"authenticity": 90, "technical_depth": 92, "communication_structure": 88}, quotes)
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), GENERIC_ANSWER)

    assert "GENERIC" in outcome.evaluation.guard_flags
    assert outcome.evaluation.ability_score <= 60, "泛化回答必须被 hard cap"
    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"


async def test_off_topic_answer_is_capped(monkeypatch):
    llm = _assessments(
        {"authenticity": 85, "technical_depth": 90, "communication_structure": 85},
        {
            "authenticity": ["异步任务应该用多线程"],
            "technical_depth": ["不需要引入 Redis 这么重的组件"],
            "communication_structure": ["Python 的 ThreadPoolExecutor 就能搞定"],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), OFF_TOPIC_ANSWER)

    assert "OFF_TOPIC" in outcome.evaluation.guard_flags
    assert outcome.evaluation.ability_score <= 45
    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"


async def test_generic_infra_word_does_not_trigger_off_topic_guard(monkeypatch):
    """「负载均衡」这类通用基建词不得触发 hard cap（只影响旧规则的扣分，不进 guard）。"""
    answer = (
        "当时主要考虑的是消费语义：List 只能做点对点，做不到多实例负载均衡，而普通 MQ 太重。"
        "我们最看重的是至少一次投递 + 可回溯这两个约束，所以最后选了 Redis Streams。"
    )
    llm = _assessments(
        {"authenticity": 80, "technical_depth": 82, "communication_structure": 78},
        {
            "authenticity": ["我们最看重的是至少一次投递 + 可回溯这两个约束"],
            "technical_depth": ["做不到多实例负载均衡"],
            "communication_structure": ["当时主要考虑的是消费语义"],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), answer)

    assert "OFF_TOPIC" not in outcome.evaluation.guard_flags
    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    assert outcome.evaluation.ability_score >= 70


# ---------------- B. Semantic scoring 与权重 ----------------


@pytest.mark.parametrize(
    "question_type,dimensions",
    [
        ("PROJECT", {"authenticity": 80, "technical_depth": 60, "communication_structure": 100}),
        ("KNOWLEDGE", {"knowledge_accuracy": 80, "technical_depth": 60, "communication_structure": 100}),
        ("SYSTEM_DESIGN", {"system_thinking": 80, "technical_depth": 60, "communication_structure": 100}),
    ],
)
async def test_weighted_dimension_aggregation_per_question_type(monkeypatch, question_type, dimensions):
    weights = active_dimension_weights(question_type)
    expected = int(round(sum(dimensions[name] * weight for name, weight in weights.items())))
    evidence = {name: [STRONG_PROJECT_ANSWER[:40]] for name in dimensions}
    service, _, _ = _service(monkeypatch, _assessments(dimensions, evidence, question_type))

    outcome = await service.evaluate(_snapshot(question_type), STRONG_PROJECT_ANSWER)

    assert set(outcome.evaluation.dimension_scores) == set(weights)
    assert outcome.evaluation.ability_score == expected
    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    assert outcome.evaluation.feedback


async def test_dimension_mismatch_falls_back(monkeypatch):
    invalid = LLMEvaluationResult(
        dimensions=[
            LLMDimensionAssessment(dimension="authenticity", score=90, evidence_quotes=[]),
            LLMDimensionAssessment(dimension="knowledge_accuracy", score=90, evidence_quotes=[]),
            LLMDimensionAssessment(dimension="communication_structure", score=90, evidence_quotes=[]),
        ]
    )
    service, _, _ = _service(monkeypatch, invalid)

    outcome = await service.evaluate(_snapshot("PROJECT"), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert any(flag.startswith("FALLBACK:") for flag in outcome.evaluation.guard_flags)


async def test_duplicate_dimension_falls_back(monkeypatch):
    duplicated = LLMEvaluationResult(
        dimensions=[
            LLMDimensionAssessment(dimension="authenticity", score=90, evidence_quotes=[]),
            LLMDimensionAssessment(dimension="authenticity", score=70, evidence_quotes=[]),
            LLMDimensionAssessment(dimension="technical_depth", score=90, evidence_quotes=[]),
            LLMDimensionAssessment(dimension="communication_structure", score=80, evidence_quotes=[]),
        ]
    )
    service, _, _ = _service(monkeypatch, duplicated)

    outcome = await service.evaluate(_snapshot("PROJECT"), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert "FALLBACK:DUPLICATE_DIMENSION" in outcome.evaluation.guard_flags


# ---------------- C. Evidence validation ----------------


def test_normalize_for_evidence_is_whitespace_insensitive():
    assert _normalize_for_evidence("Consumer Group\n用 XREADGROUP 消费") == _normalize_for_evidence(
        "consumergroup用xreadgroup消费"
    )


async def test_evidence_must_come_from_answer(monkeypatch):
    real_quote = "每个任务带唯一 message_id 做幂等"
    fabricated = "我们用了 Kafka 做消息总线以保证顺序性"
    evidence = {
        "authenticity": [real_quote],
        "technical_depth": [real_quote, fabricated],
        "communication_structure": [real_quote],
    }
    llm = _assessments({"authenticity": 80, "technical_depth": 82, "communication_structure": 78}, evidence)
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    quotes = [item.quote for item in outcome.evaluation.evidence]
    assert real_quote in quotes
    assert fabricated not in quotes, "编造的 quote 必须被丢弃"
    assert all(item.quote in STRONG_PROJECT_ANSWER for item in outcome.evaluation.evidence)


async def test_low_dimension_evidence_is_marked_risk(monkeypatch):
    quote = "主要是把热点数据放在 Redis 里"
    evidence = {"authenticity": [quote], "technical_depth": [quote], "communication_structure": [quote]}
    llm = _assessments({"authenticity": 40, "technical_depth": 45, "communication_structure": 50}, evidence)
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), GENERIC_ANSWER)

    assert outcome.evaluation.evidence
    assert {item.assessment for item in outcome.evaluation.evidence} == {"RISK"}


async def test_high_score_without_enough_evidence_is_capped(monkeypatch):
    """同一句 quote 挂在三个维度上 → unique span 只有 1 → 必须触发 HIGH_SCORE_EVIDENCE_CAP。"""
    single_quote = "每个任务带唯一 message_id 做幂等"
    llm = _assessments(
        {"authenticity": 95, "technical_depth": 95, "communication_structure": 92},
        {
            "authenticity": [single_quote],
            "technical_depth": [single_quote],
            "communication_structure": [single_quote],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert len(outcome.evaluation.evidence) == 3, "展示层保留「同一句支持多个维度」的映射"
    assert len({_normalize_for_evidence(item.quote) for item in outcome.evaluation.evidence}) == 1
    assert outcome.evaluation.ability_score <= 84
    assert "HIGH_SCORE_EVIDENCE_CAP" in outcome.evaluation.guard_flags
    assert outcome.evaluation.confidence == 0.65, "unique span 只有 1 条，不得给到 0.90"


async def test_duplicate_quotes_in_one_dimension_do_not_inflate_confidence(monkeypatch):
    """同一句 quote 在同一个维度重复 3 次 → 只能算 1 条 unique span。"""
    repeated = "每个任务带唯一 message_id 做幂等"
    llm = _assessments(
        {"authenticity": 70, "technical_depth": 70, "communication_structure": 70},
        {
            "authenticity": [repeated, repeated, repeated],
            "technical_depth": [repeated],
            "communication_structure": [repeated],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot("PROJECT"), STRONG_PROJECT_ANSWER)

    unique = {_normalize_for_evidence(item.quote) for item in outcome.evaluation.evidence}
    assert len(unique) == 1
    assert outcome.evaluation.confidence == 0.65
    assert outcome.evaluation.confidence != 0.90, "重复 quote 不得把置信度刷到最高档"


async def test_high_score_with_sufficient_evidence_is_kept(monkeypatch):
    quotes = [
        "生产端用 XADD 写入 Redis Streams",
        "消费端用 Consumer Group + XREADGROUP 多实例并行消费",
        "每个任务带唯一 message_id 做幂等",
        "超时任务用 XPENDING 捞出来重新投递",
    ]
    llm = _assessments(
        {"authenticity": 92, "technical_depth": 94, "communication_structure": 90},
        {"authenticity": quotes[:1], "technical_depth": quotes[1:], "communication_structure": quotes[:2]},
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert len({_normalize_for_evidence(item.quote) for item in outcome.evaluation.evidence}) >= 4
    assert outcome.evaluation.ability_score >= 85
    assert "HIGH_SCORE_EVIDENCE_CAP" not in outcome.evaluation.guard_flags


async def test_no_valid_evidence_falls_back_to_heuristic(monkeypatch):
    llm = _assessments(
        {"authenticity": 90, "technical_depth": 90, "communication_structure": 90},
        {"authenticity": ["完全不存在的一句话"]},
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert "FALLBACK:NO_VALID_EVIDENCE" in outcome.evaluation.guard_flags
    assert outcome.evaluation.confidence == 0.35


async def test_positive_dimension_without_own_evidence_is_rejected(monkeypatch):
    """P0-3：technical_depth=80 但没有自己的原文证据 → 整次语义结果作废，不得参与总分。"""
    llm = _assessments(
        {"authenticity": 80, "technical_depth": 80, "communication_structure": 78},
        {
            "authenticity": ["这个异步任务队列是我负责设计和落地的"],
            "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert "FALLBACK:UNGROUNDED_POSITIVE_DIMENSION" in outcome.evaluation.guard_flags
    assert outcome.evaluation.evidence == []
    # 无证据的 80 分不得成为最终分
    assert outcome.evaluation.ability_score != 80


async def test_low_dimension_without_evidence_is_allowed(monkeypatch):
    """低分维度不要求证据：它本来就是在说明「这里不足」。"""
    llm = _assessments(
        {"authenticity": 80, "technical_depth": 40, "communication_structure": 78},
        {
            "authenticity": ["这个异步任务队列是我负责设计和落地的"],
            "technical_depth": [],
            "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
        },
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    assert outcome.evaluation.dimension_scores["technical_depth"] == 40


# ---------------- D. Confidence ----------------


_Q_STRONG_1 = "生产端用 XADD 写入 Redis Streams"
_Q_STRONG_2 = "每个任务带唯一 message_id 做幂等"
_Q_STRONG_3 = "超时任务用 XPENDING 捞出来重新投递"


@pytest.mark.parametrize(
    "evidence,expected",
    [
        # unique span = 3
        (
            {"authenticity": [_Q_STRONG_1], "technical_depth": [_Q_STRONG_2], "communication_structure": [_Q_STRONG_3]},
            0.90,
        ),
        # unique span = 2（q1 复用在两个维度上仍只算 1 条）
        (
            {
                "authenticity": [_Q_STRONG_1],
                "technical_depth": [_Q_STRONG_1, _Q_STRONG_2],
                "communication_structure": [_Q_STRONG_2],
            },
            0.80,
        ),
        # unique span = 1（同一句挂在三个维度上）
        (
            {"authenticity": [_Q_STRONG_1], "technical_depth": [_Q_STRONG_1], "communication_structure": [_Q_STRONG_1]},
            0.65,
        ),
    ],
)
async def test_confidence_tiers(monkeypatch, evidence, expected):
    llm = _assessments(
        {"authenticity": 70, "technical_depth": 70, "communication_structure": 70},
        evidence,
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot("PROJECT"), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    unique = {_normalize_for_evidence(item.quote) for item in outcome.evaluation.evidence}
    assert len(unique) == (3 if expected == 0.90 else 2 if expected == 0.80 else 1)
    assert outcome.evaluation.confidence == expected


async def test_knowledge_confidence_is_capped(monkeypatch):
    quotes = [
        "生产端用 XADD 写入 Redis Streams",
        "消费端用 Consumer Group + XREADGROUP 多实例并行消费",
        "每个任务带唯一 message_id 做幂等",
    ]
    llm = _assessments(
        {"knowledge_accuracy": 88, "technical_depth": 86, "communication_structure": 84},
        {"knowledge_accuracy": quotes, "technical_depth": quotes, "communication_structure": quotes},
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot("KNOWLEDGE"), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.confidence <= 0.75, "本轮没有 RAG factual grounding，必须封顶"


async def test_rule_only_and_fallback_confidence(monkeypatch):
    service, _, _ = _service(monkeypatch, LLMEvaluationResult())
    empty = await service.evaluate(_snapshot(), "")
    assert empty.evaluation.confidence == 1.0

    fallback = await service.evaluate(_snapshot(), "用过 Redis")
    assert fallback.evaluation.confidence == 0.35


# ---------------- E. Provider / SingleFlight ----------------


async def test_evaluator_uses_given_provider_and_provider_in_key(monkeypatch):
    quotes = {
        "authenticity": ["这个异步任务队列是我负责设计和落地的"],
        "technical_depth": ["每个任务带唯一 message_id 做幂等"],
        "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
    }
    llm = _assessments(
        {"authenticity": 80, "technical_depth": 80, "communication_structure": 80},
        quotes,
    )
    service, invoker, single_flight = _service(monkeypatch, llm)
    registry = _StubRegistry()
    monkeypatch.setattr("app.common.ai.llm_provider.llm_registry", registry)

    await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER, llm_provider="custom-provider")

    assert registry.providers == ["custom-provider"], "evaluator 不得自行使用默认 provider"
    assert invoker.calls[0]["chat_model"] == "model-for-custom-provider"
    key = single_flight.keys[0]
    assert key.startswith("answer-evaluate|"), "evaluator 必须复用 SingleFlight"
    # key 是内容哈希：provider 必须参与指纹（见 test_single_flight_key_differs_by_provider）
    assert key != build_single_flight_key("answer-evaluate", EVALUATOR_VERSION, "session-1")


async def test_single_flight_key_differs_by_provider(monkeypatch):
    llm = _assessments(
        {"authenticity": 70, "technical_depth": 70, "communication_structure": 70},
        {
            "authenticity": ["这个异步任务队列是我负责设计和落地的"],
            "technical_depth": ["每个任务带唯一 message_id 做幂等"],
            "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
        },
    )
    service, _, single_flight = _service(monkeypatch, llm)
    monkeypatch.setattr("app.common.ai.llm_provider.llm_registry", _StubRegistry())

    await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER, llm_provider="provider-a")
    await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER, llm_provider="provider-b")

    assert single_flight.keys[0] != single_flight.keys[1], "不同 provider 不得共享评分结果"


# ---------------- F. Failure / fallback ----------------


async def test_timeout_falls_back(monkeypatch):
    service, _, _ = _service(monkeypatch, LLMEvaluationResult())
    monkeypatch.setattr(service, "_timeout_seconds", staticmethod(lambda: 0.01))

    class _SlowInvoker:
        async def invoke(self, **_kwargs):
            await asyncio.sleep(0.5)
            return LLMEvaluationResult()

    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "structured_output_invoker", _SlowInvoker())

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert outcome.llm_attempted is True
    assert outcome.llm_error == "TimeoutError"


async def test_provider_exception_falls_back(monkeypatch):
    service, _, _ = _service(monkeypatch, RuntimeError("provider down"))

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert outcome.llm_error == "RuntimeError"
    assert outcome.evaluation.ability_score > 0


async def test_invalid_structured_output_falls_back(monkeypatch):
    service, _, _ = _service(monkeypatch, json.JSONDecodeError("bad json", "", 0))

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert outcome.llm_attempted is True


async def test_evaluator_disabled_uses_fallback(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings.interview, "answer_evaluator_enabled", False)
    service, invoker, _ = _service(monkeypatch, LLMEvaluationResult())

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)

    assert invoker.calls == []
    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert outcome.evaluation.confidence == 0.35


# ---------------- P0-1：所有 evaluation_method 都必须 active-dimension only ----------------

ALL_DIMENSIONS = {"authenticity", "technical_depth", "knowledge_accuracy", "system_thinking", "communication_structure"}


def _assert_only_active_dims(evaluation, question_type: str):
    active = set(active_dimension_weights(question_type))
    assert set(evaluation.dimension_scores) == active, (
        f"{question_type} 只允许 {active}，实际 {set(evaluation.dimension_scores)}"
    )
    assert not (set(evaluation.dimension_scores) - active)
    assert set(evaluation.dimension_scores) != ALL_DIMENSIONS, "不得把 5 个维度原样带出去"


async def test_rule_only_empty_answer_is_active_dimension_only(monkeypatch):
    service, _, _ = _service(monkeypatch, LLMEvaluationResult())

    outcome = await service.evaluate(_snapshot("PROJECT"), "")

    assert outcome.evaluation.evaluation_method == "RULE_ONLY"
    _assert_only_active_dims(outcome.evaluation, "PROJECT")


@pytest.mark.parametrize("question_type", ["PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"])
async def test_very_short_and_disabled_timeout_are_active_dimension_only(monkeypatch, question_type):
    from app.config import settings

    service, _, _ = _service(monkeypatch, LLMEvaluationResult())

    # VERY_SHORT
    outcome = await service.evaluate(_snapshot(question_type), "用过 Redis")
    assert "VERY_SHORT" in outcome.evaluation.guard_flags
    _assert_only_active_dims(outcome.evaluation, question_type)

    # evaluator disabled
    monkeypatch.setattr(settings.interview, "answer_evaluator_enabled", False)
    disabled = await service.evaluate(_snapshot(question_type), STRONG_PROJECT_ANSWER)
    assert disabled.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert "FALLBACK:DISABLED" in disabled.evaluation.guard_flags
    _assert_only_active_dims(disabled.evaluation, question_type)
    monkeypatch.setattr(settings.interview, "answer_evaluator_enabled", True)

    # timeout
    service2, _, _ = _service(monkeypatch, LLMEvaluationResult())
    monkeypatch.setattr(service2, "_timeout_seconds", staticmethod(lambda: 0.01))

    class _SlowInvoker:
        async def invoke(self, **_kwargs):
            await asyncio.sleep(0.5)
            return LLMEvaluationResult()

    monkeypatch.setattr(evaluation_module.hybrid_evaluator, "structured_output_invoker", _SlowInvoker())
    timed_out = await service2.evaluate(_snapshot(question_type), STRONG_PROJECT_ANSWER)

    assert timed_out.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert "FALLBACK:TimeoutError" in timed_out.evaluation.guard_flags
    _assert_only_active_dims(timed_out.evaluation, question_type)


@pytest.mark.parametrize("question_type", ["PROJECT", "KNOWLEDGE", "SYSTEM_DESIGN"])
async def test_rejected_semantic_result_is_active_dimension_only(monkeypatch, question_type):
    """dimension 不匹配被拒绝后，fallback 也必须是 active-dimension only。"""
    invalid = LLMEvaluationResult(
        dimensions=[LLMDimensionAssessment(dimension="authenticity", score=90, evidence_quotes=[])],
    )
    service, _, _ = _service(monkeypatch, invalid)

    outcome = await service.evaluate(_snapshot(question_type), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    _assert_only_active_dims(outcome.evaluation, question_type)


# ---------------- signals / feedback 约束 ----------------


async def test_signals_are_bounded_and_avoid_banned_wording(monkeypatch):
    llm = LLMEvaluationResult(
        dimensions=[
            LLMDimensionAssessment(
                dimension="authenticity",
                score=70,
                assessment="证据充分",
                evidence_quotes=["每个任务带唯一 message_id 做幂等"],
                gaps=["候选人显然不会做这个方案", "缺少可验证个人贡献"],
            ),
            LLMDimensionAssessment(
                dimension="technical_depth",
                score=75,
                assessment="实现细节扎实",
                evidence_quotes=["超时任务用 XPENDING 捞出来重新投递"],
                gaps=[],
            ),
            LLMDimensionAssessment(
                dimension="communication_structure",
                score=72,
                assessment="层次清楚",
                # score >= 60 的维度必须有真实 quote（P0-3）
                evidence_quotes=["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
                gaps=[],
            ),
        ],
        risks=["候选人根本不会", "回答与题目方向有偏差"],
    )
    service, _, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot(), STRONG_PROJECT_ANSWER)
    signals = outcome.evaluation.signals

    assert outcome.evaluation.evaluation_method == "HYBRID_LLM"
    for key in ("strengths", "gaps", "risks"):
        assert len(signals[key]) <= 5
        assert all(len(item) <= 60 for item in signals[key])
    assert all("显然不会" not in item for item in signals["gaps"]), "不允许越界定性"
    assert all("根本不会" not in item for item in signals["risks"])
    assert "缺少可验证个人贡献" in signals["gaps"]
    assert len(outcome.evaluation.feedback) <= 200


async def test_previous_turn_comparison_does_not_anchor_score(monkeypatch):
    previous = [
        DynamicTurnDTO(
            id=1,
            topic_id=1,
            turn_type="MAIN",
            turn_order=1,
            question="上一题",
            answer="上一轮回答",
            ability_score=50,
        )
    ]
    llm = _assessments(
        {"authenticity": 88, "technical_depth": 90, "communication_structure": 86},
        {
            "authenticity": ["这个异步任务队列是我负责设计和落地的"],
            "technical_depth": ["每个任务带唯一 message_id 做幂等", "超时任务用 XPENDING 捞出来重新投递"],
            "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
        },
    )
    service, invoker, _ = _service(monkeypatch, llm)

    outcome = await service.evaluate(_snapshot("PROJECT", previous_turns=previous), STRONG_PROJECT_ANSWER)

    assert outcome.evaluation.ability_score >= 85, "上一轮 50 分不得把本轮压回 55~65"
    assert "重答后有明显补充" in outcome.evaluation.signals["strengths"]

    # P1-1：历史分数绝不能进入 LLM prompt（只有代码侧 compare 用得到）
    user_prompt = invoker.calls[0]["user_prompt"]
    assert "该轮历史分数" not in user_prompt
    assert "（该轮历史分数：50）" not in user_prompt
    # 历史问答仍然必须给模型（用于判断是否补齐缺口 / 是否矛盾）
    assert "上一题" in user_prompt
    assert "上一轮回答" in user_prompt


async def test_prompt_keeps_dimension_rubric_mapping(monkeypatch):
    """P1-2：rubric 必须保留 dimension → description 映射，且只输出 active dimensions。"""
    llm = _assessments(
        {"authenticity": 80, "technical_depth": 80, "communication_structure": 80},
        {
            "authenticity": ["这个异步任务队列是我负责设计和落地的"],
            "technical_depth": ["每个任务带唯一 message_id 做幂等"],
            "communication_structure": ["消费端用 Consumer Group + XREADGROUP 多实例并行消费"],
        },
    )
    service, invoker, _ = _service(monkeypatch, llm)

    await service.evaluate(_snapshot("PROJECT"), STRONG_PROJECT_ANSWER)

    user_prompt = invoker.calls[0]["user_prompt"]
    assert "- authenticity: 个人职责是否可信" in user_prompt
    assert "- technical_depth: 实现细节是否扎实" in user_prompt
    assert "- communication_structure: 是否结构清晰" in user_prompt
    # PROJECT 题不应渲染与本题无关的维度
    assert "knowledge_accuracy" not in user_prompt
    assert "system_thinking" not in user_prompt


async def test_prompt_renders_rubric_for_other_question_types(monkeypatch):
    llm = _assessments(
        {"knowledge_accuracy": 78, "technical_depth": 76, "communication_structure": 74},
        {
            "knowledge_accuracy": ["生产端用 XADD 写入 Redis Streams"],
            "technical_depth": ["每个任务带唯一 message_id 做幂等"],
            "communication_structure": ["超时任务用 XPENDING 捞出来重新投递"],
        },
        "KNOWLEDGE",
    )
    service, invoker, _ = _service(monkeypatch, llm)
    snapshot = _snapshot("KNOWLEDGE")
    snapshot.topic.rubric = {
        "knowledge_accuracy": "概念和机制是否准确",
        "technical_depth": "是否能讲到工程边界",
        "communication_structure": "是否结构清晰",
    }

    await service.evaluate(snapshot, STRONG_PROJECT_ANSWER)

    user_prompt = invoker.calls[0]["user_prompt"]
    assert "- knowledge_accuracy: 概念和机制是否准确" in user_prompt
    assert "- technical_depth: 是否能讲到工程边界" in user_prompt
    assert "- communication_structure: 是否结构清晰" in user_prompt
    assert "authenticity" not in user_prompt
