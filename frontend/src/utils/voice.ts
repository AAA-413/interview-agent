/**
 * Voice / 录音相关纯函数工具。
 *
 * 这些函数是纯逻辑（无 React、无 IO），从 InterviewPage.tsx 抽出后
 * 可被 useVoiceInput hook、AudioWorklet 包装、WS 客户端等多处复用。
 */

/**
 * DOMException name → 中文提示
 */
export const VOICE_ERROR_MESSAGES: Record<string, string> = {
  NotAllowedError: '麦克风权限被拒绝，请在浏览器地址栏允许后再试',
  NotFoundError: '没有检测到可用麦克风',
  NotReadableError: '麦克风正在被其他应用占用',
  SecurityError: '当前页面不允许访问麦克风',
};

/**
 * 选择浏览器支持的 audio MIME type。优先 webm/opus，回退到 webm / ogg / mp4。
 * 返回空字符串表示浏览器都不支持（由调用方决定是否走裸 PCM 路径）。
 */
export const getPreferredAudioMimeType = (): string => {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
};

/**
 * MIME type → 文件扩展名（用于上传时给后端一个 hint）
 */
export const getAudioFileExtension = (mimeType: string): string => {
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mp4')) return 'm4a';
  if (mimeType.includes('mpeg')) return 'mp3';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
};

/**
 * 清理 ASR 返回文本中的多余空白。
 */
export const cleanTranscript = (text: string): string => text.replace(/\s+/g, ' ').trim();

/**
 * AudioWorklet 输出的 PCM 采样率（与服务端配置一致）
 */
export const PCM_SAMPLE_RATE = 16000;
