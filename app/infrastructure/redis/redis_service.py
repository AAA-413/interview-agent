import asyncio
import logging
import socket
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 5
REDIS_SOCKET_TIMEOUT_SECONDS = 10  # Worker block_ms=5000 需要更长超时
REDIS_MAX_CONNECTIONS = 50  # 连接池大小

_redis: aioredis.Redis | None = None


def _check_port_open(host: str, port: int, timeout: float = 2) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


_redis_available = _check_port_open(settings.redis.host, settings.redis.port)


async def init_redis() -> aioredis.Redis | None:
    global _redis

    if not _redis_available:
        logger.warning("Redis (%s:%s) 不可用，缓存功能将被禁用", settings.redis.host, settings.redis.port)
        return None

    try:
        if _redis is None:
            _redis = aioredis.from_url(
                settings.redis.dsn,
                decode_responses=True,
                max_connections=REDIS_MAX_CONNECTIONS,
                socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
            )
            logger.info(
                "Redis 连接池配置: max_connections=%d, socket_timeout=%ds",
                REDIS_MAX_CONNECTIONS,
                REDIS_SOCKET_TIMEOUT_SECONDS,
            )
        await asyncio.wait_for(_redis.ping(), timeout=5)
        return _redis
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("Redis 连接失败: %s", e)
        _redis = None
        return None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        if not _redis_available:
            raise RuntimeError("Redis 不可用，请先启动 Redis 服务")
        _redis = aioredis.from_url(
            settings.redis.dsn,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


class RedisService:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        await self._redis.set(key, value, ex=ex)

    async def delete(self, *keys: str) -> int:
        return await self._redis.delete(*keys)

    async def exists(self, key: str) -> bool:
        return bool(await self._redis.exists(key))

    async def hset(self, name: str, mapping: dict[str, Any]) -> int:
        return await self._redis.hset(name, mapping=mapping)

    async def hget(self, name: str, key: str) -> str | None:
        return await self._redis.hget(name, key)

    async def hgetall(self, name: str) -> dict[str, str]:
        return await self._redis.hgetall(name)

    async def expire(self, name: str, time: int) -> bool:
        return await self._redis.expire(name, time)

    async def xadd(self, stream: str, fields: dict[str, Any], maxlen: int | None = None) -> str:
        return await self._redis.xadd(stream, fields, maxlen=maxlen)

    async def xread(self, streams: dict[str, str], count: int | None = None, block: int | None = None):
        return await self._redis.xread(streams, count=count, block=block)

    async def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
        noack: bool = False,
    ):
        return await self._redis.xreadgroup(
            groupname,
            consumername,
            streams,
            count=count,
            block=block,
            noack=noack,
        )

    async def xgroup_create(self, stream: str, groupname: str, id: str = "$", mkstream: bool = False) -> bool:
        try:
            await self._redis.xgroup_create(stream, groupname, id=id, mkstream=mkstream)
            return True
        except Exception as e:
            if "BUSYGROUP" in str(e):
                return False
            raise

    async def xack(self, stream: str, groupname: str, *message_ids: str) -> int:
        return await self._redis.xack(stream, groupname, *message_ids)

    async def xdel(self, stream: str, *message_ids: str) -> int:
        return await self._redis.xdel(stream, *message_ids)

    async def xpending_range(
        self,
        stream: str,
        groupname: str,
        min: str = "-",
        max: str = "+",
        count: int = 10,
    ) -> list[dict]:
        """获取 pending list 中的消息详情。"""
        return await self._redis.xpending_range(stream, groupname, min=min, max=max, count=count)

    async def xclaim(
        self,
        stream: str,
        groupname: str,
        consumername: str,
        min_idle_time: int,
        message_ids: list[str],
    ) -> list[tuple[str, dict[str, str]]]:
        """认领空闲超时的消息。"""
        return await self._redis.xclaim(
            stream,
            groupname,
            consumername,
            min_idle_time=min_idle_time,
            message_ids=message_ids,
        )
