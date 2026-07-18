/**
 * VoiceStreamClient — 浏览器侧流式 STT WebSocket 客户端。
 *
 * 用法：
 *   const client = new VoiceStreamClient({ onPartial, onFinal, onError });
 *   await client.connect(accessToken, { sampleRate: 16000 });
 *   client.sendAudio(pcmBytes);  // 多次
 *   client.endStream();           // 触发 server final
 *   // 或 client.close() 强制断开
 *
 * 鉴权：token 通过 query 参数 ?token=<jwt> 传给后端（HTTP 中间件不覆盖 WS）
 * URL：开发走 Vite 代理 /api/interview/voice/stream，生产同源
 *
 * 不做自动重连 — 上层 hook 决定降级到 batch 模式还是提示用户
 */

import { apiUrl } from './request';
import type { STTEvent, STTStartMessage, STTEndMessage, VoiceStreamListeners } from '../types/voiceStream';

const WS_PATH = '/api/interview/voice/stream';

export interface VoiceStreamConfig {
  sampleRate: number;
  language?: string;
  /** WS endpoint 路径，默认 /api/interview/voice/stream */
  path?: string;
}

export class VoiceStreamClient {
  private ws: WebSocket | null = null;
  private listeners: VoiceStreamListeners;

  constructor(listeners: VoiceStreamListeners = {}) {
    this.listeners = listeners;
  }

  /** 打开 WS 连接。返回 Promise，连接成功 resolve，失败 reject。 */
  connect(token: string, config: VoiceStreamConfig): Promise<void> {
    return new Promise((resolve, reject) => {
      const path = config.path ?? WS_PATH;
      const url = `${apiUrl(path)}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      // 注意：浏览器 WebSocket API 不支持设置 header，token 只能走 query
      this.ws = ws;

      const onOpen = () => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onError);
        this.listeners.onOpen?.();
        // 立即发 start
        const start: STTStartMessage = {
          type: 'start',
          sampleRate: config.sampleRate,
          language: config.language,
        };
        ws.send(JSON.stringify(start));
        resolve();
      };
      const onError = (ev: Event) => {
        ws.removeEventListener('open', onOpen);
        ws.removeEventListener('error', onError);
        reject(new Error(`WebSocket connection failed: ${(ev as ErrorEvent).message ?? 'unknown'}`));
      };

      ws.addEventListener('open', onOpen);
      ws.addEventListener('error', onError);
      ws.addEventListener('message', this.handleMessage);
      ws.addEventListener('close', this.handleClose);
    });
  }

  /** 发送一段 Int16 LE PCM bytes。WS 必须已 open。 */
  sendAudio(pcm: ArrayBuffer | Uint8Array): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not open');
    }
    // WebSocket.send 支持 Blob / ArrayBuffer / string
    this.ws.send(pcm);
  }

  /** 发送 end 控制帧，触发服务端 final。 */
  endStream(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }
    const end: STTEndMessage = { type: 'end' };
    this.ws.send(JSON.stringify(end));
  }

  /** 强制关闭 WS。 */
  close(code = 1000, reason = 'client_close'): void {
    if (this.ws) {
      try {
        this.ws.close(code, reason);
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }

  /** 是否已 open。 */
  isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private handleMessage = (ev: MessageEvent) => {
    if (typeof ev.data !== 'string') {
      // 二进制帧不是协议的一部分
      return;
    }
    let event: STTEvent;
    try {
      event = JSON.parse(ev.data);
    } catch {
      this.listeners.onError?.(0, `Invalid JSON from server: ${ev.data.slice(0, 200)}`);
      return;
    }
    switch (event.type) {
      case 'partial':
        this.listeners.onPartial?.(event.text, event.t1);
        break;
      case 'final':
        this.listeners.onFinal?.(event.text, event.t1);
        break;
      case 'error':
        this.listeners.onError?.(event.code, event.message);
        break;
    }
  };

  private handleClose = (ev: CloseEvent) => {
    this.listeners.onClose?.(ev.code, ev.reason);
    this.ws = null;
  };
}
