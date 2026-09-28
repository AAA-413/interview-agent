"""Conversation Quality 基线评测（deterministic，不调用真实 LLM）。

与 ``quality_baseline_eval.py`` 并列，但只覆盖「面试对话主链路 V1」引入的行为：

1. Context 包含上一轮 Q/A（避免重复追问 / 保证语义承接的数据基础）
2. Context 不包含超过预算的过旧历史（防止 context 无限增长）
3. FOLLOW_UP intent 正确传递到 QuestionRealizer
4. QuestionRealizer 失败时 fallback 可用，且面试不中断
5. NEXT_TOPIC 能拿到上一个 topic 的信息
6. 不可信数据（候选人回答 / 简历证据）不会进入 system prompt

LLM 调用使用替身（stub）：本脚本只做结构与链路的确定性校验，
生成质量本身由人工冒烟 + 后续 LLM Judge 负责。

Usage:
    PYTHONPATH=. .venv/bin/python tests/conversation_quality_eval.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from app.common.single_flight import build_single_flight_key
from app.modules.interview import question_realizer as question_realizer_module
from app.modules.interview.context.builder import InterviewContextBuilder
from app.modules.interview.context.models import ContextBudget
from app.modules.interview.dynamic_service import (
    DynamicAnswerEvaluationService,
    DynamicInterviewService,
    StrictInterviewPolicy,
    resolve_topic_opening,
)
from app.modules.interview.models import InterviewSessionEntity, TurnType
from app.modules.interview.question_realizer import (
    _FollowUpQuestionDTO,
    _TransitionDTO,
    question_realizer,
)
from app.modules.interview.schemas import (
    DynamicDecisionDTO,
    DynamicTopicDTO,
    DynamicTransitionDTO,
    DynamicTurnDTO,
)

OUTPUT_DIR = Path(__file__).parent / "quality_baselines" / "conversation"

REDIS_TOPIC = DynamicTopicDTO(
    topic_key="async_task_pipeline",
    topic_title="异步任务流水线",
    skill_key="python",
    question_type="PROJECT",
    source_type="resume",
    evidence_snippet="实现异步任务队列（Redis Streams + Consumer Group），支持任务重试、超时和幂等。",
    main_question="请讲清楚 Redis Streams 异步任务队列的设计。",
    topic_order=1,
)
IDEMPOTENCY_TOPIC = DynamicTopicDTO(
    topic_key="idempotency_design",
    topic_title="幂等设计",
    skill_key="python",
    question_type="PROJECT",
    source_type="resume",
    evidence_snippet="任务幂等处理：唯一 key + 去重表。",
    main_question="请讲清楚消费端怎么保证幂等。",
    topic_order=2,
)

REDIS_ANSWER = (
    "我们后来用 Redis Streams 做异步任务队列，Producer 用 XADD 写，"
    "Consumer Group 用 XREADGROUP 消费，多实例并行消费，超时任务用 XPENDING 检测后重试。"
)


class _StubInvoker:
    """替身 LLM：记录 prompt，返回固定结构化结果。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    async def invoke(self, *, chat_model, system_prompt, user_prompt, output_model, **kwargs):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self.payload


class _FakeDb:
    async def flush(self):
        return None

    def add(self, _entity):
        return None


async def _passthrough_single_flight(key, fn, **kwargs):
    return await fn()


def _turn(turn_order: int, question: str, answer: str, turn_type: str = TurnType.MAIN.value) -> DynamicTurnDTO:
    return DynamicTurnDTO(
        id=turn_order,
        topic_id=1,
        turn_type=turn_type,
        turn_order=turn_order,
        question=question,
        answer=answer,
        ability_score=60,
        signals={"strengths": ["能说明整体链路"], "gaps": []},
    )


def check_context_contains_previous_qa() -> list[dict]:
    history = [
        _turn(1, "你们为什么使用 Redis Streams？", "因为需要 Consumer Group 支持多个消费者并行消费。"),
        _turn(2, "那消费失败怎么重试？", "超时任务用 XPENDING 捞出来重新投递。", turn_type=TurnType.FOLLOW_UP.value),
    ]
    context = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=REDIS_TOPIC,
        current_question="追问：幂等怎么做的？",
        current_answer=REDIS_ANSWER,
        answered_turns=history,
        evaluation=None,
        follow_up_count=1,
    )
    history_text = context.render_history()
    return [
        {
            "check": "context_contains_previous_question",
            "passed": "你们为什么使用 Redis Streams？" in history_text,
            "detail": f"history={history_text[:80]}",
        },
        {
            "check": "context_contains_previous_answer",
            "passed": "Consumer Group" in history_text and "XPENDING" in history_text,
            "detail": "previous answers present in rendered history",
        },
        {
            "check": "context_contains_current_answer",
            "passed": "XREADGROUP" in context.current_answer,
            "detail": f"current_answer={context.current_answer[:40]}",
        },
    ]


def check_context_drops_turns_beyond_budget() -> list[dict]:
    budget = ContextBudget()
    turns = [
        _turn(order, f"第 {order} 题", f"第 {order} 个回答，内容足够长以通过评估的长度校验并包含细节。")
        for order in range(1, budget.max_recent_turns + 4)
    ]
    context = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=REDIS_TOPIC,
        current_question="当前问题",
        current_answer="当前回答",
        answered_turns=turns,
        evaluation=None,
    )
    rendered = context.render_history()
    return [
        {
            "check": "recent_turns_capped",
            "passed": len(context.recent_turns) == budget.max_recent_turns,
            "detail": f"turns in context={len(context.recent_turns)}, budget={budget.max_recent_turns}",
        },
        {
            "check": "oldest_turn_dropped",
            "passed": "第 1 个回答" not in rendered,
            "detail": f"rendered chars={len(rendered)}",
        },
    ]


async def check_follow_up_intent_reaches_realizer() -> list[dict]:
    topic = REDIS_TOPIC
    turn = DynamicTurnDTO(turn_type=TurnType.MAIN.value, turn_order=1, question=topic.main_question)
    evaluation = DynamicAnswerEvaluationService().evaluate(topic, turn, REDIS_ANSWER, [])
    decision = StrictInterviewPolicy().decide(
        topic=topic,
        turn=turn,
        evaluation=evaluation,
        answered_turns_after_current=[
            turn.model_copy(update={"answer": REDIS_ANSWER, "ability_score": evaluation.ability_score})
        ],
        has_next_topic=True,
    )
    context = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=topic,
        current_question=topic.main_question,
        current_answer=REDIS_ANSWER,
        answered_turns=[],
        evaluation=evaluation,
        follow_up_count=0,
    )

    stub = _StubInvoker(_FollowUpQuestionDTO(question="你刚才提到 XREADGROUP，重复投递怎么处理？"))
    original_invoker = question_realizer_module.structured_output_invoker
    original_single_flight = question_realizer_module.single_flight
    question_realizer_module.structured_output_invoker = stub
    question_realizer_module.single_flight = _passthrough_single_flight
    try:
        realized = await question_realizer.realize_follow_up(context, decision)
    finally:
        question_realizer_module.structured_output_invoker = original_invoker
        question_realizer_module.single_flight = original_single_flight

    user_prompt = stub.calls[0]["user_prompt"] if stub.calls else ""
    system_prompt = stub.calls[0]["system_prompt"] if stub.calls else ""
    return [
        {
            "check": "policy_emits_intent_only",
            "passed": decision.action == "FOLLOW_UP" and decision.next_question is None and bool(decision.follow_up_intent),
            "detail": f"action={decision.action}, intent={decision.follow_up_intent}, next_question={decision.next_question}",
        },
        {
            "check": "intent_forwarded_to_realizer",
            "passed": bool(decision.follow_up_intent) and decision.follow_up_intent in user_prompt,
            "detail": f"intent={decision.follow_up_intent}",
        },
        {
            "check": "realizer_receives_answer_not_only_gap",
            "passed": "XREADGROUP" in user_prompt and "Consumer Group" in user_prompt,
            "detail": "candidate's concrete terms present in user prompt",
        },
        {
            "check": "untrusted_data_not_in_system_prompt",
            "passed": "XREADGROUP" not in system_prompt,
            "detail": "candidate answer stays in user message only",
        },
        {
            "check": "realizer_returns_question",
            "passed": bool(realized),
            "detail": f"question={realized}",
        },
    ]


async def check_fallback_available() -> list[dict]:
    service = DynamicInterviewService()
    session = InterviewSessionEntity(id=1, user_id=1, session_id="eval-session", interview_mode="STRICT")
    topic = REDIS_TOPIC
    turn = DynamicTurnDTO(turn_type=TurnType.MAIN.value, turn_order=1, question=topic.main_question)
    evaluation = DynamicAnswerEvaluationService().evaluate(topic, turn, REDIS_ANSWER, [])
    context = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=topic,
        current_question=topic.main_question,
        current_answer=REDIS_ANSWER,
        answered_turns=[],
        evaluation=evaluation,
    )
    decision = DynamicDecisionDTO(action="FOLLOW_UP", reason="r", follow_up_intent="VERIFY_METRIC", target_gap="缺少指标")
    expected_template = StrictInterviewPolicy._followup_question(topic, evaluation, followup_number=1)

    results = []

    async def _raise(exc: Exception):
        raise exc

    for label, exc in (
        ("timeout", asyncio.TimeoutError()),
        ("exception", RuntimeError("provider down")),
    ):
        original = question_realizer.realize_follow_up

        async def _boom(*_args, _exc=exc, **_kwargs):
            raise _exc

        question_realizer.realize_follow_up = _boom
        try:
            realized = await service._realize_follow_up_question(
                _FakeDb(),
                session,
                topic=topic,
                evaluation=evaluation,
                context=context,
                decision=decision,
                followup_count=0,
                topic_id=1,
                turn_id=1,
            )
        finally:
            question_realizer.realize_follow_up = original

        results.append(
            {
                "check": f"fallback_on_{label}",
                "passed": realized == expected_template,
                "detail": f"realized={realized[:40] if realized else None}",
            }
        )

    del _raise
    return results


async def check_next_topic_has_previous_topic_info() -> list[dict]:
    transition_context = InterviewContextBuilder().build_topic_transition(
        session_id="eval-session",
        interview_mode="STRICT",
        previous_topic=REDIS_TOPIC,
        previous_question="你们为什么最后选了 Redis Streams？",
        previous_answer=REDIS_ANSWER,
        next_topic=IDEMPOTENCY_TOPIC,
    )

    stub = _StubInvoker(_TransitionDTO(transition="这块先到这里。", question="消费者重复收到任务时怎么保证幂等？"))
    original_invoker = question_realizer_module.structured_output_invoker
    original_single_flight = question_realizer_module.single_flight
    question_realizer_module.structured_output_invoker = stub
    question_realizer_module.single_flight = _passthrough_single_flight
    try:
        transition = await question_realizer.realize_topic_transition(transition_context)
    finally:
        question_realizer_module.structured_output_invoker = original_invoker
        question_realizer_module.single_flight = original_single_flight

    user_prompt = stub.calls[0]["user_prompt"] if stub.calls else ""
    opening, transition_text = resolve_topic_opening(transition, IDEMPOTENCY_TOPIC.main_question)
    failed_opening, failed_transition = resolve_topic_opening(None, IDEMPOTENCY_TOPIC.main_question)

    return [
        {
            "check": "transition_context_has_previous_topic",
            "passed": transition_context.previous_topic.topic_key == "async_task_pipeline"
            and "Consumer Group" in transition_context.previous_answer,
            "detail": f"previous={transition_context.previous_topic.topic_key}",
        },
        {
            "check": "transition_prompt_has_both_topics",
            "passed": "异步任务流水线" in user_prompt and "幂等设计" in user_prompt,
            "detail": "previous and next topic both in prompt",
        },
        {
            "check": "transition_composed_into_opening",
            "passed": opening.startswith("这块先到这里。") and "幂等" in opening and bool(transition_text),
            "detail": f"opening={opening[:40]}",
        },
        {
            "check": "transition_fallback_uses_main_question",
            "passed": failed_opening == IDEMPOTENCY_TOPIC.main_question and failed_transition == "",
            "detail": f"opening={failed_opening[:40]}",
        },
    ]


def check_single_flight_key_sensitive_to_context() -> list[dict]:
    with_history = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=REDIS_TOPIC,
        current_question="问题",
        current_answer=REDIS_ANSWER,
        answered_turns=[_turn(1, "上一题", "上一答：我们用了 Redis Streams。")],
    )
    without_history = InterviewContextBuilder().build(
        session_id="eval-session",
        interview_mode="STRICT",
        topic=REDIS_TOPIC,
        current_question="问题",
        current_answer=REDIS_ANSWER,
        answered_turns=[],
    )
    key_a = build_single_flight_key("followup-realize", *with_history.fingerprint_parts(), "VERIFY_METRIC", "gap")
    key_b = build_single_flight_key("followup-realize", *without_history.fingerprint_parts(), "VERIFY_METRIC", "gap")
    key_same = build_single_flight_key("followup-realize", *with_history.fingerprint_parts(), "VERIFY_METRIC", "gap")
    return [
        {
            "check": "single_flight_key_differs_on_state",
            "passed": key_a != key_b,
            "detail": f"{key_a[:24]} vs {key_b[:24]}",
        },
        {
            "check": "single_flight_key_stable_on_same_state",
            "passed": key_a == key_same,
            "detail": "same context merges",
        },
    ]


async def collect_checks() -> list[dict]:
    checks: list[dict] = []
    checks.extend(check_context_contains_previous_qa())
    checks.extend(check_context_drops_turns_beyond_budget())
    checks.extend(await check_follow_up_intent_reaches_realizer())
    checks.extend(await check_fallback_available())
    checks.extend(await check_next_topic_has_previous_topic_info())
    checks.extend(check_single_flight_key_sensitive_to_context())
    return checks


def write_outputs(checks: list[dict]) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for item in checks if item["passed"])
    failed = len(checks) - passed
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_checks": len(checks),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(checks), 4) if checks else 0.0,
        "checks": checks,
    }
    results_path = OUTPUT_DIR / "results.json"
    report_path = OUTPUT_DIR / "report.md"
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Conversation Quality 基线（deterministic）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 通过：{passed}/{len(checks)}（{payload['pass_rate'] * 100:.1f}%）",
        "",
        "| Check | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for item in checks:
        status = "PASS" if item["passed"] else "FAIL"
        lines.append(f"| {item['check']} | {status} | {item['detail']} |")
    lines.append("")
    lines.append("结论：" + ("对话主链路契约检查通过" if failed == 0 else f"存在 {failed} 项失败，需要修复"))
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return results_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Conversation quality deterministic eval")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总行")
    args = parser.parse_args()

    checks = asyncio.run(collect_checks())
    results_path, report_path = write_outputs(checks)
    passed = sum(1 for item in checks if item["passed"])
    failed = len(checks) - passed

    if not args.quiet:
        for item in checks:
            print(f"  [{'PASS' if item['passed'] else 'FAIL'}] {item['check']} - {item['detail']}")
    print(f"\nConversation Quality: {passed}/{len(checks)} passed")
    print(f"Report: {os.path.relpath(report_path)}")
    print(f"Results: {os.path.relpath(results_path)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
