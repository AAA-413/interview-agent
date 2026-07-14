/**
 * 流式 STT WebSocket 消息类型。
 *
 * 与后端 app/modules/interview/voice_streaming_service.py 的 STTEvent 对应。
 * 使用 discriminated union 便于 TypeScript 收窄类型。
 */

/** 服务端下行事件 */
export type STTEvent =
  | {
      type: 'partial';
      text: string;
      t0: number;
      t1: number;
    }
  | {
      type: 'final';
      text: string;
      t0: number;
      t1: number;
    }
  | {
      type: 'error';
      text: string;
      t0: number;
      t1: number;
      code: number;
      message: string;
    };

/** 客户端上行 start 控制帧 */
export interface STTStartMessage {
  type: 'start';
  sampleRate: number;
  language?: string;
}

/** 客户端上行 end 控制帧 */
export interface STTEndMessage {
  type: 'end';
}

/** 客户端上行所有控制消息 union */
export type STTControlMessage = STTStartMessage | STTEndMessage;

/** 事件订阅回调 */
export interface VoiceStreamListeners {
  onPartial?: (text: string, t1: number) => void;
  onFinal?: (text: string, t1: number) => void;
  onError?: (code: number, message: string) => void;
  onClose?: (code: number, reason: string) => void;
  onOpen?: () => void;
}

/** WS 连接状态 */
export type VoiceStreamState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';
