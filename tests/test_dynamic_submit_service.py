"""DynamicInterviewService.submit_turn_answer() 的 service-level 测试。

之前只有 helper 级测试，导致「Phase 1 用 fallback_question 覆盖所有 action 的
next_question」这类状态机 bug 没有被发现（COACH_RETRY 的 main_question 被清成 None、
NEXT_TOPIC 在 transition 失败时 DB 与 response 不一致）。

这里用一个内存版 persistence（只替换 DB 访问方法，DTO 转换仍用真实实现）
驱动完整主流程，并显式验证：
- FOLLOW_UP / NEXT_TOPIC / COACH_RETRY 三种 action 的 persisted next_question 规则；
- Realizer / transition 失败时 reload 后的状态仍自洽；
- metric 写失败 → rollback，且不影响 Phase 1 已提交的状态；
- Phase 3 落库失败 → 回落 Phase 1 状态，API 不返回 500。
"""

from __future__ import annotations

import asyncio

import pytest

from app.modules.interview import question_realizer as question_realizer_module
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service as persistence
from app.modules.interview.dynamic_service import DynamicInterviewService
from app.modules.interview.models import (
    InterviewSessionEntity,
    InterviewTopicEntity,
    InterviewTurnEntity,
    SessionStatus,
    TopicStatus,
    TurnType,
)
from app.modules.interview.question_realizer import question_realizer
from app.modules.interview.schemas import SubmitDynamicTurnAnswerRequest

STRONG_ANSWER = (
    "我们用 Redis Streams 做异步任务队列：Producer 用 XADD 写入，Consumer Group 用 XREADGROUP 消费，"
    "每个任务带唯一 message_id 做幂等，超时任务用 XPENDING 捞出来重投，P99 从 800ms 降到 300ms。"
)
VAGUE_ANSWER = "用了一个队列，效果还不错，大家都觉得挺好用的。"


class _FakeDb:
    """最小 AsyncSession 替身：记录 commit / rollback，可指定第 N 次 flush 失败。"""

    def __init__(self, fail_flush_on: int | None = None):
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self._fail_flush_on = fail_flush_on
        self.entities: list[object] = []

    def add(self, entity):
        self.entities.append(entity)

    async def flush(self):
        self.flushes += 1
        if self._fail_flush_on is not None and self.flushes == self._fail_flush_on:
            raise RuntimeError("flush failed")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _MemoryPersistence:
    """内存版 persistence：只覆盖 submit_turn_answer 用到的 DB 访问方法。"""

    def __init__(
        self, session: InterviewSessionEntity, topics: list[InterviewTopicEntity], turns: list[InterviewTurnEntity]
    ):
        self.session = session
        self.topics = {topic.id: topic for topic in topics}
        self.turns = {turn.id: turn for turn in turns}
        self._next_turn_id = max(self.turns) + 1
        self.metric_failures: list[str] = []

    # ---- DB 访问 ----
    async def find_session_or_throw(self, _db, _session_id, _user_id=None):
        return self.session

    async def find_turn_or_throw(self, _db, turn_id, _session_entity_id, _user_id=None):
        return self.turns[turn_id]

    async def find_topic_or_throw(self, _db, topic_id, _user_id=None):
        return self.topics[topic_id]

    async def list_turns_by_topic(self, _db, topic_id):
        return sorted(
            (turn for turn in self.turns.values() if turn.topic_id == topic_id),
            key=lambda item: item.turn_order,
        )

    async def list_topics(self, _db, session_entity_id):
        return sorted(
            (topic for topic in self.topics.values() if topic.session_id == session_entity_id),
            key=lambda item: item.topic_order,
        )

    async def save_turn_answer(
        self, _db, turn, *, answer, ability_score, feedback, signals, evaluation, decision_action, decision, coach_hint
    ):
        turn.answer = answer
        turn.ability_score = ability_score
        turn.feedback = feedback
        turn.signals_json = _json(signals)
        turn.evaluation_json = _json(evaluation)
        turn.decision_action = decision_action
        turn.decision_json = _json(decision)
        turn.coach_hint_json = _json(coach_hint) if coach_hint else None

    async def update_topic_after_answer(self, _db, topic, *, turn_count, best_score, final_score, completed=False):
        topic.turn_count = turn_count
        topic.best_score = best_score
        topic.final_score = final_score
        if completed:
            topic.status = TopicStatus.COMPLETED.value

    async def create_turn(
        self, _db, *, session_entity_id, topic_id, user_id, turn_type, turn_order, question, coach_hint=None
    ):
        entity = InterviewTurnEntity(
            id=self._next_turn_id,
            session_id=session_entity_id,
            topic_id=topic_id,
            user_id=user_id,
            turn_type=turn_type,
            turn_order=turn_order,
            question=question,
            coach_hint_json=_json(coach_hint) if coach_hint else None,
        )
        self.turns[entity.id] = entity
        self._next_turn_id += 1
        return entity

    async def activate_topic(self, _db, topic_id, session_entity_id):
        for topic in self.topics.values():
            if topic.session_id == session_entity_id and topic.status == TopicStatus.ACTIVE.value:
                topic.status = TopicStatus.COMPLETED.value
        self.topics[topic_id].status = TopicStatus.ACTIVE.value
        self.session.current_topic_id = topic_id

    async def update_turn_question(self, _db, turn, question):
        turn.question = question

    async def update_turn_decision(self, _db, turn, decision):
        turn.decision_json = _json(decision)

    async def record_operation_metric(self, db, **kwargs):
        await db.add(object())
        await db.flush()

    # ---- 重载（等价于 GET /dynamic-sessions/{id}） ----
    def reload_turn(self, turn_id: int) -> dict:
        return persistence.turn_to_dto(self.turns[turn_id]).model_dump()

    def reload_topic(self, topic_id: int) -> dict:
        return persistence.topic_to_dto(self.topics[topic_id]).model_dump()


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _build_state(*, mode: str = "STRICT", current_turn_type: str = TurnType.MAIN.value, weak: bool = True):
    """构造一个「当前轮未作答」的会话状态。"""
    session = InterviewSessionEntity(
        id=1,
        user_id=1,
        session_id="svc-session",
        interview_mode=mode,
        llm_provider="dashscope",
        status=SessionStatus.INTERVIEWING,
    )
    topic = InterviewTopicEntity(
        id=1,
        session_id=1,
        user_id=1,
        topic_key="async_task_pipeline",
        topic_title="异步任务流水线",
        skill_key="python",
        question_type="PROJECT",
        source_type="resume",
        evidence_snippet="Redis Streams + Consumer Group 异步任务队列。",
        main_question="请讲清楚 Redis Streams 异步任务队列的设计。",
        topic_order=1,
        status=TopicStatus.ACTIVE.value,
        max_turns=3,
    )
    turns = [
        InterviewTurnEntity(
            id=1,
            session_id=1,
            topic_id=1,
            user_id=1,
            turn_type=TurnType.MAIN.value,
            turn_order=1,
            question=topic.main_question,
        )
    ]
    if current_turn_type == TurnType.FOLLOW_UP.value:
        # 已经追问过两次（都答完），使 Policy 判定为 NEXT_TOPIC
        for order, turn_id in ((2, 2), (3, 3)):
            turns.append(
                InterviewTurnEntity(
                    id=turn_id,
                    session_id=1,
                    topic_id=1,
                    user_id=1,
                    turn_type=TurnType.FOLLOW_UP.value,
                    turn_order=order,
                    question=f"追问 {order - 1}",
                    answer="上一轮回答内容足够长，并且包含具体实现细节说明。",
                    ability_score=55,
                )
            )
        turns.append(
            InterviewTurnEntity(
                id=4,
                session_id=1,
                topic_id=1,
                user_id=1,
                turn_type=TurnType.FOLLOW_UP.value,
                turn_order=4,
                question="追问 3",
            )
        )
    return session, topic, turns


def _install(monkeypatch, fake_persistence: _MemoryPersistence):
    for name in (
        "find_session_or_throw",
        "find_turn_or_throw",
        "find_topic_or_throw",
        "list_turns_by_topic",
        "list_topics",
        "save_turn_answer",
        "update_topic_after_answer",
        "create_turn",
        "activate_topic",
        "update_turn_question",
        "update_turn_decision",
        "record_operation_metric",
    ):
        monkeypatch.setattr(persistence, name, getattr(fake_persistence, name))


def _next_topic(active: bool = False) -> InterviewTopicEntity:
    return InterviewTopicEntity(
        id=2,
        session_id=1,
        user_id=1,
        topic_key="idempotency_design",
        topic_title="幂等设计",
        skill_key="python",
        question_type="PROJECT",
        source_type="resume",
        evidence_snippet="任务幂等处理。",
        main_question="请讲清楚消费端怎么保证幂等。",
        topic_order=2,
        status=TopicStatus.ACTIVE.value if active else TopicStatus.PENDING.value,
    )


async def _submit(service: DynamicInterviewService, db, turn_id: int, answer: str = STRONG_ANSWER):
    return await service.submit_turn_answer(
        db,
        "svc-session",
        turn_id,
        SubmitDynamicTurnAnswerRequest(answer=answer),
        user_id=1,
    )


# ---------------- Case 1：FOLLOW_UP + Realizer failure ----------------


async def test_follow_up_failure_keeps_next_question_consistent(monkeypatch):
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)

    async def _timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(question_realizer, "realize_follow_up", _timeout)
    db = _FakeDb()

    response = await _submit(DynamicInterviewService(), db, turn_id=1)

    assert response.decision.action == "FOLLOW_UP"
    expected = response.next_turn.question
    assert response.decision.next_question == expected

    # Phase 1 已提交（一次 commit），Phase 3 无需回填（fallback 已落库）
    assert db.commits >= 1

    # reload：answer 在，decision 与 next turn 一致
    answered = fake.reload_turn(1)
    assert answered["answer"] == STRONG_ANSWER
    assert answered["decision"]["next_question"] == expected
    assert fake.reload_turn(response.next_turn.id)["question"] == expected


# ---------------- Case 2：NEXT_TOPIC + transition failure ----------------


async def test_next_topic_transition_failure_keeps_main_question_everywhere(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)

    async def _fail(*_args, **_kwargs):
        return None  # Realizer 失败 / disabled / 返回空

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _fail)
    db = _FakeDb()

    response = await _submit(DynamicInterviewService(), db, turn_id=4)

    assert response.decision.action == "NEXT_TOPIC"
    assert response.decision.next_question == next_topic.main_question
    assert response.next_turn.question == next_topic.main_question

    # reload 后必须完全一致（旧实现这里 decision.next_question 会是 null）
    answered = fake.reload_turn(4)
    assert answered["decision"]["next_question"] == next_topic.main_question
    assert fake.reload_turn(response.next_turn.id)["question"] == next_topic.main_question
    assert fake.reload_topic(1)["status"] == TopicStatus.COMPLETED.value
    assert fake.reload_topic(2)["status"] == TopicStatus.ACTIVE.value


async def test_next_topic_transition_success_enhances_both_sides(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)

    async def _ok(*_args, **_kwargs):
        return "消息队列这块先到这。"

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _ok)
    db = _FakeDb()

    response = await _submit(DynamicInterviewService(), db, turn_id=4)

    expected = f"消息队列这块先到这。\n\n{next_topic.main_question}"
    assert response.next_turn.question == expected
    assert response.decision.next_question == expected
    assert expected.endswith(next_topic.main_question), "LLM 不得改写核心问题"

    answered = fake.reload_turn(4)
    assert answered["decision"]["next_question"] == expected
    assert fake.reload_turn(response.next_turn.id)["question"] == expected


# ---------------- Case 3：COACH_RETRY ----------------


async def test_coach_retry_keeps_policy_next_question(monkeypatch):
    session, topic, turns = _build_state(mode="COACH")
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    db = _FakeDb()

    response = await _submit(DynamicInterviewService(), db, turn_id=1, answer=VAGUE_ANSWER)

    assert response.decision.action == "COACH_RETRY"
    # 旧实现会把 Policy 给出的 main_question 覆盖成 None
    assert response.decision.next_question == topic.main_question
    assert response.next_turn.question == topic.main_question

    answered = fake.reload_turn(1)
    assert answered["decision"]["next_question"] == topic.main_question


# ---------------- metric 失败 / Phase 3 失败 ----------------


async def test_metric_flush_failure_rolls_back_and_still_returns_result(monkeypatch):
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    db = _FakeDb(fail_flush_on=1)  # metric 的 flush 失败

    response = await _submit(DynamicInterviewService(), db, turn_id=1)

    assert db.rollbacks >= 1, "metric flush 失败后必须 rollback，否则 session 不可继续使用"
    assert response.decision.action == "FOLLOW_UP"
    assert response.next_turn is not None
    # Phase 1 的 answer 不受影响
    assert fake.reload_turn(1)["answer"] == STRONG_ANSWER


async def test_phase3_failure_falls_back_to_phase1_state(monkeypatch):
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)

    async def _boom(*_args, **_kwargs):
        return "你刚才提到 XADD 写入，那 Consumer Group 的消费位点怎么保证不丢？"

    monkeypatch.setattr(question_realizer, "realize_follow_up", _boom)

    async def _failing_update_turn_question(_db, _turn, _question):
        raise RuntimeError("phase3 write failed")

    monkeypatch.setattr(persistence, "update_turn_question", _failing_update_turn_question)
    db = _FakeDb()

    response = await _submit(DynamicInterviewService(), db, turn_id=1)

    # 不能 500：仍然返回 Phase 1 的兜底追问
    assert response.decision.action == "FOLLOW_UP"
    persisted = fake.reload_turn(response.next_turn.id)["question"]
    assert response.next_turn.question == persisted, "对外返回必须等于库里已提交的状态"
    assert response.decision.next_question == persisted
    assert db.rollbacks >= 1
    assert fake.reload_turn(1)["answer"] == STRONG_ANSWER


# ---------------- 全部失败路径：会话仍可继续 ----------------


async def test_session_remains_usable_after_all_realizer_failures(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _boom)
    service = DynamicInterviewService()

    first = await _submit(service, _FakeDb(), turn_id=4)
    assert first.next_turn is not None

    # 用 Realizer 返回的新 turn 继续回答，链路仍然可执行
    second = await _submit(service, _FakeDb(), turn_id=first.next_turn.id)
    assert second.decision.action in {"FOLLOW_UP", "NEXT_TOPIC", "COACH_RETRY", "END"}
    assert fake.reload_turn(first.next_turn.id)["answer"] is not None


# ---------------- provider 对齐 ----------------


async def test_submit_passes_session_provider_to_follow_up_realizer(monkeypatch):
    session, topic, turns = _build_state()
    session.llm_provider = "custom-provider"
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)

    recorded: dict = {}

    async def _spy(_context, _decision, *, llm_provider=None):
        recorded["provider"] = llm_provider
        return "你刚才提到 XADD，那 Consumer Group 的位点怎么维护？"

    monkeypatch.setattr(question_realizer, "realize_follow_up", _spy)

    await _submit(DynamicInterviewService(), _FakeDb(), turn_id=1)

    assert recorded["provider"] == "custom-provider"


async def test_submit_passes_session_provider_to_transition_realizer(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    session.llm_provider = "custom-provider"
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)

    recorded: dict = {}

    async def _spy(_context, *, llm_provider=None):
        recorded["provider"] = llm_provider
        return ""

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _spy)

    await _submit(DynamicInterviewService(), _FakeDb(), turn_id=4)

    assert recorded["provider"] == "custom-provider"


@pytest.mark.parametrize("provider", ["dashscope", "custom-x"])
async def test_realizer_resolves_chat_model_from_given_provider(monkeypatch, provider):
    recorded: dict = {}

    class _FakeRegistry:
        def get_chat_model(self, name=None):
            recorded["provider"] = name
            return object()

    monkeypatch.setattr("app.common.ai.llm_provider.llm_registry", _FakeRegistry())
    monkeypatch.setattr(question_realizer_module, "structured_output_invoker", _CapturedInvoker())
    monkeypatch.setattr(question_realizer_module, "single_flight", _PassthroughSingleFlight())

    from tests.test_interview_context_realizer import _context, _decision

    await question_realizer.realize_follow_up(_context(), _decision(), llm_provider=provider)

    assert recorded["provider"] == provider


class _CapturedInvoker:
    async def invoke(self, **_kwargs):
        return question_realizer_module._FollowUpQuestionDTO(question="追问？")


class _PassthroughSingleFlight:
    async def __call__(self, _key, fn, **_kwargs):
        return await fn()
