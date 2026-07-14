/**
 * useVoiceInput — 统一的语音输入 hook。
 *
 * mode='stream' (主用)：
 *   - getUserMedia + AudioContext + AudioWorklet 采集 PCM
 *   - 48kHz → 16kHz 抽取 + Float32 → Int16 转换
 *   - 按 200ms 切片 → WebSocket 推送 → 收 partial / final
 *   - onCommit 在收到 final 时调
 *
 * mode='batch' (回退)：
 *   - getUserMedia + MediaRecorder 采集到 Blob
 *   - stop 时调 interviewApi.transcribeVoice → onCommit(text)
 *
 * 状态机：idle → recording/streaming → transcribing（仅 batch） → idle
 *                                                  ↓
 *                                                error → 1.5s 后回 idle
 *
 * 不做自动重连 — 流式失败时上层可切到 batch 模式重试
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { interviewApi } from '../api/interview';
import { VoiceStreamClient } from '../api/voiceStream';
import {
  PCM_SAMPLE_RATE,
  VOICE_ERROR_MESSAGES,
  cleanTranscript,
  getAudioFileExtension,
  getPreferredAudioMimeType,
} from '../utils/voice';

export type VoiceMode = 'batch' | 'stream';
export type VoiceState = 'idle' | 'recording' | 'streaming' | 'transcribing' | 'error';

export interface UseVoiceInputOptions {
  mode: VoiceMode;
  /** 用户接受结果时（流式 final / 批式 transcribe 完成）调 */
  onCommit: (text: string) => void;
  /** 错误回调（鉴权失败、ASR 错误、设备无权限等） */
  onError?: (err: Error) => void;
  /** 拿当前 JWT（WS 鉴权用），返回 null 表示未登录 */
  getToken?: () => string | null;
}

export interface UseVoiceInputReturn {
  voiceState: VoiceState;
  voiceError: string;
  recordingSeconds: number;
  partialText: string;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  cancel: () => void;
}

const ERROR_RECOVER_MS = 1500;
const STREAM_CHUNK_MS = 200; // 每 200ms 推一段

function getVoiceErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    if (err.name in VOICE_ERROR_MESSAGES) {
      return VOICE_ERROR_MESSAGES[err.name] ?? err.message;
    }
    return err.message;
  }
  return '录音发生未知错误';
}

export function useVoiceInput(options: UseVoiceInputOptions): UseVoiceInputReturn {
  const { mode, onCommit, onError, getToken } = options;

  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [voiceError, setVoiceError] = useState<string>('');
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [partialText, setPartialText] = useState<string>('');

  // Refs（不变更时不需要触发渲染）
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const errorRecoverTimerRef = useRef<number | null>(null);

  // 流式专用
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const wsClientRef = useRef<VoiceStreamClient | null>(null);
  // PCM 缓冲（Int16 at 16kHz）
  const pcmBufferRef = useRef<number[]>([]);
  const sourceSampleRateRef = useRef<number>(PCM_SAMPLE_RATE);

  // 稳定的 callback refs（避免 useEffect 反复重连）
  const onCommitRef = useRef(onCommit);
  const onErrorRef = useRef(onError);
  onCommitRef.current = onCommit;
  onErrorRef.current = onError;

  const enterError = useCallback((err: unknown) => {
    const msg = getVoiceErrorMessage(err);
    setVoiceError(msg);
    setVoiceState('error');
    onErrorRef.current?.(err instanceof Error ? err : new Error(msg));
    // 1.5s 后自动回 idle
    if (errorRecoverTimerRef.current !== null) {
      window.clearTimeout(errorRecoverTimerRef.current);
    }
    errorRecoverTimerRef.current = window.setTimeout(() => {
      setVoiceState('idle');
      setVoiceError('');
      setPartialText('');
    }, ERROR_RECOVER_MS);
  }, []);

  const startTimer = useCallback(() => {
    if (recordingTimerRef.current !== null) return;
    const startTime = Date.now();
    setRecordingSeconds(0);
    recordingTimerRef.current = window.setInterval(() => {
      setRecordingSeconds(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  }, []);

  // ============================ 流式 ============================
  const startStream = useCallback(async () => {
    setVoiceError('');
    setPartialText('');

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    mediaStreamRef.current = stream;

    // 准备 WebSocket
    const token = getToken?.();
    if (!token) {
      stream.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
      throw new Error('未登录，无法使用流式识别');
    }

    const wsClient = new VoiceStreamClient({
      onPartial: (text) => {
        setPartialText(cleanTranscript(text));
      },
      onFinal: (text) => {
        const cleaned = cleanTranscript(text);
        if (cleaned) onCommitRef.current(cleaned);
        setVoiceState('idle');
        setPartialText('');
      },
      onError: (code, message) => {
        enterError(new Error(`STT error (${code}): ${message}`));
      },
      onClose: () => {
        setVoiceState((prev) => (prev === 'streaming' ? 'idle' : prev));
      },
    });
    wsClientRef.current = wsClient;

    // 准备 AudioContext + AudioWorklet
    const AudioCtxCtor: typeof AudioContext = window.AudioContext
      || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtxCtor();
    audioContextRef.current = ctx;
    sourceSampleRateRef.current = ctx.sampleRate;

    await ctx.audioWorklet.addModule('/audio-worklets/pcm-capture.js');
    const workletNode = new AudioWorkletNode(ctx, 'pcm-capture');
    workletNodeRef.current = workletNode;

    const sourceNode = ctx.createMediaStreamSource(stream);
    sourceNodeRef.current = sourceNode;
    sourceNode.connect(workletNode);

    // Float32 帧 → Int16 抽取 → 缓冲到 200ms → WS 推
    const targetChunkSamples = Math.floor((STREAM_CHUNK_MS * PCM_SAMPLE_RATE) / 1000);
    workletNode.port.onmessage = (ev) => {
      const frame = ev.data as Float32Array;
      // 抽样到 PCM_SAMPLE_RATE（默认源 48kHz 抽 3 倍）
      const factor = Math.max(1, Math.round(sourceSampleRateRef.current / PCM_SAMPLE_RATE));
      for (let i = 0; i < frame.length; i += factor) {
        const s = Math.max(-1, Math.min(1, frame[i]));
        pcmBufferRef.current.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      }
      if (pcmBufferRef.current.length >= targetChunkSamples) {
        const chunk = new Int16Array(pcmBufferRef.current.splice(0, targetChunkSamples));
        try {
          wsClientRef.current?.sendAudio(chunk.buffer);
        } catch {
          // WS 可能在重连中
        }
      }
    };

    // 连接 WS（onopen 后自动发 start）
    await wsClient.connect(token, {
      sampleRate: PCM_SAMPLE_RATE,
      language: 'zh',
    });

    setVoiceState('streaming');
    startTimer();
  }, [enterError, getToken, startTimer]);

  const stopStream = useCallback(async () => {
    stopTimer();
    const ws = wsClientRef.current;
    if (ws && ws.isOpen()) {
      ws.endStream();
    }
    // 等待 final 由 onFinal callback 触发，状态转换在 onFinal 里
  }, [stopTimer]);

  // ============================ 批式 ============================
  const startBatch = useCallback(async () => {
    setVoiceError('');
    setPartialText('');

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    mediaStreamRef.current = stream;

    const mimeType = getPreferredAudioMimeType();
    const recorder = new MediaRecorder(
      stream,
      mimeType ? { mimeType } : undefined,
    );
    mediaRecorderRef.current = recorder;
    audioChunksRef.current = [];

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        audioChunksRef.current.push(event.data);
      }
    };

    recorder.onstop = async () => {
      stopTimer();
      const mime = recorder.mimeType || mimeType || 'audio/webm';
      const blob = new Blob(audioChunksRef.current, { type: mime });
      audioChunksRef.current = [];

      // 释放麦克风
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop());
        mediaStreamRef.current = null;
      }

      if (blob.size < 1024) {
        enterError(new Error('录音过短，请重试'));
        return;
      }

      setVoiceState('transcribing');
      try {
        const ext = getAudioFileExtension(mime);
        const file = new File([blob], `recording.${ext}`, { type: mime });
        const result = await interviewApi.transcribeVoice(file);
        const cleaned = cleanTranscript(result.text);
        if (cleaned) onCommitRef.current(cleaned);
        setVoiceState('idle');
      } catch (err) {
        enterError(err);
      }
    };

    recorder.onerror = (event: Event) => {
      const error = (event as unknown as { error?: { message?: string } }).error;
      enterError(new Error(`MediaRecorder error: ${error?.message ?? 'unknown'}`));
    };

    recorder.start(1000);
    setVoiceState('recording');
    startTimer();
  }, [enterError, startTimer, stopTimer]);

  const stopBatch = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop(); // onstop 触发 transcribe
    }
  }, []);

  // ============================ 公开 API ============================
  const start = useCallback(async () => {
    try {
      if (mode === 'stream') {
        await startStream();
      } else {
        await startBatch();
      }
    } catch (err) {
      enterError(err);
    }
  }, [mode, startStream, startBatch, enterError]);

  const stop = useCallback(async () => {
    try {
      if (mode === 'stream') {
        await stopStream();
      } else {
        await stopBatch();
      }
    } catch (err) {
      enterError(err);
    }
  }, [mode, stopStream, stopBatch, enterError]);

  const cancel = useCallback(() => {
    stopTimer();
    if (errorRecoverTimerRef.current !== null) {
      window.clearTimeout(errorRecoverTimerRef.current);
      errorRecoverTimerRef.current = null;
    }
    // 流式
    if (wsClientRef.current) {
      wsClientRef.current.close();
      wsClientRef.current = null;
    }
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (sourceNodeRef.current) {
      sourceNodeRef.current.disconnect();
      sourceNodeRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => undefined);
      audioContextRef.current = null;
    }
    pcmBufferRef.current = [];
    // 批式
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      try {
        mediaRecorderRef.current.ondataavailable = null;
        mediaRecorderRef.current.onstop = null;
        mediaRecorderRef.current.stop();
      } catch {
        // ignore
      }
      mediaRecorderRef.current = null;
    }
    audioChunksRef.current = [];
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    setVoiceState('idle');
    setVoiceError('');
    setPartialText('');
    setRecordingSeconds(0);
  }, [stopTimer]);

  // 卸载清理
  useEffect(() => {
    return () => {
      cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    voiceState,
    voiceError,
    recordingSeconds,
    partialText,
    start,
    stop,
    cancel,
  };
}
