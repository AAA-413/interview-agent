"""VoiceStreamingService 单元测试。

Mock 掉 FunASR 推理，验证：
- 滚动窗口 partial 行为
- final 事件
- 连续错误终止
- session 超时
- SenseVoice 标签清理
"""
import asyncio

import pytest

from app.common.error_code import ErrorCode
from app.modules.interview.voice_streaming_service import (
    STTEvent,
    STTEventType,
    VoiceStreamingService,
    _clean_sensevoice_output,
)


class FakeFunASR:
    """Mock FunASR 推理。返回固定文本或根据调用次数返回不同文本。"""

    def __init__(self, responses: list[str] | None = None, raise_after: int | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0
        self.raise_after = raise_after
        self.last_input_bytes: bytes | None = None

    def __call__(self, pcm_bytes: bytes, sample_rate: int) -> str:
        self.last_input_bytes = pcm_bytes
        if self.raise_after is not None and self.call_count >= self.raise_after:
            self.call_count += 1
            raise RuntimeError(f"fake funasr error at call {self.call_count}")
        self.call_count += 1
        if self.responses:
            idx = min(self.call_count - 1, len(self.responses) - 1)
            return self.responses[idx]
        return f"text-from-{len(pcm_bytes)}-bytes"


def _patch_transcribe(monkeypatch, service: VoiceStreamingService, fake: FakeFunASR) -> None:
    """直接 monkeypatch 服务的 _transcribe_sync 方法。"""
    monkeypatch.setattr(service, "_transcribe_sync", fake)


def _make_audio_chunker(chunks: list[bytes], delay: float = 0.0):
    """把 list[bytes] 包成 async iterator，可选每片 delay。"""
    async def _iter():
        for chunk in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield chunk
    return _iter()


async def test_stream_transcribe_yields_partials_and_final(monkeypatch):
    """正常流：多个 partial + 1 个 final。"""
    service = VoiceStreamingService()
    # 模拟 _INFER_INTERVAL_MS 调短，避免测试跑 1s
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)

    fake = FakeFunASR(responses=["你好", "你好世界", "你好世界今天"])
    _patch_transcribe(monkeypatch, service, fake)

    pcm_1s = b"\x00\x00" * 16000  # 1s @ 16kHz
    chunks = _make_audio_chunker([pcm_1s, pcm_1s, pcm_1s], delay=0.02)

    events: list[STTEvent] = []
    async for ev in service.stream_transcribe(chunks, sample_rate=16000):
        events.append(ev)
        if ev.type == STTEventType.FINAL:
            break

    partials = [e for e in events if e.type == STTEventType.PARTIAL]
    finals = [e for e in events if e.type == STTEventType.FINAL]
    assert len(partials) >= 1, f"expected at least 1 partial, got {len(partials)}"
    assert len(finals) == 1
    assert finals[0].text


async def test_stream_transcribe_handles_duplicate_partials(monkeypatch):
    """同一文本不重复发 partial。"""
    service = VoiceStreamingService()
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)

    fake = FakeFunASR(responses=["你好", "你好", "你好世界"])
    _patch_transcribe(monkeypatch, service, fake)

    pcm = b"\x00\x00" * 16000
    chunks = _make_audio_chunker([pcm] * 3, delay=0.02)

    events = []
    async for ev in service.stream_transcribe(chunks, sample_rate=16000):
        events.append(ev)
        if ev.type == STTEventType.FINAL:
            break

    partials = [e for e in events if e.type == STTEventType.PARTIAL]
    partial_texts = [p.text for p in partials]
    assert partial_texts == ["你好", "你好世界"], f"got {partial_texts}"


async def test_stream_transcribe_stops_after_max_consecutive_errors(monkeypatch):
    """连续推理错误达到上限后终止并报 error。"""
    service = VoiceStreamingService()
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)
    monkeypatch.setattr(VoiceStreamingService, "_MAX_CONSECUTIVE_ERRORS", 2)

    fake = FakeFunASR(raise_after=0)  # 每次都抛
    _patch_transcribe(monkeypatch, service, fake)

    pcm = b"\x00\x00" * 16000
    chunks = _make_audio_chunker([pcm] * 5, delay=0.02)

    events = []
    async for ev in service.stream_transcribe(chunks, sample_rate=16000):
        events.append(ev)

    error_events = [e for e in events if e.type == STTEventType.ERROR]
    assert len(error_events) >= 1
    assert "too many consecutive errors" in error_events[-1].message
    assert not any(e.type == STTEventType.FINAL for e in events)


async def test_stream_transcribe_session_timeout(monkeypatch):
    """单次会话超过 max_session_seconds 主动终止。"""
    service = VoiceStreamingService()
    from app.config import settings

    monkeypatch.setattr(settings.voice_interview, "streaming_stt_max_session_seconds", 0.1)
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 1000)  # 不触发推理

    chunks = _make_audio_chunker([b"\x00\x00" * 100] * 5, delay=0.05)

    events = []
    async for ev in service.stream_transcribe(chunks, sample_rate=16000):
        events.append(ev)

    error_events = [e for e in events if e.type == STTEventType.ERROR]
    assert any(e.message == "session_timeout" for e in error_events)


async def test_stream_transcribe_empty_audio():
    """没有音频数据：没有 partial 但会发 final（空文本）作为流结束信号。"""
    service = VoiceStreamingService()

    chunks = _make_audio_chunker([])

    events = []
    async for ev in service.stream_transcribe(chunks, sample_rate=16000):
        events.append(ev)

    assert not any(e.type == STTEventType.PARTIAL for e in events)
    # 即使 buffer 为空也会发 final，文本是 ""
    finals = [e for e in events if e.type == STTEventType.FINAL]
    assert len(finals) == 1
    assert finals[0].text == ""


def test_clean_sensevoice_output_strips_tags():
    """验证 SenseVoice 标签清理。"""
    assert _clean_sensevoice_output("你好世界") == "你好世界"
    assert (
        _clean_sensevoice_output("<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好世界") == "你好世界"
    )
    assert _clean_sensevoice_output("<|en|><|HAPPY|>hello world") == "hello world"
    assert _clean_sensevoice_output("") == ""
    # 多个标签
    assert (
        _clean_sensevoice_output("<|zh|><|NEUTRAL|><|Speech|>中间<|withitn|>文本") == "中间文本"
    )


def test_stt_event_to_dict():
    """验证事件序列化。"""
    event = STTEvent(
        type=STTEventType.PARTIAL,
        text="你好",
        t0=0.0,
        t1=1.5,
    )
    d = event.to_dict()
    assert d == {
        "type": "partial",
        "text": "你好",
        "t0": 0.0,
        "t1": 1.5,
        "code": 0,
        "message": "",
    }


async def test_stream_transcribe_uses_default_sample_rate(monkeypatch):
    """不传 sample_rate 时用配置默认值 (16kHz)。"""
    service = VoiceStreamingService()
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)

    fake = FakeFunASR(responses=["测试"])
    _patch_transcribe(monkeypatch, service, fake)

    pcm = b"\x00\x00" * 16000
    chunks = _make_audio_chunker([pcm], delay=0.02)

    events = []
    async for ev in service.stream_transcribe(chunks):
        events.append(ev)
        if ev.type == STTEventType.FINAL:
            break

    assert any(e.type == STTEventType.PARTIAL for e in events)
    assert fake.call_count >= 1
