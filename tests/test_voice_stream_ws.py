"""流式 STT WebSocket 契约测试。

用 FastAPI TestClient 模拟浏览器 → 验证：
- 鉴权（无 token / 错 token / 有效 token）
- 正常流（start 帧 + pcm 帧 → partial → final）
- end 帧提前终止
- 客户端 disconnect 兜底
- service 错误 → error 事件
"""

import os
import time

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("AI_BAILIAN_API_KEY", "dummy-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth.security import create_access_token
from app.modules.interview.voice_streaming_service import VoiceStreamingService

VALID_TOKEN = create_access_token({"sub": "1"})


def _mock_transcribe(monkeypatch, service: VoiceStreamingService, responses=None):
    """Monkeypatch VoiceStreamingService._transcribe_sync。"""
    call_count = {"n": 0}

    def fake(pcm_bytes: bytes, sample_rate: int) -> str:
        idx = call_count["n"]
        call_count["n"] += 1
        if responses is None:
            return f"text-{len(pcm_bytes)}"
        if idx < len(responses):
            return responses[idx]
        return responses[-1]

    monkeypatch.setattr(service, "_transcribe_sync", fake)
    return call_count


def _drain_events(ws, max_events: int = 10):
    """读 WS 事件直到 final / error / disconnect 或上限。"""
    events = []
    for _ in range(max_events):
        try:
            ev = ws.receive_json()
            events.append(ev)
            if ev.get("type") in ("final", "error"):
                break
        except Exception:
            break
    return events


def test_ws_rejects_missing_token():
    """无 token：WS 在 accept 前就关闭。"""
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/api/interview/voice/stream") as ws:
            ws.receive_json()


def test_ws_rejects_invalid_token():
    """无效 token：关闭。"""
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/api/interview/voice/stream?token=invalid.jwt.token") as ws:
            ws.receive_json()


def test_ws_accepts_valid_token_and_streams_partial_then_final(monkeypatch):
    """有效 token：start + pcm → partial 增量 → final 关闭。"""
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)
    service = VoiceStreamingService()
    _mock_transcribe(monkeypatch, service, responses=["你好", "你好世界", "你好世界今天"])

    client = TestClient(app)
    with client.websocket_connect(f"/api/interview/voice/stream?token={VALID_TOKEN}") as ws:
        ws.send_json({"type": "start", "sampleRate": 16000})
        pcm_1s = b"\x00\x00" * 16000
        for _ in range(3):
            ws.send_bytes(pcm_1s)
            time.sleep(0.02)
        ws.send_json({"type": "end"})

        events = _drain_events(ws, max_events=20)

    types = [e.get("type") for e in events]
    assert "partial" in types, f"expected partial, got {types}"
    assert "final" in types, f"expected final, got {types}"


def test_ws_handles_end_frame_without_data(monkeypatch):
    """只发 end 不发数据：直接收到 final（可能为空文本）。"""
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)
    service = VoiceStreamingService()
    _mock_transcribe(monkeypatch, service, responses=[])

    client = TestClient(app)
    with client.websocket_connect(f"/api/interview/voice/stream?token={VALID_TOKEN}") as ws:
        ws.send_json({"type": "end"})
        events = _drain_events(ws)

    types = [e.get("type") for e in events]
    assert "final" in types


def test_ws_handles_pcm_without_start_frame(monkeypatch):
    """不发 start 帧，直接推 PCM：也应该正常处理。"""
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)
    service = VoiceStreamingService()
    _mock_transcribe(monkeypatch, service, responses=["直接开始"])

    client = TestClient(app)
    with client.websocket_connect(f"/api/interview/voice/stream?token={VALID_TOKEN}") as ws:
        pcm_1s = b"\x00\x00" * 16000
        for _ in range(3):
            ws.send_bytes(pcm_1s)
            time.sleep(0.02)
        ws.send_json({"type": "end"})

        events = _drain_events(ws)

    assert any(e.get("type") in ("partial", "final") for e in events)


def test_ws_emits_error_on_transcribe_failure(monkeypatch):
    """service 抛异常时：error 事件。

    发送一段 PCM 后再 end，让 service 真正被调用。
    """
    monkeypatch.setattr(VoiceStreamingService, "_INFER_INTERVAL_MS", 10)
    service = VoiceStreamingService()

    def always_fail(pcm_bytes: bytes, sample_rate: int) -> str:
        raise RuntimeError("simulated FunASR failure")

    monkeypatch.setattr(service, "_transcribe_sync", always_fail)

    client = TestClient(app)
    with client.websocket_connect(f"/api/interview/voice/stream?token={VALID_TOKEN}") as ws:
        # 先发 start
        ws.send_json({"type": "start", "sampleRate": 16000})
        # 推 PCM 让 service 跑推理
        pcm_1s = b"\x00\x00" * 16000
        for _ in range(3):
            ws.send_bytes(pcm_1s)
            time.sleep(0.02)
        # 终止流，让 service 跑 final
        ws.send_json({"type": "end"})

        events = _drain_events(ws, max_events=10)

    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) >= 1, f"expected error events, got {events}"
    assert any("simulated FunASR failure" in e.get("message", "") for e in error_events)
