/**
 * AudioWorklet: 浏览器音频采集处理器。
 *
 * 在音频线程运行，接收输入设备的 Float32 帧（通常是 128 samples/帧），
 * 复制后通过 port.postMessage 转发到主线程。主线程负责：
 *   1. Float32 → Int16 转换
 *   2. 48kHz → 16kHz 重采样（线性插值）
 *   3. 按 200ms 切片
 *   4. 通过 WebSocket 推送到后端
 *
 * 这个 worklet 不做重采样是因为：
 * - AudioContext 的 sampleRate 跟设备/浏览器有关，48kHz 是常见值但不是固定
 * - 重采样逻辑放在主线程里更易调试 / 单测
 * - worklet 只负责"把原始帧搬出音频线程"
 *
 * 注意：这个文件是浏览器原生 JS（不是 TS），由 Vite 通过 public/ 目录
 * 直接以原文件形式 serve，URL 是 /audio-worklets/pcm-capture.js。
 */

class PCMCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const channel = input[0];
    if (!channel || channel.length === 0) return true;

    // 必须复制 — input 缓冲会被下一帧覆盖
    const copy = new Float32Array(channel);
    this.port.postMessage(copy, [copy.buffer]);
    return true;
  }
}

registerProcessor('pcm-capture', PCMCaptureProcessor);
