/**
 * VoiceStatusLine — 语音状态行。
 *
 * 显示当前 voice 状态 + 时长 / partial 预览 / 错误信息。
 * idle 状态下不渲染（节省空间）。
 *
 * 样式紧凑：放在 textarea 旁边或下面。
 */

import { AlertCircle, Loader2, Mic, Radio } from 'lucide-react';
import type { VoiceState } from '../hooks/useVoiceInput';

interface VoiceStatusLineProps {
  voiceState: VoiceState;
  recordingSeconds?: number;
  partialText?: string;
  voiceError?: string;
}

function formatSeconds(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export function VoiceStatusLine({
  voiceState,
  recordingSeconds = 0,
  partialText = '',
  voiceError = '',
}: VoiceStatusLineProps) {
  if (voiceState === 'idle') {
    return null;
  }

  let Icon: typeof Mic;
  let text: string;
  let className: string;

  switch (voiceState) {
    case 'recording':
      Icon = Mic;
      text = `录音中 ${formatSeconds(recordingSeconds)}`;
      className = 'text-red-600';
      break;
    case 'streaming':
      Icon = Radio;
      text = partialText
        ? `正在识别：${partialText}`
        : `正在识别 ${formatSeconds(recordingSeconds)}`;
      className = 'text-blue-600';
      break;
    case 'transcribing':
      Icon = Loader2;
      text = '正在转写...';
      className = 'text-amber-600';
      break;
    case 'error':
      Icon = AlertCircle;
      text = voiceError || '录音出错';
      className = 'text-red-600';
      break;
    default:
      Icon = Mic;
      text = '';
      className = '';
  }

  const isSpinning = voiceState === 'transcribing';

  return (
    <div
      className={`flex items-center gap-1.5 text-xs ${className}`}
      data-voice-state={voiceState}
      role="status"
      aria-live="polite"
    >
      <Icon className={`h-3.5 w-3.5 ${isSpinning ? 'animate-spin' : ''}`} />
      <span className="truncate">{text}</span>
    </div>
  );
}
