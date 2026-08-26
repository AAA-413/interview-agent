"""WebSocket 流式 STT 服务，基于 FunASR (SenseVoice-Small)。

设计要点：
- Lazy singleton + 线程安全双检锁：FunASR 模型 (~230MB) 只加载一次
- 进程内运行：不开独立 funasr-server，与 FastAPI 同进程
- 滚动窗口推理：每 1s 取最近 5s 音频做一次推理，partial 随音频增长而增长
- asyncio.to_thread 跑阻塞推理，不阻塞事件循环
- WS 下行事件用 dataclass + to_dict，WS 路由层直接 send_json

为什么用滚动窗口而不是"每帧全量推理"？
- SenseVoice 不是原生流式模型，全量推理是 O(n²)
- 滚动窗口把单次推理量固定在 ~5s 音频，CPU 可控
- partial 文本随窗口滚动自然增长，体感"边说边出字"

FunASR 输出格式：
- 返回 list[OrderedDict]，每个含 'text' / 'lang' / 'timestamp' 等
- SenseVoice 在 text 前会带 <|zh|><|NEUTRAL|><|Speech|><|withitn|> 标签
- _clean_sensevoice_output 把这些标签移除
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

import numpy as np

from app.common.error_code import ErrorCode
from app.config import settings

logger = logging.getLogger(__name__)


class STTEventType(str, Enum):
    """WebSocket 下行事件类型。"""

    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"


@dataclass
class STTEvent:
    """WebSocket 下行事件（partial / final / error）。"""

    type: STTEventType
    text: str = ""
    t0: float = 0.0
    t1: float = 0.0
    code: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "text": self.text,
            "t0": self.t0,
            "t1": self.t1,
            "code": self.code,
            "message": self.message,
        }


class VoiceStreamingService:
    """FunASR SenseVoice-Small 流式 STT 服务（lazy singleton，线程安全）。"""

    # 每 1000ms 触发一次部分识别
    _INFER_INTERVAL_MS = 1000
    # 连续错误上限：超过则停止 stream 并报 error
    _MAX_CONSECUTIVE_ERRORS = 3

    _instance: "VoiceStreamingService | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "VoiceStreamingService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._model = None
        self._model_lock = threading.Lock()
        self._initialized = True

    def _get_model(self):
        """Lazy load FunASR model。首次调用时下载并加载模型。"""
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    logger.info(
                        "loading FunASR model: %s (device=%s, quantize=%s)",
                        settings.voice_interview.funasr_model,
                        settings.voice_interview.funasr_device,
                        settings.voice_interview.funasr_quantize,
                    )
                    from funasr import AutoModel  # 重量级延迟导入

                    self._model = AutoModel(
                        model=settings.voice_interview.funasr_model,
                        device=settings.voice_interview.funasr_device,
                        quantize=settings.voice_interview.funasr_quantize,
                        disable_update=True,
                    )
                    logger.info("FunASR model loaded")
        return self._model

    def _transcribe_sync(self, pcm_bytes: bytes, sample_rate: int) -> str:
        """同步调用 FunASR。返回识别文本（已清理标签）。

        必须在 to_thread 中调用。
        """
        if not pcm_bytes:
            return ""
        # Int16 PCM (-32768..32767) → float32 (-1.0..1.0)
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        model = self._get_model()
        with self._model_lock:
            result = model.generate(
                input=audio,
                sampling_rate=sample_rate,
                disable_pbar=True,
            )

        if not result:
            return ""
        first = result[0] if isinstance(result, list) else result
        text = first.get("text", "") if hasattr(first, "get") else ""
        return _clean_sensevoice_output(text).strip()

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
        sample_rate: int | None = None,
    ) -> AsyncIterator[STTEvent]:
        """流式识别。

        Args:
            audio_chunks: 异步迭代器，每项是单声道 Int16 LE PCM bytes
            sample_rate: 采样率，默认用配置值 (16kHz)

        Yields:
            STTEvent 序列：多个 partial → 一个 final（或 error 终止）
        """
        if sample_rate is None:
            sample_rate = settings.voice_interview.streaming_stt_sample_rate

        max_session_seconds = settings.voice_interview.streaming_stt_max_session_seconds

        buffer = bytearray()
        started_at = time.monotonic()
        last_text = ""
        last_infer_at = 0.0
        consecutive_errors = 0

        try:
            async for pcm in audio_chunks:
                # 硬上限：超过 max_session_seconds 主动终止
                if time.monotonic() - started_at > max_session_seconds:
                    yield STTEvent(
                        type=STTEventType.ERROR,
                        code=ErrorCode.STT_STREAM_ERROR.value,
                        message="session_timeout",
                    )
                    return

                buffer.extend(pcm)
                now = time.monotonic()

                # 周期性 partial 推理
                # 注意：每次都转写完整 buffer，不能用"最后 5s 滚动窗口"——
                # 那样会丢掉前面的内容（用户测试发现长语音只识别最后一句）
                # SenseVoice CPU 17x 实时，单次推理 ~60ms/秒音频，O(n²) 可控
                if len(buffer) > 0 and (now - last_infer_at) * 1000 >= self._INFER_INTERVAL_MS:
                    last_infer_at = now
                    audio_chunk = bytes(buffer)
                    try:
                        text = await asyncio.to_thread(self._transcribe_sync, audio_chunk, sample_rate)
                        consecutive_errors = 0
                        if text and text != last_text:
                            last_text = text
                            yield STTEvent(
                                type=STTEventType.PARTIAL,
                                text=text,
                                t0=0.0,
                                t1=now - started_at,
                            )
                    except Exception as e:  # noqa: BLE001
                        consecutive_errors += 1
                        logger.warning("FunASR partial failed (consecutive=%d): %s", consecutive_errors, e)
                        if consecutive_errors >= self._MAX_CONSECUTIVE_ERRORS:
                            yield STTEvent(
                                type=STTEventType.ERROR,
                                code=ErrorCode.STT_STREAM_ERROR.value,
                                message=f"too many consecutive errors: {e}",
                            )
                            return
                        yield STTEvent(
                            type=STTEventType.ERROR,
                            code=ErrorCode.STT_STREAM_ERROR.value,
                            message=f"transcribe failed: {e}",
                        )
        except Exception as e:  # noqa: BLE001
            logger.exception("stream_transcribe outer failure")
            yield STTEvent(
                type=STTEventType.ERROR,
                code=ErrorCode.STT_STREAM_ERROR.value,
                message=f"stream error: {e}",
            )
            return

        # Final：流结束后对完整 buffer 跑一次推理
        # 即使 buffer 为空也发 final 事件（客户端用来确认流正常结束）
        try:
            text = ""
            if buffer:
                text = await asyncio.to_thread(self._transcribe_sync, bytes(buffer), sample_rate)
            yield STTEvent(
                type=STTEventType.FINAL,
                text=text,
                t0=0.0,
                t1=time.monotonic() - started_at,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("FunASR final failed")
            yield STTEvent(
                type=STTEventType.ERROR,
                code=ErrorCode.STT_STREAM_ERROR.value,
                message=f"finalize failed: {e}",
            )


_SENSEVOICE_TAG_RE = re.compile(r"<\|[^|]+\|>")


def _clean_sensevoice_output(text: str) -> str:
    """清理 SenseVoice 输出的特殊标签。

    SenseVoice 默认会在 text 前面带 <|lang|><|emotion|><|type|><|itn|> 等标签，
    例如 <|zh|><|NEUTRAL|><|Speech|><|withitn|>你好世界。流式场景下需要去掉。
    """
    return _SENSEVOICE_TAG_RE.sub("", text)


# 模块级单例
voice_streaming_service = VoiceStreamingService()
