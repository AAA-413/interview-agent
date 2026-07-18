/**
 * VoiceMicButton — 麦克风按钮，5 态视觉。
 *
 * idle (灰)    - Mic 图标
 * recording (红) - MicOff 图标（录音中）
 * streaming (蓝) - MicOff 图标 + 脉冲
 * transcribing (黄) - Loader2 旋转
 * error (红)  - AlertCircle
 *
 * 颜色用 Tailwind class，hover/focus 跟周围环境保持一致。
 */

import { AlertCircle, Loader2, Mic, MicOff } from 'lucide-react';
import type { VoiceState } from '../hooks/useVoiceInput';

interface VoiceMicButtonProps {
  voiceState: VoiceState;
  onClick: () => void;
  disabled?: boolean;
}

const STATE_CONFIG: Record<VoiceState, {
  icon: typeof Mic;
  className: string;
  title: string;
}> = {
  idle: {
    icon: Mic,
    className: 'bg-slate-100 text-slate-600 hover:bg-slate-200',
    title: '点击开始录音',
  },
  recording: {
    icon: MicOff,
    className: 'bg-red-500 text-white hover:bg-red-600 animate-pulse',
    title: '点击停止（整段转写）',
  },
  streaming: {
    icon: MicOff,
    className: 'bg-blue-500 text-white hover:bg-blue-600 animate-pulse',
    title: '点击停止（流式识别）',
  },
  transcribing: {
    icon: Loader2,
    className: 'bg-amber-100 text-amber-700 cursor-wait',
    title: '正在转写...',
  },
  error: {
    icon: AlertCircle,
    className: 'bg-red-100 text-red-600',
    title: '录音出错',
  },
};

export function VoiceMicButton({ voiceState, onClick, disabled }: VoiceMicButtonProps) {
  const config = STATE_CONFIG[voiceState];
  const Icon = config.icon;
  const isSpinning = voiceState === 'transcribing';

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={config.title}
      aria-label={config.title}
      data-voice-state={voiceState}
      className={`flex h-10 w-10 items-center justify-center rounded-full transition-colors ${config.className} ${
        disabled ? 'cursor-not-allowed opacity-50' : ''
      }`}
    >
      <Icon className={`h-5 w-5 ${isSpinning ? 'animate-spin' : ''}`} />
    </button>
  );
}
