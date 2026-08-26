"""分布式 single-flight：合并并发重复请求，避免对同一逻辑请求重复调用 LLM。

设计参考 Go 标准库 ``golang.org/x/sync/singleflight`` 的思路，并借鉴 AI-Meeting
（程序员牛肉）的「内容指纹 + Redis 原子锁 + 结果回放」三原语：

1. 内容指纹：同一业务请求（相同题目 + 相同答案等）在任何实例上算出相同的 key；
2. Redis 原子锁：跨实例用 ``SET NX EX`` 抢占 owner，只有 owner 真正执行 fn；
3. 结果回放：owner 的结果写入 Redis 并带 TTL，短时间内到达的重复请求直接回放。

所有 Redis 异常或等待超时都会降级为直接执行 fn，保证调用方一定能拿到结果，
不会因为引入本模块而导致请求失败。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

_RUNNING_PREFIX = "sf:run:"
_RESULT_PREFIX = "sf:res:"

DEFAULT_RUNNING_TTL_SECONDS = 120
DEFAULT_RESULT_TTL_SECONDS = 600
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 30.0


def build_single_flight_key(stage: str, *parts: Any) -> str:
    """用内容指纹构造 single-flight key，保证同一逻辑请求跨实例落到同一 key。

    对输入做 SHA-256，截取 32 位，避免把用户原文（可能很长、含分隔符）直接塞进 key。
    """
    normalized = "|".join("" if p is None else str(p).strip() for p in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    return f"{stage}|{digest}"


async def single_flight(
    key: str,
    fn: Callable[[], Awaitable[str]],
    *,
    running_ttl: int = DEFAULT_RUNNING_TTL_SECONDS,
    result_ttl: int = DEFAULT_RESULT_TTL_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> str:
    """对相同 ``key`` 的并发调用只执行一次 ``fn``，其余请求共享结果。

    ``fn`` 必须返回一个字符串（例如 JSON 序列化后的结果），它会被原样写入 Redis
    并回放给 follower。调用方负责序列化与反序列化。

    极端边界：若 owner 执行耗时超过 ``running_ttl``（默认 120s），锁会自然过期，
    此时可能出现另一个请求接管并重复执行——这等价于「接管」语义，LLM 场景下
    （单次调用通常远小于 120s）几乎不会触发，故不做 token 级 CAS 校验以保持简单。
    """
    redis = await _try_get_redis()
    if redis is None:
        return await fn()

    result_key = f"{_RESULT_PREFIX}{key}"
    running_key = f"{_RUNNING_PREFIX}{key}"

    try:
        cached = await redis.get(result_key)
        if cached:
            return cached

        acquired = await redis.set(running_key, "1", nx=True, ex=running_ttl)
        if acquired:
            try:
                result = await fn()
                await redis.set(result_key, result, ex=result_ttl)
                return result
            finally:
                await redis.delete(running_key)

        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            cached = await redis.get(result_key)
            if cached:
                return cached
            await asyncio.sleep(poll_interval)

        logger.warning("single-flight 等待在途请求超时，降级为直接执行: key=%s", key)
        return await fn()
    except Exception as e:
        logger.warning("single-flight 异常，降级为直接执行: key=%s, error=%s", key, e)
        return await fn()


async def _try_get_redis():
    try:
        from app.infrastructure.redis.redis_service import get_redis

        return await get_redis()
    except Exception as e:
        logger.warning("single-flight 获取 Redis 失败，降级为直接执行: %s", e)
        return None
