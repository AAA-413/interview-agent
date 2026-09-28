"""DynamicInterviewService.submit_turn_answer() 的 service-level 测试。

用内存版 persistence（只替换 DB 访问方法，DTO 转换仍用真实实现）+ stub evaluator
驱动完整主流程，覆盖：

- FOLLOW_UP / NEXT_TOPIC / COACH_RETRY 三种 action 的 persisted next_question
- Realizer / transition 失败后 reload 一致性
- metric（独立 session）成功 / 失败路径
- Phase 3 落库失败 → 回落 Phase 1 状态
- **PR2 新增**：Evaluation 期间不持有业务 DB transaction / 不持锁 / 不写 answer
- **PR2 新增**：并发 stale submit → 加锁重读后拒绝重复提交且不覆盖旧答案
- **PR2 新增**：evaluation_method / confidence / evidence / guard_flags 持久化 roundtrip
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.common.exception import BusinessException
from app.modules.interview.dynamic_persistence_service import dynamic_interview_persistence_service as persistence
from app.modules.interview.dynamic_service import (
    DynamicAnswerEvaluationService,
    DynamicInterviewService,
    StrictInterviewPolicy,
)
from app.modules.interview.evaluation.hybrid_evaluator import HybridEvaluationOutcome
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
OTHER_REQUEST_ANSWER = "另一个并发请求已经提交的回答内容，长度足够通过校验。"


class _FakeDb:
    """业务 session 替身：记录 commit / rollback / flush。

    ``on_rollback`` 用来模拟 SQLAlchemy rollback 对 ORM 对象的 expire 效果：
    回调把实体属性改成哨兵值，任何「rollback 之后还读 ORM」的代码都会露馅。
    """

    def __init__(self, *, on_rollback=None):
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.entities: list[object] = []
        self._on_rollback = on_rollback

    def add(self, entity):
        self.entities.append(entity)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1
        if self._on_rollback is not None:
            self._on_rollback()


class _FakeAuxSession:
    """snapshot / metric 用的独立 session 替身。"""

    def __init__(self, *, fail_flush: bool = False):
        self._fail_flush = fail_flush
        self.entities: list[object] = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0

    def add(self, entity):
        self.entities.append(entity)

    async def flush(self):
        self.flushes += 1
        if self._fail_flush:
            raise RuntimeError("flush failed")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _FakeSessionContext:
    """模拟 ``async with get_db_context() as session``。

    ``fail_flush_index`` 用于让「第 N 个被打开的 session」的 flush 失败，
    以便单独测试 metric 写失败路径。
    """

    def __init__(self, factory: "_FakeSessionFactory"):
        self._factory = factory

    async def __aenter__(self):
        session = _FakeAuxSession(fail_flush=self._factory.should_fail(self._factory.opened))
        self._factory.opened += 1
        self._factory.sessions.append(session)
        return session

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is not None:
            self._factory.sessions[-1].rollbacks += 1
        return False


class _FakeSessionFactory:
    """每次 get_db_context() 打开一个全新的独立 session。"""

    def __init__(self, fail_flush_indexes: set[int] | None = None):
        self.sessions: list[_FakeAuxSession] = []
        self.opened = 0
        self._fail_indexes = fail_flush_indexes or set()

    def should_fail(self, index: int) -> bool:
        return index in self._fail_indexes

    def __call__(self):
        return _FakeSessionContext(self)


def _patch_db_context(monkeypatch, factory: _FakeSessionFactory) -> None:
    monkeypatch.setattr("app.database.get_db_context", factory)


class _MemoryPersistence:
    """内存版 persistence：只覆盖 submit_turn_answer 用到的 DB 访问方法。"""

    def __init__(
        self,
        session: InterviewSessionEntity,
        topics: list[InterviewTopicEntity],
        turns: list[InterviewTurnEntity],
    ):
        self.session = session
        self.topics = {topic.id: topic for topic in topics}
        self.turns = {turn.id: turn for turn in turns}
        self._next_turn_id = max(self.turns) + 1
        # PR2：模拟「另一个请求在 LLM evaluation 期间提交了同一轮」
        self.answer_submitted_by_other = False
        self.lock_reads = 0
        self.metric_calls: list[dict] = []

    # ---- DB 访问 ----
    async def find_session_or_throw(self, _db, _session_id, _user_id=None):
        return self.session

    async def find_turn_or_throw(self, _db, turn_id, _session_entity_id, _user_id=None):
        return self.turns[turn_id]

    async def find_turn_for_update_or_throw(self, _db, turn_id, _session_entity_id, _user_id=None):
        self.lock_reads += 1
        turn = self.turns[turn_id]
        if self.answer_submitted_by_other:
            turn.answer = OTHER_REQUEST_ANSWER
        return turn

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
        self,
        _db,
        turn,
        *,
        answer,
        ability_score,
        feedback,
        signals,
        evaluation,
        decision_action,
        decision,
        coach_hint,
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
        # 注意：add() 是同步方法，不能 await（否则会 TypeError 并把所有用例
        # 静默推到 metric failure 分支，造成假通过）。
        self.metric_calls.append(kwargs)
        db.add(object())
        await db.flush()

    # ---- reload（等价于 GET /dynamic-sessions/{id}） ----
    def reload_turn(self, turn_id: int) -> dict:
        return persistence.turn_to_dto(self.turns[turn_id]).model_dump()

    def reload_topic(self, topic_id: int) -> dict:
        return persistence.topic_to_dto(self.topics[topic_id]).model_dump()


class _StubHybridEvaluator:
    """可控的 evaluator 替身：默认返回 heuristic fallback（不触发任何 LLM 调用）。"""

    def __init__(self, *, outcome=None, on_call=None, error: Exception | None = None):
        self._outcome = outcome
        self._on_call = on_call
        self._error = error
        self.snapshot = None
        self.llm_provider: str | None = None
        self.calls = 0

    async def evaluate(self, snapshot, answer, *, llm_provider=None):
        self.calls += 1
        self.snapshot = snapshot
        self.llm_provider = llm_provider
        if self._on_call is not None:
            await self._on_call(snapshot, answer)
        if self._error is not None:
            raise self._error
        if self._outcome is not None:
            return self._outcome
        heuristic = DynamicAnswerEvaluationService().evaluate(
            snapshot.topic, snapshot.turn, answer, snapshot.previous_turns
        )
        return HybridEvaluationOutcome(
            evaluation=heuristic.model_copy(update={"evaluation_method": "HEURISTIC_FALLBACK", "confidence": 0.35}),
            llm_attempted=False,
        )


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _build_state(*, mode: str = "STRICT", current_turn_type: str = TurnType.MAIN.value):
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
    fake_persistence.metric_calls = []
    for name in (
        "find_session_or_throw",
        "find_turn_or_throw",
        "find_turn_for_update_or_throw",
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


def _make_service(monkeypatch, evaluator: _StubHybridEvaluator | None = None) -> DynamicInterviewService:
    service = DynamicInterviewService()
    service.hybrid_evaluator = evaluator or _StubHybridEvaluator()
    return service


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
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _timeout(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(question_realizer, "realize_follow_up", _timeout)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert response.decision.action == "FOLLOW_UP"
    expected = response.next_turn.question
    assert response.decision.next_question == expected

    answered = fake.reload_turn(1)
    assert answered["answer"] == STRONG_ANSWER
    assert answered["decision"]["next_question"] == expected
    assert fake.reload_turn(response.next_turn.id)["question"] == expected
    # 落库前加锁重读一次，避免慢 LLM 放大重复提交 race
    assert fake.lock_reads >= 1


# ---------------- Case 2：NEXT_TOPIC + transition failure ----------------


async def test_next_topic_transition_failure_keeps_main_question_everywhere(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _fail(*_args, **_kwargs):
        return None

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _fail)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=4)

    assert response.decision.action == "NEXT_TOPIC"
    assert response.decision.next_question == next_topic.main_question
    assert response.next_turn.question == next_topic.main_question

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
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _ok(*_args, **_kwargs):
        return "消息队列这块先到这。"

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _ok)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=4)

    expected = f"消息队列这块先到这。\n\n{next_topic.main_question}"
    assert response.next_turn.question == expected
    assert response.decision.next_question == expected
    assert expected.endswith(next_topic.main_question), "LLM 不得改写核心问题"
    assert fake.reload_turn(4)["decision"]["next_question"] == expected


# ---------------- Case 3：COACH_RETRY ----------------


async def test_coach_retry_keeps_policy_next_question(monkeypatch):
    session, topic, turns = _build_state(mode="COACH")
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1, answer=VAGUE_ANSWER)

    assert response.decision.action == "COACH_RETRY"
    assert response.decision.next_question == topic.main_question
    assert response.next_turn.question == topic.main_question
    assert fake.reload_turn(1)["decision"]["next_question"] == topic.main_question


# ---------------- metric：独立 session，成功 / 失败两条路径 ----------------


async def test_metric_success_path_uses_dedicated_sessions(monkeypatch):
    """snapshot 与 metric 都走独立 session；metric flush 真正执行。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    factory = _FakeSessionFactory()
    _patch_db_context(monkeypatch, factory)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    metric_sessions = [item for item in factory.sessions if item.entities]
    assert metric_sessions, "metric 必须写入独立 session"
    assert all(item.flushes >= 1 for item in metric_sessions)
    assert all(item.commits >= 1 for item in metric_sessions)
    assert all(item.rollbacks == 0 for item in metric_sessions)
    assert db.rollbacks == 0
    assert {call["operation_type"] for call in fake.metric_calls} >= {"ANSWER_EVALUATE", "FOLLOW_UP_REALIZE"}
    assert response.decision.action == "FOLLOW_UP"
    # stub evaluator 没有真正调用 LLM，因此不应写 ANSWER_EVALUATE_LLM
    assert "ANSWER_EVALUATE_LLM" not in {call["operation_type"] for call in fake.metric_calls}


async def test_llm_evaluator_metric_separates_success_and_failure(monkeypatch):
    """LLM 评分失败但提交成功：metric success=false，HTTP submit 仍然成功。"""
    from app.modules.interview.schemas import DynamicTurnEvaluationDTO

    fallback = DynamicTurnEvaluationDTO(
        ability_score=58,
        feedback="回答偏泛。",
        signals={"strengths": [], "gaps": ["缺少实现细节"], "risks": []},
        dimension_scores={"authenticity": 58, "technical_depth": 58, "communication_structure": 58},
        evaluation_method="HEURISTIC_FALLBACK",
        confidence=0.35,
        guard_flags=["FALLBACK:TimeoutError"],
    )
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    evaluator = _StubHybridEvaluator(
        outcome=HybridEvaluationOutcome(evaluation=fallback, llm_attempted=True, llm_error="TimeoutError")
    )

    response = await _submit(_make_service(monkeypatch, evaluator), _FakeDb(), turn_id=1)

    llm_metrics = [call for call in fake.metric_calls if call["operation_type"] == "ANSWER_EVALUATE_LLM"]
    assert len(llm_metrics) == 1
    assert llm_metrics[0]["success"] is False
    assert llm_metrics[0]["error_type"] == "TimeoutError"
    # 提交本身成功
    assert response.evaluation.evaluation_method == "HEURISTIC_FALLBACK"
    assert fake.reload_turn(1)["answer"] == STRONG_ANSWER


async def test_metric_flush_failure_does_not_touch_business_session(monkeypatch):
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    # index 0 = snapshot，index 1 = ANSWER_EVALUATE metric → 让它失败
    factory = _FakeSessionFactory(fail_flush_indexes={1})
    _patch_db_context(monkeypatch, factory)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert factory.sessions[1].rollbacks >= 1, "metric session 必须被回滚/关闭"
    assert factory.sessions[1].commits == 0
    assert db.rollbacks == 0, "业务 session 不能被 metric 写失败牵连"
    assert response.decision.action == "FOLLOW_UP"
    assert fake.reload_turn(1)["answer"] == STRONG_ANSWER


async def test_phase3_failure_falls_back_to_phase1_state(monkeypatch):
    """Phase 3 写失败 → rollback → 不再读 ORM → 正常返回 Phase 1 状态。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    enhanced = "你刚才提到 XADD 写入，那 Consumer Group 的消费位点怎么保证不丢？"

    async def _enhanced(*_args, **_kwargs):
        return enhanced

    monkeypatch.setattr(question_realizer, "realize_follow_up", _enhanced)

    async def _failing_update_turn_question(_db, turn_entity, question):
        turn_entity.question = question
        raise RuntimeError("phase3 write failed")

    monkeypatch.setattr(persistence, "update_turn_question", _failing_update_turn_question)

    topic_dto = persistence.topic_to_dto(topic)
    turn_dto = persistence.turn_to_dto(turns[0])
    evaluation = DynamicAnswerEvaluationService().evaluate(topic_dto, turn_dto, STRONG_ANSWER, [])
    expected_fallback = StrictInterviewPolicy._followup_question(topic_dto, evaluation, followup_number=1)

    def _expire_orm_state():
        session.status = "__expired__"
        session.session_id = "__expired__"
        topic.max_turns = -1
        topic.best_score = -1
        topic.final_score = -1
        turns[0].id = -1

    db = _FakeDb(on_rollback=_expire_orm_state)

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert response.decision.action == "FOLLOW_UP"
    assert response.next_turn.question == expected_fallback
    assert response.next_turn.question != enhanced, "rollback 后不得使用未落库的 enhancement"
    assert response.decision.next_question == expected_fallback
    assert response.status == SessionStatus.INTERVIEWING.value
    assert response.topic_progress["max_turns"] == 3
    assert db.rollbacks >= 1


# ---------------- PR2：DB transaction boundary ----------------


async def test_evaluation_does_not_hold_business_transaction(monkeypatch):
    """LLM evaluation 期间：不写业务 session、不持 row lock、不 flush answer。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    started = asyncio.Event()
    release = asyncio.Event()
    observed: dict = {}

    async def _on_call(_snapshot, _answer):
        observed["business_commits"] = db.commits
        observed["business_flushes"] = db.flushes
        observed["business_entities"] = len(db.entities)
        observed["row_lock_reads"] = fake.lock_reads
        observed["answer_persisted"] = fake.turns[1].answer
        started.set()
        await release.wait()

    evaluator = _StubHybridEvaluator(on_call=_on_call)
    service = _make_service(monkeypatch, evaluator)

    task = asyncio.create_task(_submit(service, db, turn_id=1))
    await started.wait()
    await asyncio.sleep(0)
    # 此刻 evaluator 正在「等待 LLM」，业务侧必须完全干净
    assert observed == {
        "business_commits": 0,
        "business_flushes": 0,
        "business_entities": 0,
        "row_lock_reads": 0,
        "answer_persisted": None,
    }
    assert fake.turns[1].answer is None

    release.set()
    response = await task
    assert response.decision.action == "FOLLOW_UP"
    assert fake.turns[1].answer == STRONG_ANSWER
    assert fake.lock_reads == 1, "加锁重读只能发生在 evaluation 之后"


async def test_evaluation_receives_snapshot_and_session_provider(monkeypatch):
    session, topic, turns = _build_state()
    session.llm_provider = "custom-provider"
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    evaluator = _StubHybridEvaluator()
    await _submit(_make_service(monkeypatch, evaluator), _FakeDb(), turn_id=1)

    assert evaluator.llm_provider == "custom-provider"
    assert evaluator.snapshot.session_id == "svc-session"
    assert evaluator.snapshot.topic.topic_key == "async_task_pipeline"
    assert evaluator.snapshot.turn.id == 1
    assert evaluator.snapshot.turn.answer is None, "snapshot 拿到的是未作答状态"


# ---------------- PR2：并发 / stale submit ----------------


async def test_concurrent_submit_is_rejected_after_lock(monkeypatch):
    """snapshot 读到未作答，evaluation 期间被别的请求提交 → 加锁后必须拒绝且不覆盖。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _on_call(_snapshot, _answer):
        fake.answer_submitted_by_other = True

    evaluator = _StubHybridEvaluator(on_call=_on_call)
    db = _FakeDb()

    with pytest.raises(BusinessException) as exc:
        await _submit(_make_service(monkeypatch, evaluator), db, turn_id=1)

    assert "已提交" in str(exc.value)
    assert fake.turns[1].answer == OTHER_REQUEST_ANSWER, "不得覆盖另一个请求已提交的答案"
    assert db.commits == 0, "重复提交不应产生任何业务提交"


# ---------------- PR2：evaluation 字段持久化 roundtrip ----------------


async def test_evaluation_metadata_roundtrip(monkeypatch):
    from app.modules.interview.schemas import DynamicTurnEvaluationDTO, EvaluationEvidenceDTO

    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    evaluation = DynamicTurnEvaluationDTO(
        ability_score=77,
        feedback="回答有基础，但还需要补证据和边界。",
        signals={"strengths": ["实现细节扎实"], "gaps": ["缺少指标口径"], "risks": []},
        dimension_scores={"authenticity": 80, "technical_depth": 78, "communication_structure": 72},
        evaluation_method="HYBRID_LLM",
        confidence=0.8,
        evidence=[
            EvaluationEvidenceDTO(
                dimension="technical_depth",
                quote="每个任务带唯一 message_id 做幂等",
                assessment="SUPPORT",
            )
        ],
        guard_flags=[],
    )
    evaluator = _StubHybridEvaluator(outcome=HybridEvaluationOutcome(evaluation=evaluation, llm_attempted=True))

    response = await _submit(_make_service(monkeypatch, evaluator), _FakeDb(), turn_id=1)

    assert response.evaluation.evaluation_method == "HYBRID_LLM"
    reloaded = fake.reload_turn(1)["evaluation"]
    assert reloaded["evaluation_method"] == "HYBRID_LLM"
    assert reloaded["confidence"] == 0.8
    assert reloaded["evidence"][0]["quote"] == "每个任务带唯一 message_id 做幂等"
    assert reloaded["dimension_scores"] == {
        "authenticity": 80,
        "technical_depth": 78,
        "communication_structure": 72,
    }
    assert "guard_flags" in reloaded
    # 旧 evaluation_json（没有新字段）仍可解析
    legacy = DynamicTurnEvaluationDTO(**{"ability_score": 60, "feedback": "old"})
    assert legacy.evaluation_method == "HEURISTIC_FALLBACK"
    assert legacy.confidence == 0.0


async def test_session_remains_usable_after_all_realizer_failures(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _boom)
    service = _make_service(monkeypatch)

    first = await _submit(service, _FakeDb(), turn_id=4)
    assert first.next_turn is not None

    second = await _submit(service, _FakeDb(), turn_id=first.next_turn.id)
    assert second.decision.action in {"FOLLOW_UP", "NEXT_TOPIC", "COACH_RETRY", "END"}
    assert fake.reload_turn(first.next_turn.id)["answer"] is not None


async def test_submit_passes_session_provider_to_realizers(monkeypatch):
    session, topic, turns = _build_state()
    session.llm_provider = "custom-provider"
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    recorded: dict = {}

    async def _spy(_context, _decision, *, llm_provider=None):
        recorded["provider"] = llm_provider
        return "你刚才提到 XADD，那 Consumer Group 的位点怎么维护？"

    monkeypatch.setattr(question_realizer, "realize_follow_up", _spy)

    await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=1)

    assert recorded["provider"] == "custom-provider"


async def test_submit_passes_session_provider_to_transition_realizer(monkeypatch):
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    session.llm_provider = "custom-provider"
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    recorded: dict = {}

    async def _spy(_context, *, llm_provider=None):
        recorded["provider"] = llm_provider
        return ""

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _spy)

    await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=4)

    assert recorded["provider"] == "custom-provider"
