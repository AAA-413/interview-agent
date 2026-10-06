import asyncio

import pytest

from app.common.single_flight import build_single_flight_key, single_flight
from app.modules.interview.question_service import interview_question_service


class _FakeRedis:
    """模拟 redis.asyncio 的最小实现，覆盖 single_flight 用到的 set/get/delete。"""

    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                count += 1
        return count


def test_build_single_flight_key_is_deterministic():
    a = build_single_flight_key("followup", "题目", "答案", "knowledge", 0)
    b = build_single_flight_key("followup", "题目", "答案", "knowledge", 0)
    assert a == b
    assert a.startswith("followup|")


def test_build_single_flight_key_differs_on_input():
    a = build_single_flight_key("followup", "题目", "答案", "knowledge", 0)
    b = build_single_flight_key("followup", "题目", "另一份答案", "knowledge", 0)
    assert a != b


def test_giveup_answer_detection():
    assert interview_question_service._is_giveup_answer("不会")
    assert interview_question_service._is_giveup_answer("不知道")
    assert interview_question_service._is_giveup_answer("   ")  # 空白
    assert interview_question_service._is_giveup_answer(None)
    assert interview_question_service._is_giveup_answer("pass")
    assert not interview_question_service._is_giveup_answer(
        "这里是我对 Redis 持久化机制的理解，RDB 和 AOF 的区别在于……"  # 长回答不短路
    )
    assert not interview_question_service._is_giveup_answer(
        "我不会这道题的完整答案，但我知道它和缓存一致性有关"  # 超过阈值长度交给 LLM
    )


async def test_single_flight_merges_concurrent_calls(monkeypatch):
    fake = _FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return '{"result": "ok"}'

    results = await asyncio.gather(
        single_flight("merge|test", fn, poll_interval=0.01, wait_timeout=2),
        single_flight("merge|test", fn, poll_interval=0.01, wait_timeout=2),
        single_flight("merge|test", fn, poll_interval=0.01, wait_timeout=2),
    )

    assert results == ['{"result": "ok"}'] * 3
    assert calls == 1


async def test_single_flight_replays_cached_result_without_calling_fn(monkeypatch):
    fake = _FakeRedis()
    fake._store["sf:res:replay|test"] = '{"cached": true}'

    async def fake_get_redis():
        return fake

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "should-not-run"

    result = await single_flight("replay|test", fn)
    assert result == '{"cached": true}'
    assert calls == 0


async def test_single_flight_does_not_rerun_failed_fn(monkeypatch):
    """fn 自身失败（LLM 超时等）不能触发降级重跑，否则同一请求会重复调用模型。"""
    fake = _FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise RuntimeError("LLM timeout")

    try:
        await single_flight("fail|test", fn)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("异常应向上抛出")

    assert calls == 1


async def test_single_flight_releases_lock_when_owner_cancelled(monkeypatch):
    """owner 拿到锁后被 cancel，running key 必须被清理（不能留下悬挂锁）。"""
    fake = _FakeRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)

    started = asyncio.Event()

    async def fn():
        started.set()
        await asyncio.sleep(30)
        return "never"

    task = asyncio.create_task(single_flight("cancel|test", fn))
    await started.wait()
    await asyncio.sleep(0)  # 让 owner 进入 await fn()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "sf:run:cancel|test" not in fake._store, "取消后 running lock 必须被删除"
    assert "sf:res:cancel|test" not in fake._store


async def test_single_flight_cleanup_error_does_not_mask_fn_error(monkeypatch):
    """cleanup 自身异常不能覆盖 fn 抛出的原始异常。"""

    class _BrokenDeleteRedis(_FakeRedis):
        async def delete(self, *keys):
            raise RuntimeError("redis delete failed")

    fake = _BrokenDeleteRedis()

    async def fake_get_redis():
        return fake

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise ValueError("llm boom")

    with pytest.raises(ValueError, match="llm boom"):
        await single_flight("cleanup|test", fn)

    assert calls == 1


async def test_single_flight_falls_back_when_redis_unavailable(monkeypatch):
    async def fake_get_redis():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.infrastructure.redis.redis_service.get_redis", fake_get_redis)

    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "direct"

    result = await single_flight("fallback|test", fn)
    assert result == "direct"
    assert calls == 1
