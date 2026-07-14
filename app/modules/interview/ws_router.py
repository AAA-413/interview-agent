"""面试模块的 WebSocket 路由。

当前包含：
- /voice/stream: 流式 STT（FunASR SenseVoice-Small）

WebSocket 鉴权说明：
- HTTP 的 auth_middleware 不覆盖 WebSocket，需要在 handler 内手动解码 JWT
- 鉴权方式：客户端通过 query 参数 ?token=<jwt> 传 token
- 鉴权失败用 WS close code 1008

线协议（参考 voice_streaming_service.py 中的 STTEvent）：
- C→S 第一帧（可选）：JSON {"type":"start", "sampleRate":16000, "language":"zh"}
- C→S 后续帧：binary（Int16 LE 单声道 PCM，每帧 100-250ms）
- C→S 终止（可选）：JSON {"type":"end"}
- S→C：JSON {"type":"partial|final|error", ...}
"""
import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.modules.auth.security import decode_access_token
from app.modules.interview.voice_streaming_service import STTEventType, voice_streaming_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _pcm_chunker(websocket: WebSocket) -> AsyncIterator[bytes]:
    """从 WebSocket 持续读取 binary 帧，遇到 end 帧 / disconnect 停止。"""
    while True:
        try:
            msg = await websocket.receive()
        except WebSocketDisconnect:
            return

        msg_type = msg.get("type")
        if msg_type == "websocket.disconnect":
            return

        if "bytes" in msg and msg["bytes"] is not None:
            yield msg["bytes"]
        elif "text" in msg and msg["text"] is not None:
            try:
                payload = json.loads(msg["text"])
            except json.JSONDecodeError:
                logger.warning("invalid JSON control frame: %r", msg["text"])
                continue
            if payload.get("type") == "end":
                return
        # 其他类型（start 已经在 handler 里读过），忽略


@router.websocket("/voice/stream")
async def voice_stream_ws(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """流式 STT WebSocket 端点。客户端必须带 ?token=<jwt>。"""
    # ---- 1. 鉴权（HTTP 中间件不覆盖 WS）----
    payload = decode_access_token(token)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
        return
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid_token")
        return

    await websocket.accept()

    # ---- 2. 尝试读首帧（可作为 start 控制消息）----
    sample_rate: int | None = None
    first_bytes: bytes | None = None
    try:
        first = await asyncio.wait_for(websocket.receive(), timeout=2.0)
        if "text" in first and first["text"] is not None:
            try:
                payload_json = json.loads(first["text"])
                if payload_json.get("type") == "start":
                    sr = payload_json.get("sampleRate")
                    if isinstance(sr, int) and sr > 0:
                        sample_rate = sr
            except json.JSONDecodeError:
                logger.warning("first frame not valid JSON, ignored")
        elif "bytes" in first and first["bytes"] is not None:
            first_bytes = first["bytes"]
    except asyncio.TimeoutError:
        # 客户端没在 2s 内发首帧 — 正常，继续
        pass

    # ---- 3. 构造 PCM 流迭代器 ----
    if first_bytes is not None:
        async def _chunks() -> AsyncIterator[bytes]:
            yield first_bytes
            async for c in _pcm_chunker(websocket):
                yield c
        chunks_iter: AsyncIterator[bytes] = _chunks()
    else:
        chunks_iter = _pcm_chunker(websocket)

    # ---- 4. 跑流式识别 ----
    try:
        async for event in voice_streaming_service.stream_transcribe(
            chunks_iter, sample_rate=sample_rate
        ):
            await websocket.send_json(event.to_dict())
            if event.type == STTEventType.FINAL:
                break
    except WebSocketDisconnect:
        logger.info("voice stream WS disconnected by client (user=%s)", user_id)
        return
    except Exception as e:  # noqa: BLE001
        logger.exception("voice stream WS failed (user=%s)", user_id)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "code": 1005,
                    "message": f"server error: {e}",
                    "text": "",
                    "t0": 0.0,
                    "t1": 0.0,
                }
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:  # noqa: BLE001
            pass
        return

    # ---- 5. 正常关闭 ----
    try:
        await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
    except Exception:  # noqa: BLE001
        pass
