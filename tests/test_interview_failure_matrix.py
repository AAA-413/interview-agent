"""PR6：Interview Failure Injection Matrix。

定位
----
**不是**又一套单元测试，而是把 PR1–PR5 的 correctness invariants 集中成一张可执行的
故障注入矩阵：每个场景模拟一个真实的失败点，然后检查**状态**（answer / turn_count /
coverage / best_score / decision / next turn / evaluation_method / confidence），
而不只是「没有抛异常」。

约定
----
- 只 mock **失败点**，不 mock 被测层：业务编排始终真实走 ``submit_turn_answer``。
- 已经被 ``tests/test_dynamic_submit_service.py`` 深度覆盖的场景，这里只保留矩阵级的
  状态断言并在 docstring 里点名对应测试，避免机械复制。

| 场景 | 失败点 | 期望 |
| --- | --- | --- |
| F1 | Evaluator LLM 抛错 | HEURISTIC_FALLBACK / 0.35，answer 落库，topic 推进 |
| F2 | Knowledge Grounding 超时 | ERROR，evaluator 照常跑，answer 落库 |
| F3 | Retriever 运行期异常 | submit 存活，无 grounding |
| F4 | Metric DB commit 失败 | 业务状态完全不变（只 warning） |
| F5 | Coverage reducer 抛错 | score / answer 保留，coverage 保持原状态 |
| F6 | Follow-up Realizer 失败 | 确定性兜底问题，Phase 1 不回滚 |
| F7 | Topic Transition Realizer 失败 | next_turn.question == next_topic.main_question |
| F8 | Realizer metric 失败 | realized wording 仍然生效 |
| F9 | Phase 3 持久化失败 | Phase 1 兜底状态保留 |
| F10 | 重复提交 | 只成功一次，turn_count 不重复 +1 |
| F11 | Stale E0 snapshot | 加锁后 revalidate 拒绝，0 业务提交 |
| F12 | 外部调用被取消 | CancelledError 传播；已提交的 Phase 1 状态不回滚 |
"""

from __future__ import annotations

import asyncio

import pytest

from app.common.exception import BusinessException
from app.modules.interview.dynamic_service import DynamicInterviewService
from app.modules.interview.models import TopicStatus, TurnType
from app.modules.interview.question_realizer import question_realizer
from app.modules.interview.schemas import (
    KNOWLEDGE_GROUNDING_ERROR,
    KnowledgeGroundingDTO,
)
from app.modules.interview.topic_state import tracker as tracker_module
from app.modules.interview.topic_state.tracker import topic_coverage_tracker
from tests.test_dynamic_submit_service import (  # noqa: E402 - 复用既有 submit 测试脚手架
    OTHER_REQUEST_ANSWER,
    STRONG_ANSWER,
    _build_state,
    _FakeDb,
    _FakeSessionFactory,
    _grounding_ready,
    _install,
    _knowledge_topic,
    _make_service,
    _MemoryPersistence,
    _next_topic,
    _patch_db_context,
    _patch_grounding,
    _StubHybridEvaluator,
    _submit,
)


def _knowledge_dimensions_answer() -> str:
    return "Redis MULTI 先把命令入队，EXEC 再统一执行；它不像 MySQL 那样提供失败自动回滚。"


def _state_of(fake: _MemoryPersistence, turn_id: int, topic_id: int = 1) -> dict:
    """一次取回矩阵关心的全部状态（避免每个测试自己散着断言）。"""
    turn = fake.reload_turn(turn_id)
    topic = fake.reload_topic(topic_id)
    return {
        "answer": turn["answer"],
        "ability_score": turn["ability_score"],
        "evaluation_method": turn["evaluation"]["evaluation_method"],
        "confidence": turn["evaluation"]["confidence"],
        "decision_action": turn["decision"]["action"],
        "turn_count": topic["turn_count"],
        "best_score": topic["best_score"],
        "coverage_state": topic["coverage_state"],
    }


# ---------------------------------------------------------------------------
# F1：Evaluator LLM 失败
# ---------------------------------------------------------------------------


async def test_f1_evaluator_failure_falls_back_but_advances_topic(monkeypatch):
    """LLM 语义评分抛错 → HEURISTIC_FALLBACK / 0.35，但 answer 与 topic 状态照常推进。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    evaluator = _StubHybridEvaluator(error=TimeoutError("llm timeout"))
    response = await _submit(_make_service(monkeypatch, evaluator), db, turn_id=1)

    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["evaluation_method"] == "HEURISTIC_FALLBACK"
    assert state["confidence"] == 0.35
    assert "FALLBACK:TimeoutError" in response.evaluation.guard_flags
    assert state["decision_action"] == response.decision.action == "FOLLOW_UP"
    assert state["turn_count"] == 1
    assert state["best_score"] == response.evaluation.ability_score
    # 降级评分仍必须给出下一轮，面试不能断在这里
    assert response.next_turn is not None
    assert response.next_turn.question
    assert db.commits >= 1


# ---------------------------------------------------------------------------
# F2：Knowledge Grounding 超时（KNOWLEDGE）
# ---------------------------------------------------------------------------


async def test_f2_grounding_timeout_does_not_block_submit(monkeypatch):
    """grounding 超时 → submit 成功；semantic evaluator 仍运行；confidence 受 cap 约束。"""
    session, topic, turns = _knowledge_topic(*_build_state())
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    calls: list = []

    async def _timeout(snapshot):
        calls.append(snapshot)
        raise TimeoutError("grounding timeout")

    _patch_grounding(monkeypatch, _timeout)
    evaluator = _StubHybridEvaluator()
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch, evaluator), db, turn_id=1)

    assert calls, "KNOWLEDGE 题必须尝试检索"
    assert evaluator.calls == 1, "grounding 失败后 semantic evaluator 必须继续运行"
    assert evaluator.snapshot.knowledge_grounding is None
    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["decision_action"] == "FOLLOW_UP"
    assert state["confidence"] <= 0.75, "没有 validated grounding，KNOWLEDGE confidence 必须仍被 cap"
    assert response.evaluation.ability_score == state["ability_score"]


async def test_f2b_grounding_error_status_is_isolated_from_score(monkeypatch):
    """grounding 返回 ERROR → 评分与置信度按「无 grounding」语义处理。"""
    session, topic, turns = _knowledge_topic(*_build_state())
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _error(_snapshot):
        return KnowledgeGroundingDTO(status=KNOWLEDGE_GROUNDING_ERROR, error_type="RuntimeError")

    _patch_grounding(monkeypatch, _error)
    evaluator = _StubHybridEvaluator()

    response = await _submit(_make_service(monkeypatch, evaluator), _FakeDb(), turn_id=1)

    assert evaluator.calls == 1
    assert evaluator.snapshot.knowledge_grounding.status == KNOWLEDGE_GROUNDING_ERROR
    assert response.evaluation.confidence <= 0.75
    assert _state_of(fake, 1)["answer"] == STRONG_ANSWER


# ---------------------------------------------------------------------------
# F3：Retriever 运行期异常
# ---------------------------------------------------------------------------


async def test_f3_retriever_runtime_error_keeps_submit_alive(monkeypatch):
    """检索链路整体炸掉也不能影响提交（对应 PR5 §26）。"""
    session, topic, turns = _knowledge_topic(*_build_state())
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _boom(_snapshot):
        raise RuntimeError("vector store down")

    _patch_grounding(monkeypatch, _boom)

    response = await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=1)

    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["evaluation_method"] == "HEURISTIC_FALLBACK"
    assert response.next_turn is not None, "提交必须完整走完 Phase 1"


# ---------------------------------------------------------------------------
# F4：Metric DB 失败（三个 operation 都必须被隔离）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("knowledge", "fail_index", "operation"),
    [
        (False, 1, "ANSWER_EVALUATE"),
        (True, 1, "ANSWER_KNOWLEDGE_RETRIEVE"),
        (True, 2, "ANSWER_EVALUATE"),
    ],
)
async def test_f4_metric_write_failure_is_isolated(monkeypatch, knowledge, fail_index, operation):
    """metric 写失败（flush/commit）不得影响业务状态。

    独立 metric session 的 index：0 = E0 snapshot，之后按调用顺序
    （KNOWLEDGE 时先 ANSWER_KNOWLEDGE_RETRIEVE 再 ANSWER_EVALUATE）。
    """
    session, topic, turns = _build_state()
    if knowledge:
        session, topic, turns = _knowledge_topic(session, topic, turns)
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    db = _FakeDb()

    factory = _FakeSessionFactory(fail_flush_indexes={fail_index})
    _patch_db_context(monkeypatch, factory)
    if knowledge:
        _patch_grounding(monkeypatch, lambda _s: _return(_grounding_ready()))

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert factory.sessions[fail_index].commits == 0, f"{operation} metric 不应被提交"
    assert factory.sessions[fail_index].rollbacks >= 1, f"{operation} metric session 必须回滚/关闭"
    assert db.rollbacks == 0, "metric 失败不能牵连业务 session"
    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["turn_count"] == 1
    assert state["decision_action"] == "FOLLOW_UP"
    assert response.next_turn is not None, "metric 失败不能阻止下一轮创建"


async def _return(value):
    return value


# ---------------------------------------------------------------------------
# F5：Coverage reducer 失败
# ---------------------------------------------------------------------------


async def test_f5_coverage_reducer_failure_preserves_score_and_old_state(monkeypatch):
    """Coverage 局部异常 → score / answer 保留，coverage 保持原状态（PR3 失败域分离）。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    def _boom(**_kwargs):
        raise RuntimeError("coverage reducer exploded")

    monkeypatch.setattr(topic_coverage_tracker, "update", _boom)

    response = await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=1)

    state = _state_of(fake, 1)
    # score 与 answer 完全保留
    assert state["answer"] == STRONG_ANSWER
    assert state["ability_score"] == response.evaluation.ability_score
    assert state["decision_action"] in {"FOLLOW_UP", "NEXT_TOPIC", "COACH_RETRY", "END"}
    # coverage 没有被写坏：落库的是「原状态」（初始状态的 points 全为 NOT_COVERED）
    persisted = state["coverage_state"]
    assert persisted is not None, "coverage 状态仍应落库（保持原状态，而不是不写）"
    assert persisted["points"], "初始 coverage 状态应包含 canonical targets"
    assert all(point["status"] == "NOT_COVERED" for point in persisted["points"].values())
    assert persisted["covered_keys"] == []
    assert tracker_module is not None  # 保持 import 显式，避免 lint 误删


# ---------------------------------------------------------------------------
# F6：Follow-up Realizer 失败
# ---------------------------------------------------------------------------


async def test_f6_follow_up_realizer_failure_uses_deterministic_fallback(monkeypatch):
    """Realizer 失败 → 确定性兜底问题；Phase 1 已提交的状态不回滚。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _fail(*_args, **_kwargs):
        return None

    monkeypatch.setattr(question_realizer, "realize_follow_up", _fail)
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert response.decision.action == "FOLLOW_UP"
    assert response.next_turn is not None
    assert response.next_turn.question, "必须有确定性兜底问题"
    assert response.next_turn.question == response.decision.next_question
    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["turn_count"] == 1
    assert db.commits >= 1, "Phase 1 提交必须完成"


# ---------------------------------------------------------------------------
# F7：Topic Transition Realizer 失败
# ---------------------------------------------------------------------------


async def test_f7_topic_transition_failure_keeps_canonical_main_question(monkeypatch):
    """NEXT_TOPIC 时转场语失败 → 下一题必须等于 next_topic.main_question。

    与 ``test_next_topic_transition_failure_keeps_main_question_everywhere`` 同源，
    这里补一条矩阵级断言：Phase 1 的 decision 与 Phase 3 的 turn 都不得被 LLM 改写。
    """
    session, topic, turns = _build_state(current_turn_type=TurnType.FOLLOW_UP.value)
    next_topic = _next_topic()
    fake = _MemoryPersistence(session, [topic, next_topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _fail(*_args, **_kwargs):
        return None

    monkeypatch.setattr(question_realizer, "realize_topic_transition", _fail)

    response = await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=4)

    assert response.decision.action == "NEXT_TOPIC"
    assert response.next_turn.question == next_topic.main_question
    assert fake.reload_turn(response.next_turn.id)["question"] == next_topic.main_question
    assert fake.reload_turn(4)["decision"]["next_question"] == next_topic.main_question
    assert fake.reload_topic(1)["status"] == TopicStatus.COMPLETED.value
    assert fake.reload_topic(2)["status"] == TopicStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# F8：Realizer metric 失败
# ---------------------------------------------------------------------------


async def test_f8_realizer_metric_failure_keeps_realized_wording(monkeypatch):
    """LLM 成功但 metric 写失败 → 仍然使用 realized wording（metric 不影响 correctness）。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)

    # index 0 = snapshot，index 1 = ANSWER_EVALUATE metric，index 2 = FOLLOW_UP_REALIZE metric
    factory = _FakeSessionFactory(fail_flush_indexes={2})
    _patch_db_context(monkeypatch, factory)

    realized = "你提到 XADD 写入，那 Consumer Group 的消费位点怎么保证不丢？"

    async def _ok(*_args, **_kwargs):
        return realized

    monkeypatch.setattr(question_realizer, "realize_follow_up", _ok)

    response = await _submit(_make_service(monkeypatch), _FakeDb(), turn_id=1)

    assert factory.sessions[2].commits == 0, "realizer metric session 应写失败"
    assert response.next_turn.question == realized, "metric 失败不能让系统丢弃 LLM 措辞"
    assert fake.reload_turn(response.next_turn.id)["question"] == realized


# ---------------------------------------------------------------------------
# F9：Phase 3 持久化失败
# ---------------------------------------------------------------------------


async def test_f9_phase3_persistence_failure_keeps_phase1_state(monkeypatch):
    """Phase 3 写失败 → 回落到 Phase 1 兜底状态。

    与 ``test_phase3_failure_falls_back_to_phase1_state`` 同源；这里补矩阵级断言：
    answer / evaluation / turn_count 全部保持 Phase 1 值。
    """
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _enhanced(*_args, **_kwargs):
        return "这是被增强过的追问措辞。"

    monkeypatch.setattr(question_realizer, "realize_follow_up", _enhanced)

    async def _failing_update(_db, _turn, _question):
        raise RuntimeError("phase3 write failed")

    monkeypatch.setattr(
        "app.modules.interview.dynamic_service.dynamic_interview_persistence_service.update_turn_question",
        _failing_update,
    )

    db = _FakeDb()
    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["turn_count"] == 1
    assert state["decision_action"] == "FOLLOW_UP"
    assert response.next_turn is not None
    assert response.next_turn.question, "Phase 3 失败后必须回落到 Phase 1 的兜底问题"
    assert db.rollbacks >= 1, "Phase 3 写失败应触发 rollback"


# ---------------------------------------------------------------------------
# F10 / F11：重复提交与 stale snapshot
# ---------------------------------------------------------------------------


async def test_f10_duplicate_submit_does_not_double_count(monkeypatch):
    """重复提交（同 turn）→ 只成功一次：不重复 +1 turn_count、不创建第二个 turn。

    深度断言见 ``test_concurrent_submit_is_rejected_after_lock`` 与
    ``test_concurrent_submit_does_not_double_write_coverage``；这里补「不重复建 turn」。
    """
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    turns_before = len(fake.turns)

    async def _on_call(_snapshot, _answer):
        fake.answer_submitted_by_other = True

    db = _FakeDb()
    with pytest.raises(BusinessException):
        await _submit(_make_service(monkeypatch, _StubHybridEvaluator(on_call=_on_call)), db, turn_id=1)

    assert len(fake.turns) == turns_before, "被拒绝的重复提交不得创建新 turn"
    assert fake.turns[1].answer == OTHER_REQUEST_ANSWER
    assert db.commits == 0
    assert fake.coverage_writes == 0


async def test_f11_stale_snapshot_is_revalidated_after_lock(monkeypatch):
    """E0 读到未作答 → evaluation 期间被别的请求提交 → Phase 1 加锁后必须拒绝。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())

    async def _on_call(_snapshot, _answer):
        fake.answer_submitted_by_other = True

    db = _FakeDb()
    with pytest.raises(BusinessException):
        await _submit(_make_service(monkeypatch, _StubHybridEvaluator(on_call=_on_call)), db, turn_id=1)

    assert fake.lock_reads == 1, "必须走一次 FOR UPDATE 加锁重读"
    assert fake.topic_lock_reads == 0, "发现 answer 已存在时必须在此之前中止（不得锁 topic）"
    assert db.commits == 0
    assert fake.topics[1].turn_count in (None, 0), "被拒绝时 topic 不得被推进"


# ---------------------------------------------------------------------------
# F12：外部调用被取消
# ---------------------------------------------------------------------------


async def test_f12_cancellation_propagates_and_does_not_roll_back_committed_phase1(monkeypatch):
    """Phase 2 被取消：异常照常传播，但 Phase 1 已提交的状态不得回滚。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    async def _cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(question_realizer, "realize_follow_up", _cancelled)

    with pytest.raises(asyncio.CancelledError):
        await _submit(_make_service(monkeypatch), db, turn_id=1)

    # Phase 1 已经提交：answer / topic 状态 / 下一轮兜底 turn 都必须还在
    state = _state_of(fake, 1)
    assert state["answer"] == STRONG_ANSWER
    assert state["turn_count"] == 1
    assert state["decision_action"] == "FOLLOW_UP"
    assert db.commits == 1, "取消只能发生在 Phase 1 提交之后"
    assert db.rollbacks == 0, "已提交的 Phase 1 状态不得被回滚"


async def test_f12b_realizer_cancellation_is_not_swallowed(monkeypatch):
    """``_run_realizer_outside_transaction`` 只吞 Exception，CancelledError 必须向上传播。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    factory = _FakeSessionFactory()
    _patch_db_context(monkeypatch, factory)

    service = DynamicInterviewService()

    async def _cancelled():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service._run_realizer_outside_transaction(session, "FOLLOW_UP_REALIZE", _cancelled, topic_id=1, turn_id=1)

    assert factory.sessions == [], "取消时不得再写 metric（也不应留下悬挂 session）"


# ---------------------------------------------------------------------------
# Phase 1 原子性
# ---------------------------------------------------------------------------


async def test_phase1_midway_failure_commits_nothing(monkeypatch):
    """Phase 1 中途抛异常 → 0 次 commit（不存在 half-commit）。"""
    session, topic, turns = _build_state()
    db_writes: list[int] = []

    class _RecordingPersistence(_MemoryPersistence):
        """记录 Phase 1 各写操作落在哪个 session 对象上。"""

        async def save_turn_answer(self, _db, *args, **kwargs):
            db_writes.append(id(_db))
            return await super().save_turn_answer(_db, *args, **kwargs)

        async def update_topic_after_answer(self, _db, *args, **kwargs):
            db_writes.append(id(_db))
            return await super().update_topic_after_answer(_db, *args, **kwargs)

        async def create_turn(self, _db, **kwargs):
            db_writes.append(id(_db))
            raise RuntimeError("phase1 exploded while creating next turn")

    fake = _RecordingPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    with pytest.raises(RuntimeError, match="phase1 exploded"):
        await _submit(_make_service(monkeypatch), db, turn_id=1)

    assert db.commits == 0, "Phase 1 中途失败绝不能产生提交"
    assert len(db_writes) == 3, "save_turn_answer / update_topic_after_answer / create_turn 都应被调用"
    assert set(db_writes) == {id(db)}, "Phase 1 的所有写操作必须落在同一个业务 session 上（单次 rollback 即原子）"


# ---------------------------------------------------------------------------
# §93：Phase 1 golden state snapshot
# ---------------------------------------------------------------------------


async def test_phase1_golden_state_is_self_consistent(monkeypatch):
    """一次 FOLLOW_UP 提交后，commit 出来的是一份自洽 snapshot。"""
    session, topic, turns = _build_state()
    fake = _MemoryPersistence(session, [topic], turns)
    _install(monkeypatch, fake)
    _patch_db_context(monkeypatch, _FakeSessionFactory())
    db = _FakeDb()

    response = await _submit(_make_service(monkeypatch), db, turn_id=1)

    turn = fake.reload_turn(1)
    topic_dto = fake.reload_topic(1)
    next_turn = fake.reload_turn(response.next_turn.id)

    # turn
    assert turn["answer"] == STRONG_ANSWER
    assert turn["ability_score"] == response.evaluation.ability_score
    assert turn["evaluation"]["ability_score"] == response.evaluation.ability_score
    assert turn["decision"]["action"] == "FOLLOW_UP"
    # topic
    assert topic_dto["turn_count"] == 1
    assert topic_dto["best_score"] == response.evaluation.ability_score
    assert topic_dto["final_score"] == response.evaluation.ability_score
    assert topic_dto["status"] == TopicStatus.ACTIVE.value
    assert topic_dto["coverage_state"] is not None
    # next turn：Phase 1 兜底问题与 Phase 2/3 的最终问题在成功路径下一致
    assert next_turn["turn_type"] == TurnType.FOLLOW_UP.value
    assert next_turn["turn_order"] == 2
    assert next_turn["question"] == response.next_turn.question
    # 未作答的下一轮不得带答案
    assert next_turn["answer"] is None
