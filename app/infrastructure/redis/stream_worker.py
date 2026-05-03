from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.infrastructure.redis.redis_service import RedisService

logger = logging.getLogger(__name__)

T = TypeVar("T")
MessageHandler = Callable[[dict[str, str]], Awaitable[None]]


class StreamWorker:
    def __init__(
        self,
        *,
        name: str,
        redis_service: RedisService,
        stream_key: str,
        handler: MessageHandler,
        block_ms: int = 5000,
        read_count: int = 1,
        idle_sleep_seconds: float = 1.0,
        error_sleep_seconds: float = 3.0,
    ):
        self._name = name
        self._redis = redis_service
        self._stream_key = stream_key
        self._handler = handler
        self._block_ms = block_ms
        self._read_count = read_count
        self._idle_sleep_seconds = idle_sleep_seconds
        self._error_sleep_seconds = error_sleep_seconds
        self._last_id = "$"
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run_forever(self) -> None:
        logger.info("Starting async worker: %s (stream=%s)", self._name, self._stream_key)
        while not self._stopped:
            try:
                results = await self._redis.xread(
                    {self._stream_key: self._last_id},
                    count=self._read_count,
                    block=self._block_ms,
                )
                if not results:
                    await asyncio.sleep(self._idle_sleep_seconds)
                    continue

                for _stream_name, stream_messages in results:
                    for msg_id, fields in stream_messages:
                        self._last_id = msg_id
                        try:
                            await self._handler(fields)
                            await self._redis.xdel(self._stream_key, msg_id)
                        except Exception:
                            logger.exception("worker %s 处理消息失败: stream=%s, msg_id=%s", self._name, self._stream_key, msg_id)
            except asyncio.CancelledError:
                logger.info("Async worker cancelled: %s", self._name)
                raise
            except TimeoutError:
                logger.warning(
                    "Async worker Redis Stream read timeout, will retry: %s (stream=%s, block_ms=%s)",
                    self._name,
                    self._stream_key,
                    self._block_ms,
                )
                await asyncio.sleep(self._error_sleep_seconds)
            except Exception:
                logger.exception("Async worker runtime error: %s", self._name)
                await asyncio.sleep(self._error_sleep_seconds)
