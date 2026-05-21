import asyncio
import logging
import os
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import UploadFile

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.config import settings
from app.modules.interview.schemas import VoiceTranscriptionDTO

logger = logging.getLogger(__name__)

_CONTENT_TYPE_SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


class VoiceTranscriptionService:
    def __init__(self) -> None:
        self._model = None
        self._model_lock = Lock()

    async def transcribe(self, file: UploadFile) -> VoiceTranscriptionDTO:
        if settings.voice_interview.stt_provider != "local_whisper":
            raise BusinessException(ErrorCode.BAD_REQUEST, "当前仅支持本地 Whisper 语音识别")

        content_type = (file.content_type or "").split(";")[0].lower()
        if content_type and not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
            raise BusinessException(ErrorCode.BAD_REQUEST, "请上传音频文件")

        max_bytes = settings.voice_interview.max_audio_size_mb * 1024 * 1024
        content = await file.read(max_bytes + 1)
        if not content:
            raise BusinessException(ErrorCode.BAD_REQUEST, "没有收到音频内容")
        if len(content) > max_bytes:
            raise BusinessException(
                ErrorCode.BAD_REQUEST, f"音频过大，请控制在 {settings.voice_interview.max_audio_size_mb}MB 内"
            )

        suffix = _CONTENT_TYPE_SUFFIXES.get(content_type, Path(file.filename or "").suffix or ".webm")
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(content)
                temp_path = temp_file.name

            return await asyncio.to_thread(self._transcribe_sync, temp_path)
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    def _transcribe_sync(self, audio_path: str) -> VoiceTranscriptionDTO:
        try:
            model = self._get_model()
            segments, info = model.transcribe(
                audio_path,
                language="zh",
                vad_filter=True,
                beam_size=5,
                condition_on_previous_text=False,
            )
            text = "，".join(segment.text.strip() for segment in segments if segment.text.strip())
        except BusinessException:
            raise
        except Exception as exc:
            logger.exception("本地语音识别失败")
            raise BusinessException(ErrorCode.AI_SERVICE_ERROR, "语音识别失败，请重新录音或手动输入") from exc

        return VoiceTranscriptionDTO(
            text=text.strip(),
            language=getattr(info, "language", None),
            duration=getattr(info, "duration", None),
        )

    def _get_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise BusinessException(
                    ErrorCode.AI_SERVICE_ERROR,
                    "本地语音识别依赖未安装，请先安装 faster-whisper",
                ) from exc

            logger.info(
                "正在加载本地语音识别模型: model=%s, device=%s, compute_type=%s",
                settings.voice_interview.stt_model,
                settings.voice_interview.stt_device,
                settings.voice_interview.stt_compute_type,
            )
            if settings.voice_interview.stt_hf_endpoint:
                os.environ.setdefault("HF_ENDPOINT", settings.voice_interview.stt_hf_endpoint)
            self._model = WhisperModel(
                settings.voice_interview.stt_model,
                device=settings.voice_interview.stt_device,
                compute_type=settings.voice_interview.stt_compute_type,
            )
            return self._model


voice_transcription_service = VoiceTranscriptionService()
